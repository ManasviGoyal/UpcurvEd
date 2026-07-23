# backend/agent/structured_video.py
"""
Structured Manim video generation, v3.

One LLM call returns a compact JSON scene plan. The backend then renders
five scenes with slower classroom pacing. One or two middle scenes may receive
a second, tightly-scoped LLM call for more creative Manim visuals, with safe
template fallback if that creative scene fails.

This intentionally avoids asking the LLM to return long multi-scene Python code,
which prevents token truncation errors such as: SyntaxError: '(' was never closed.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import uuid
from typing import Any

from backend.agent.code_sanitize import sanitize_minimally
from backend.agent.llm.clients import call_llm
from backend.agent.prompts import (
    STRUCTURED_VIDEO_CREATIVE_SCENE_SYSTEM,
    STRUCTURED_VIDEO_EDIT_SYSTEM,
    STRUCTURED_VIDEO_SYSTEM,
    build_structured_video_creative_scene_prompt,
    build_structured_video_edit_user_prompt,
    build_structured_video_user_prompt,
)
from backend.runner.job_runner import STORAGE, run_job_from_code, to_static_url

logger = logging.getLogger(f"app.{__name__}")


_ALLOWED_KINDS = (
    "title",
    "key_points",
    "diagram",
    "flow_diagram",
    "cycle_diagram",
    "timeline",
    "comparison",
    "chart",
    "system_map",
    "pseudo_3d",
    "creative",
    "recap",
)
_DEFAULT_KINDS = ["title", "key_points", "flow_diagram", "pseudo_3d", "recap"]


def _pick_provider_and_key(
    provider: str | None,
    provider_keys: dict[str, str] | None,
) -> tuple[str, str]:
    keys = provider_keys or {}
    prov = (provider or "").strip().lower()

    if prov in ("claude", "gemini", "openrouter"):
        key = keys.get(prov) or ""
        if not key:
            raise RuntimeError(f"Missing API key for provider '{prov}'.")
        return prov, key

    # Preserve the app's usual preference order.
    if keys.get("gemini"):
        return "gemini", keys["gemini"]
    if keys.get("claude"):
        return "claude", keys["claude"]
    if keys.get("openrouter"):
        return "openrouter", keys["openrouter"]

    raise RuntimeError("No provider keys available. Provide a Gemini, Claude, or OpenRouter key.")


def _extract_block(text: str, name: str) -> str:
    pattern = rf"<<<{re.escape(name)}>>>([\s\S]*?)<<<END_{re.escape(name)}>>>"
    match = re.search(pattern, text or "")
    return match.group(1).strip() if match else ""


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"\s*```$", "", clean).strip()

    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Conservative fallback: find the first JSON object-looking block.
    match = re.search(r"\{[\s\S]*\}", clean)
    if not match:
        raise RuntimeError("Structured video plan is missing valid JSON.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise RuntimeError("Structured video JSON was not an object.")
    return parsed


def _short_text(value: Any, limit: int, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\x00", "")
    return (text[:limit].strip() or fallback)


def _default_plan(topic: str) -> dict[str, Any]:
    safe_topic = _short_text(topic, 60, "Learning topic")
    return {
        "title": safe_topic,
        "audience": "general",
        "scenes": [
            {
                "id": 1,
                "kind": "title",
                "heading": safe_topic,
                "narration": f"This lesson introduces {safe_topic} with a clear visual overview.",
                "bullets": ["Big idea", "Visual map"],
                "visual_goal": "Open with a simple title visual and one central symbol.",
                "beats": [
                    {"say": f"Today we will build a visual understanding of {safe_topic}.", "visual": "Reveal the title and central symbol."},
                    {"say": "Watch for one main idea, one mechanism, and one takeaway.", "visual": "Reveal three short guide labels."},
                    {"say": "The goal is a clear mental picture, not a list of facts.", "visual": "Highlight the central symbol."},
                ],
                "duration_sec": 12,
            },
            {
                "id": 2,
                "kind": "key_points",
                "heading": "Core ideas",
                "narration": f"These key points explain the most important mechanisms behind {safe_topic}.",
                "bullets": ["Main mechanism", "Cause and effect", "Why it matters"],
                "visual_goal": "Reveal three connected ideas one at a time.",
                "beats": [
                    {"say": f"First, identify the main mechanism behind {safe_topic}.", "visual": "Reveal the first key idea."},
                    {"say": "Next, connect causes to effects instead of memorizing labels.", "visual": "Draw arrows between the ideas."},
                    {"say": "Finally, use the connection to predict what happens next.", "visual": "Highlight the takeaway idea."},
                ],
                "duration_sec": 15,
            },
            {
                "id": 3,
                "kind": "flow_diagram",
                "heading": "How it works",
                "narration": f"A step-by-step diagram shows how {safe_topic} moves from inputs to results.",
                "bullets": ["Input", "Process", "Result"],
                "visual_goal": "Show inputs moving through a process into an output.",
                "beats": [
                    {"say": "Start with the input or condition that begins the process.", "visual": "Reveal the input object."},
                    {"say": "Then show the middle step where the important change happens.", "visual": "Animate motion into the process object."},
                    {"say": "End by showing the result and the arrow that explains it.", "visual": "Reveal the output and highlight the flow."},
                ],
                "duration_sec": 17,
            },
            {
                "id": 4,
                "kind": "creative",
                "heading": "Inside view",
                "narration": f"A layered visual makes the hidden structure of {safe_topic} easier to understand.",
                "bullets": ["Outer layer", "Inside process", "Final effect"],
                "visual_goal": "Animate layered parts changing into one final effect.",
                "beats": [
                    {"say": "Now zoom into the part that is usually invisible.", "visual": "Reveal layered parts one by one."},
                    {"say": "Show how changing one layer changes the whole system.", "visual": "Move or transform the middle layer."},
                    {"say": "Connect the hidden change back to the visible result.", "visual": "Highlight the final effect."},
                ],
                "duration_sec": 18,
            },
            {
                "id": 5,
                "kind": "recap",
                "heading": "Quick recap",
                "narration": f"The takeaway is to connect the parts of {safe_topic} into one clear system.",
                "bullets": ["Main idea", "Mechanism", "Takeaway"],
                "visual_goal": "Review the three ideas as one connected map.",
                "beats": [
                    {"say": "Here is the main idea again in one visual map.", "visual": "Bring back the three recap labels."},
                    {"say": "The mechanism explains why the parts affect each other.", "visual": "Draw a final connecting arrow."},
                    {"say": "Use the takeaway to explain a new example on your own.", "visual": "Highlight the final takeaway."},
                ],
                "duration_sec": 14,
            },
        ],
    }


def _normalize_beats(incoming: dict[str, Any], *, narration: str, visual_goal: str, bullets: list[str]) -> list[dict[str, str]]:
    raw_beats = incoming.get("beats")
    beats: list[dict[str, str]] = []
    if isinstance(raw_beats, list):
        for item in raw_beats[:3]:
            if isinstance(item, dict):
                say = _short_text(item.get("say") or item.get("text") or item.get("narration"), 130, "")
                visual = _short_text(item.get("visual") or item.get("action"), 120, "")
            else:
                say = _short_text(item, 130, "")
                visual = ""
            if say:
                beats.append({"say": say, "visual": visual})

    if not beats:
        first = narration or "Introduce the key idea."
        second = visual_goal or (f"Show how {bullets[0]} changes the picture." if bullets else "Show the mechanism step by step.")
        third = f"The takeaway is {bullets[-1]}." if bullets else "Use the visual to remember the takeaway."
        beats = [
            {"say": _short_text(first, 130, "Introduce the key idea."), "visual": "Reveal the main visual."},
            {"say": _short_text(second, 130, "Show the mechanism step by step."), "visual": "Animate the important change."},
            {"say": _short_text(third, 130, "Use the visual to remember the takeaway."), "visual": "Highlight the takeaway."},
        ]

    while len(beats) < 3:
        idx = len(beats)
        fallback_say = [
            narration or "Introduce the key idea.",
            visual_goal or "Show the mechanism step by step.",
            "Pause on the takeaway so students can remember it.",
        ][idx]
        beats.append({"say": _short_text(fallback_say, 130, "Continue the explanation."), "visual": "Continue the visual step."})

    return beats[:3]


def _normalize_plan(plan: dict[str, Any], topic: str | None = None) -> dict[str, Any]:
    fallback = _default_plan(topic or "Learning topic")
    title = _short_text(plan.get("title"), 90, fallback["title"])
    scenes_in = plan.get("scenes")
    if not isinstance(scenes_in, list):
        scenes_in = []

    scenes: list[dict[str, Any]] = []

    for idx in range(5):
        fallback_scene = fallback["scenes"][idx]
        incoming = scenes_in[idx] if idx < len(scenes_in) and isinstance(scenes_in[idx], dict) else {}

        kind = _short_text(incoming.get("kind"), 30, _DEFAULT_KINDS[idx]).lower().replace(" ", "_")
        if kind not in _ALLOWED_KINDS:
            kind = _DEFAULT_KINDS[idx]

        # Keep stable open/close. Middle scenes may vary.
        if idx in (0, 1, 4):
            kind = _DEFAULT_KINDS[idx]
        if idx == 3 and kind in {"key_points", "title", "recap"}:
            kind = "creative"

        heading = _short_text(incoming.get("heading"), 70, fallback_scene["heading"])
        narration = _short_text(
            incoming.get("narration") or incoming.get("caption"),
            240,
            fallback_scene["narration"],
        )
        visual_goal = _short_text(
            incoming.get("visual_goal") or incoming.get("visual"),
            220,
            fallback_scene.get("visual_goal", ""),
        )

        bullets_in = incoming.get("bullets")
        bullets: list[str] = []
        if isinstance(bullets_in, list):
            for item in bullets_in[:4]:
                text = _short_text(item, 54, "")
                if text:
                    bullets.append(text)

        if not bullets:
            bullets = list(fallback_scene["bullets"])

        try:
            duration = int(incoming.get("duration_sec") or fallback_scene["duration_sec"])
        except Exception:
            duration = int(fallback_scene["duration_sec"])
        duration = max(11, min(20, duration))
        if idx in (2, 3):
            duration = max(15, duration)

        beats = _normalize_beats(incoming, narration=narration, visual_goal=visual_goal, bullets=bullets)

        scenes.append(
            {
                "id": idx + 1,
                "kind": kind,
                "heading": heading,
                "narration": narration,
                "bullets": bullets[:4],
                "visual_goal": visual_goal,
                "beats": beats,
                "duration_sec": duration,
            }
        )

    return {"title": title, "audience": str(plan.get("audience") or "general"), "scenes": scenes}


def parse_structured_video_plan(raw: str, topic: str) -> dict[str, Any]:
    """Parse the compact plan. On malformed/truncated model output, use a local plan."""
    try:
        plan_text = _extract_block(raw, "PLAN_JSON") or raw
        return _normalize_plan(_extract_json_object(plan_text), topic=topic)
    except Exception as exc:
        logger.warning("structured video plan parse failed; using local default plan: %s", exc)
        return _normalize_plan(_default_plan(topic), topic=topic)


def parse_plan_from_scene_bundle(bundle: str, topic: str = "Edited video") -> dict[str, Any]:
    """Extract the plan from a structured scene bundle returned as scene_code."""
    plan_text = _extract_block(bundle or "", "PLAN_JSON")
    if not plan_text:
        raise RuntimeError("Original video is not a structured scene bundle; PLAN_JSON missing.")
    return _normalize_plan(_extract_json_object(plan_text), topic=topic)


def is_structured_scene_bundle(text: str | None) -> bool:
    value = text or ""
    return "<<<PLAN_JSON>>>" in value and "<<<END_PLAN_JSON>>>" in value


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def build_template_scene_code(scene: dict[str, Any]) -> str:
    """Build one deterministic Manim scene with narration split into beats.

    The goal is synchronization: each scene has 2-3 short voiceover blocks, and
    each block owns a visual action. This prevents the narration from playing all
    at once while the visual simply waits.
    """
    scene_json = _safe_json(scene)

    template = r'''
from manim import *  # noqa: F403,F405
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))

        scene = __SCENE_JSON__
        kind = str(scene.get("kind") or "key_points")
        heading = str(scene.get("heading") or "Key idea")
        narration = str(scene.get("narration") or heading)
        visual_goal = str(scene.get("visual_goal") or "")
        try:
            target_duration = max(11.0, min(20.0, float(scene.get("duration_sec") or 15.0)))
        except Exception:
            target_duration = 15.0
        pace = max(1.0, min(1.45, target_duration / 14.0))

        bullets_data = [str(x) for x in (scene.get("bullets") or []) if str(x).strip()][:4]
        if not bullets_data:
            bullets_data = ["Main idea", "Mechanism", "Takeaway"]

        def safe_label(text, limit=42):
            value = str(text or "").strip()
            value = value.replace("\n", " ")
            if len(value) > limit:
                value = value[: limit - 1].rstrip() + "…"
            return value or "Idea"

        def small_text(text, size=23, color=WHITE):
            return Text(safe_label(text, 46), font_size=size, color=color)

        def rt(seconds):
            return float(seconds) * pace

        raw_beats = scene.get("beats") if isinstance(scene.get("beats"), list) else []
        beats = []
        for item in raw_beats[:3]:
            if isinstance(item, dict):
                say = str(item.get("say") or item.get("text") or "").strip()
                visual = str(item.get("visual") or "").strip()
            else:
                say = str(item or "").strip()
                visual = ""
            if say:
                beats.append({"say": say, "visual": visual})
        if not beats:
            beats = [
                {"say": narration, "visual": "Reveal the main idea."},
                {"say": visual_goal or "Show the mechanism step by step.", "visual": "Animate the change."},
                {"say": "Pause on the takeaway so students can explain it.", "visual": "Highlight the takeaway."},
            ]
        while len(beats) < 3:
            beats.append({"say": narration, "visual": "Continue the visual explanation."})
        beats = beats[:3]

        def finish_voiceover(tracker, animation_time):
            duration = float(getattr(tracker, "duration", 0) or 0)
            remaining = max(0.25, duration - float(animation_time or 0))
            if remaining > 0.25:
                self.wait(remaining)

        bg = Rectangle(width=config.frame_width, height=config.frame_height)
        bg.set_fill("#0f172a", opacity=1)
        bg.set_stroke(width=0)
        self.add(bg)

        title = Text(safe_label(heading, 58), font_size=38, color=WHITE).to_edge(UP, buff=0.42)
        label = Text(kind.replace("_", " ").upper(), font_size=18, color=BLUE_C)
        label.next_to(title, DOWN, buff=0.18)
        card = RoundedRectangle(width=10.9, height=4.85, corner_radius=0.25)
        card.set_stroke(BLUE_C, width=2)
        card.set_fill("#1e293b", opacity=0.92)
        card.shift(DOWN * 0.35)

        with self.voiceover(text=beats[0]["say"]) as tracker:
            self.play(FadeIn(card), FadeIn(label), Write(title), run_time=rt(1.0))
            finish_voiceover(tracker, rt(1.0))

        if kind == "title":
            icon = Circle(radius=0.82, color=YELLOW, fill_opacity=0.8).move_to(card.get_center() + UP * 0.15)
            ring = Circle(radius=1.12, color=BLUE_C).move_to(icon)
            guide = VGroup(*[small_text(x, 22) for x in bullets_data[:3]])
            guide.arrange(RIGHT, buff=0.45).next_to(icon, DOWN, buff=0.55)
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(GrowFromCenter(ring), FadeIn(icon), run_time=rt(1.0))
                self.play(LaggedStart(*[FadeIn(g, shift=UP * 0.15) for g in guide], lag_ratio=0.15), run_time=rt(1.2))
                finish_voiceover(tracker, rt(2.2))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(Rotate(ring, angle=PI / 4), Indicate(icon), run_time=rt(1.1))
                finish_voiceover(tracker, rt(1.1))

        elif kind in ("diagram", "flow_diagram"):
            labels = bullets_data[:3]
            while len(labels) < 3:
                labels.append(["Input", "Process", "Result"][len(labels)])
            positions = [LEFT * 3.45 + DOWN * 0.08, ORIGIN + DOWN * 0.08, RIGHT * 3.45 + DOWN * 0.08]
            shapes = VGroup(
                Circle(radius=0.55, color=BLUE_C, fill_opacity=0.75).move_to(positions[0]),
                RoundedRectangle(width=1.35, height=0.92, corner_radius=0.18, color=GREEN_C, fill_opacity=0.75).move_to(positions[1]),
                Triangle(color=ORANGE, fill_opacity=0.75).scale(0.72).move_to(positions[2]),
            )
            arrows = VGroup(
                Arrow(shapes[0].get_right(), shapes[1].get_left(), buff=0.22, color=WHITE),
                Arrow(shapes[1].get_right(), shapes[2].get_left(), buff=0.22, color=WHITE),
            )
            texts = VGroup(*[small_text(labels[i], 23).next_to(shapes[i], DOWN, buff=0.33) for i in range(3)])
            moving_dot = Dot(color=YELLOW).scale(1.15).move_to(shapes[0].get_center())
            goal = Text(safe_label(visual_goal or beats[2].get("visual"), 65), font_size=19, color=BLUE_B)
            goal.move_to(card.get_bottom() + UP * 0.43)
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(FadeIn(shapes[0]), Write(texts[0]), FadeIn(moving_dot), run_time=rt(0.9))
                self.play(GrowArrow(arrows[0]), moving_dot.animate.move_to(shapes[1].get_center()), FadeIn(shapes[1]), Write(texts[1]), run_time=rt(1.4))
                finish_voiceover(tracker, rt(2.3))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(GrowArrow(arrows[1]), moving_dot.animate.move_to(shapes[2].get_center()), FadeIn(shapes[2]), Write(texts[2]), run_time=rt(1.4))
                self.play(FadeIn(goal), Indicate(shapes[1]), run_time=rt(0.9))
                finish_voiceover(tracker, rt(2.3))

        elif kind == "cycle_diagram":
            labels = bullets_data[:4]
            while len(labels) < 4:
                labels.append(["Stage 1", "Stage 2", "Stage 3", "Stage 4"][len(labels)])
            center = card.get_center() + DOWN * 0.05
            circle_path = Circle(radius=1.45, color=BLUE_E).move_to(center)
            node_positions = [center + UP * 1.45, center + RIGHT * 2.35, center + DOWN * 1.45, center + LEFT * 2.35]
            nodes = VGroup(*[Circle(radius=0.33, color=[BLUE_C, GREEN_C, ORANGE, PURPLE_B][i], fill_opacity=0.82).move_to(node_positions[i]) for i in range(4)])
            node_labels = VGroup(*[small_text(labels[i], 20).next_to(nodes[i], [UP, RIGHT, DOWN, LEFT][i], buff=0.22) for i in range(4)])
            pointer = Dot(color=YELLOW).scale(1.25).move_to(node_positions[0])
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(Create(circle_path), run_time=rt(0.8))
                self.play(LaggedStart(*[FadeIn(n) for n in nodes], lag_ratio=0.15), run_time=rt(1.0))
                self.play(LaggedStart(*[Write(t) for t in node_labels], lag_ratio=0.12), run_time=rt(1.0))
                finish_voiceover(tracker, rt(2.8))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(MoveAlongPath(pointer, circle_path), run_time=rt(2.5))
                self.play(Indicate(nodes[0]), Indicate(nodes[2]), run_time=rt(0.8))
                finish_voiceover(tracker, rt(3.3))

        elif kind == "timeline":
            labels = bullets_data[:4]
            while len(labels) < 4:
                labels.append(["First", "Next", "Then", "Finally"][len(labels)])
            line = Line(LEFT * 4.1 + DOWN * 0.05, RIGHT * 4.1 + DOWN * 0.05, color=WHITE)
            dots = VGroup()
            text_mobs = VGroup()
            for i, label_txt in enumerate(labels[:4]):
                pos = line.point_from_proportion(i / 3)
                dot = Dot(pos, color=[BLUE_C, GREEN_C, ORANGE, PURPLE_B][i]).scale(1.2)
                text = small_text(label_txt, 20).next_to(dot, UP if i % 2 == 0 else DOWN, buff=0.35)
                dots.add(dot); text_mobs.add(text)
            mover = Dot(color=YELLOW).scale(1.0).move_to(line.get_start())
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(Create(line), run_time=rt(0.7))
                self.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.18), run_time=rt(0.9))
                self.play(LaggedStart(*[Write(t) for t in text_mobs], lag_ratio=0.12), run_time=rt(0.9))
                finish_voiceover(tracker, rt(2.5))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(mover.animate.move_to(line.get_end()), run_time=rt(2.0))
                self.play(Indicate(dots[-1]), run_time=rt(0.8))
                finish_voiceover(tracker, rt(2.8))

        elif kind == "comparison":
            labels = bullets_data[:3]
            while len(labels) < 3:
                labels.append(["Before", "During", "After"][len(labels)])
            cols = VGroup()
            for i, pos in enumerate([LEFT * 3.2, ORIGIN, RIGHT * 3.2]):
                box = RoundedRectangle(width=2.55, height=2.25, corner_radius=0.18).move_to(card.get_center() + pos + DOWN * 0.05)
                box.set_stroke([BLUE_C, GREEN_C, ORANGE][i], width=2).set_fill("#0f172a", opacity=0.72)
                head = small_text(labels[i], 22).move_to(box.get_top() + DOWN * 0.45)
                icon = Circle(radius=0.36, color=[BLUE_C, GREEN_C, ORANGE][i], fill_opacity=0.85).move_to(box.get_center() + DOWN * 0.15)
                cols.add(VGroup(box, head, icon))
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(LaggedStart(*[FadeIn(c[0], shift=UP * 0.12) for c in cols], lag_ratio=0.12), run_time=rt(1.0))
                self.play(LaggedStart(*[Write(c[1]) for c in cols], lag_ratio=0.12), run_time=rt(1.0))
                finish_voiceover(tracker, rt(2.0))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(LaggedStart(*[FadeIn(c[2], scale=0.5) for c in cols], lag_ratio=0.12), run_time=rt(0.9))
                self.play(cols[1].animate.shift(UP * 0.2), Indicate(cols[1]), run_time=rt(1.2))
                self.play(cols[1].animate.shift(DOWN * 0.2), run_time=rt(0.4))
                finish_voiceover(tracker, rt(2.5))

        elif kind == "chart":
            labels = bullets_data[:4]
            while len(labels) < 4:
                labels.append(["Low", "Medium", "High", "Peak"][len(labels)])
            base = Line(LEFT * 4 + DOWN * 1.45, RIGHT * 4 + DOWN * 1.45, color=WHITE)
            y_axis = Line(LEFT * 4 + DOWN * 1.45, LEFT * 4 + UP * 1.4, color=WHITE)
            heights = [0.8, 1.35, 2.0, 1.55]
            bars = VGroup()
            text_mobs = VGroup()
            for i in range(4):
                bar = Rectangle(width=0.8, height=heights[i]).set_fill([BLUE_C, GREEN_C, ORANGE, PURPLE_B][i], opacity=0.82).set_stroke(width=0)
                x_pos = -2.7 + i * 1.55
                bar.move_to(RIGHT * x_pos + DOWN * 1.45 + UP * heights[i] / 2)
                lab = small_text(labels[i], 18).next_to(bar, DOWN, buff=0.23)
                bars.add(bar); text_mobs.add(lab)
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(Create(base), Create(y_axis), run_time=rt(0.6))
                self.play(LaggedStart(*[GrowFromEdge(b, DOWN) for b in bars], lag_ratio=0.16), run_time=rt(1.4))
                finish_voiceover(tracker, rt(2.0))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(LaggedStart(*[Write(t) for t in text_mobs], lag_ratio=0.1), run_time=rt(0.9))
                self.play(bars[2].animate.scale(1.08), Indicate(bars[2]), run_time=rt(1.1))
                self.play(bars[2].animate.scale(1/1.08), run_time=rt(0.3))
                finish_voiceover(tracker, rt(2.3))

        elif kind == "system_map":
            labels = bullets_data[:4]
            while len(labels) < 4:
                labels.append(["Input", "Signal", "Center", "Output"][len(labels)])
            center = Circle(radius=0.66, color=YELLOW, fill_opacity=0.85).move_to(card.get_center() + DOWN * 0.05)
            center_text = small_text(labels[2], 20, color=BLACK).move_to(center)
            left = Circle(radius=0.42, color=BLUE_C, fill_opacity=0.82).shift(LEFT * 3.4 + DOWN * 0.05)
            top = Circle(radius=0.42, color=GREEN_C, fill_opacity=0.82).shift(UP * 1.4 + DOWN * 0.05)
            right = Circle(radius=0.42, color=ORANGE, fill_opacity=0.82).shift(RIGHT * 3.4 + DOWN * 0.05)
            nodes = VGroup(left, top, right)
            arrows = VGroup(Arrow(left.get_right(), center.get_left(), buff=0.18, color=WHITE), Arrow(top.get_bottom(), center.get_top(), buff=0.18, color=WHITE), Arrow(center.get_right(), right.get_left(), buff=0.18, color=WHITE))
            node_labels = VGroup(small_text(labels[0], 21).next_to(left, DOWN, buff=0.23), small_text(labels[1], 21).next_to(top, UP, buff=0.23), small_text(labels[3], 21).next_to(right, DOWN, buff=0.23))
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(FadeIn(center), Write(center_text), run_time=rt(0.8))
                self.play(LaggedStart(*[FadeIn(n, shift=0.2 * (n.get_center() - center.get_center())) for n in nodes], lag_ratio=0.15), run_time=rt(1.1))
                finish_voiceover(tracker, rt(1.9))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.12), run_time=rt(1.1))
                self.play(LaggedStart(*[Write(t) for t in node_labels], lag_ratio=0.1), run_time=rt(0.9))
                self.play(Indicate(center), run_time=rt(0.8))
                finish_voiceover(tracker, rt(2.8))

        elif kind in ("pseudo_3d", "creative"):
            labels = bullets_data[:3]
            while len(labels) < 3:
                labels.append(["Layer 1", "Layer 2", "Result"][len(labels)])
            layers = VGroup()
            colors = [BLUE_C, GREEN_C, PURPLE_B]
            offsets = [LEFT * 0.55 + DOWN * 0.45, ORIGIN, RIGHT * 0.55 + UP * 0.45]
            for i in range(3):
                panel = RoundedRectangle(width=4.35, height=2.05, corner_radius=0.18)
                panel.set_stroke(colors[i], width=2).set_fill("#172554", opacity=0.55 + i * 0.1)
                panel.move_to(card.get_center() + offsets[i])
                txt = small_text(labels[i], 23).move_to(panel.get_center())
                shadow = panel.copy().set_fill(BLACK, opacity=0.18).set_stroke(width=0).shift(DOWN * 0.18 + RIGHT * 0.18)
                layers.add(VGroup(shadow, panel, txt))
            connector1 = Arrow(layers[0][1].get_right(), layers[1][1].get_left(), buff=0.15, color=WHITE)
            connector2 = Arrow(layers[1][1].get_right(), layers[2][1].get_left(), buff=0.15, color=WHITE)
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(FadeIn(layers[0], shift=LEFT * 0.25), run_time=rt(0.8))
                self.play(FadeIn(layers[1], shift=RIGHT * 0.25), GrowArrow(connector1), run_time=rt(1.0))
                finish_voiceover(tracker, rt(1.8))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                self.play(FadeIn(layers[2], shift=RIGHT * 0.25), GrowArrow(connector2), run_time=rt(1.0))
                self.play(layers[1].animate.shift(UP * 0.18), layers[2].animate.shift(UP * 0.12), run_time=rt(0.8))
                self.play(Indicate(layers[2]), run_time=rt(0.9))
                finish_voiceover(tracker, rt(2.7))

        else:
            bullet_mobs = VGroup(*[Text("• " + safe_label(item, 50), font_size=28, color=WHITE) for item in bullets_data])
            bullet_mobs.arrange(DOWN, aligned_edge=LEFT, buff=0.36).move_to(card.get_center())
            connectors = VGroup()
            for i in range(max(0, len(bullet_mobs) - 1)):
                connectors.add(Arrow(bullet_mobs[i].get_bottom(), bullet_mobs[i + 1].get_top(), buff=0.12, color=BLUE_B, stroke_width=2))
            with self.voiceover(text=beats[1]["say"]) as tracker:
                self.play(LaggedStart(*[FadeIn(item, shift=UP * 0.2) for item in bullet_mobs], lag_ratio=0.22), run_time=rt(1.8))
                finish_voiceover(tracker, rt(1.8))
            with self.voiceover(text=beats[2]["say"]) as tracker:
                if len(connectors) > 0:
                    self.play(LaggedStart(*[GrowArrow(a) for a in connectors], lag_ratio=0.15), run_time=rt(1.0))
                self.play(Indicate(bullet_mobs[0]), run_time=rt(0.8))
                finish_voiceover(tracker, rt(1.8))

        snapshot = [m for m in list(self.mobjects) if m is not bg]
        if snapshot:
            self.play(*[FadeOut(m) for m in snapshot], run_time=rt(0.6))
        self.wait(0.1)
'''.strip() + "\n"
    return template.replace("__SCENE_JSON__", scene_json)


# Backward-compatible name used by the renderer's fallback branch.
def build_scene_fallback_code(scene: dict[str, Any]) -> str:
    return build_template_scene_code(scene)


def _video_url_to_path(video_url: str) -> pathlib.Path:
    relative = video_url.replace("/static/", "", 1)
    return STORAGE / relative


def _render_scene_clip(
    *,
    code: str,
    scene: dict[str, Any],
    final_job_id: str,
    scene_index: int,
) -> tuple[pathlib.Path, dict[str, Any]]:
    scene_job_id = f"{final_job_id}_s{scene_index:02d}"

    safe_code = sanitize_minimally(code)
    result = run_job_from_code(
        safe_code,
        job_id=scene_job_id,
        timeout_seconds=240,
        inject_watermark=False,
    )
    if result.get("ok") and result.get("video_url"):
        return _video_url_to_path(result["video_url"]), {
            "scene_index": scene_index,
            "used_fallback": False,
            "job_id": result.get("job_id"),
        }

    # This should be rare because the primary scene is already a deterministic template.
    logger.warning(
        "structured template scene %s failed; trying simplified fallback. error=%s",
        scene_index,
        result.get("error") or result.get("error_log") or "unknown",
    )

    simple_scene = dict(scene)
    simple_scene["kind"] = "key_points"
    fallback_code = build_scene_fallback_code(simple_scene)
    fallback_job_id = f"{final_job_id}_s{scene_index:02d}_fallback"
    fallback = run_job_from_code(
        fallback_code,
        job_id=fallback_job_id,
        timeout_seconds=240,
        inject_watermark=False,
    )

    if fallback.get("ok") and fallback.get("video_url"):
        return _video_url_to_path(fallback["video_url"]), {
            "scene_index": scene_index,
            "used_fallback": True,
            "primary_error": result.get("error") or result.get("error_log"),
            "primary_job_id": result.get("job_id"),
            "fallback_job_id": fallback.get("job_id"),
        }

    raise RuntimeError(
        "Fallback scene render failed for scene "
        f"{scene_index}: {fallback.get('error') or fallback.get('error_log') or 'unknown'}"
    )


def _find_ffmpeg() -> str:
    for key in ("UPCURVED_FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"):
        value = (os.environ.get(key) or "").strip()
        if value and pathlib.Path(value).exists():
            return value

    found = shutil.which("ffmpeg")
    if found:
        return found

    raise RuntimeError("ffmpeg not found. Set UPCURVED_FFMPEG_PATH or install ffmpeg.")


def _concat_clips(clips: list[pathlib.Path], final_mp4: pathlib.Path, logs_dir: pathlib.Path) -> None:
    if not clips:
        raise RuntimeError("No scene clips were produced.")

    ffmpeg_bin = _find_ffmpeg()
    concat_file = logs_dir / "concat.txt"
    concat_file.write_text(
        "\n".join([f"file '{clip.as_posix()}'" for clip in clips]) + "\n",
        encoding="utf-8",
    )

    copy_cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(final_mp4),
    ]
    copy_proc = subprocess.run(copy_cmd, capture_output=True, text=True)
    (logs_dir / "concat_copy_cmd.txt").write_text(" ".join(copy_cmd), encoding="utf-8")
    (logs_dir / "concat_copy_stdout.txt").write_text(copy_proc.stdout or "", encoding="utf-8")
    (logs_dir / "concat_copy_stderr.txt").write_text(copy_proc.stderr or "", encoding="utf-8")

    if copy_proc.returncode == 0 and final_mp4.exists():
        return

    reencode_cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(final_mp4),
    ]
    reencode_proc = subprocess.run(reencode_cmd, capture_output=True, text=True)
    (logs_dir / "concat_reencode_cmd.txt").write_text(" ".join(reencode_cmd), encoding="utf-8")
    (logs_dir / "concat_reencode_stdout.txt").write_text(reencode_proc.stdout or "", encoding="utf-8")
    (logs_dir / "concat_reencode_stderr.txt").write_text(reencode_proc.stderr or "", encoding="utf-8")

    if reencode_proc.returncode != 0 or not final_mp4.exists():
        detail = (reencode_proc.stderr or copy_proc.stderr or "")[-1000:]
        raise RuntimeError(f"ffmpeg concat failed: {detail}")


def _apply_final_watermark(final_mp4: pathlib.Path, logs_dir: pathlib.Path) -> None:
    """
    Apply one continuous watermark to the stitched final video.
    If ffmpeg/drawtext is unavailable, keep the unwatermarked final video.
    """
    try:
        ffmpeg_bin = _find_ffmpeg()
        tmp_mp4 = final_mp4.with_name("video_watermarked.mp4")
        text = "Generated using UpcurvEd"
        vf = (
            "drawtext="
            f"text='{text}':"
            "x=w-tw-24:y=24:"
            "fontsize=22:"
            "fontcolor=white@0.86:"
            "box=1:boxcolor=black@0.45:boxborderw=8"
        )
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(final_mp4),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(tmp_mp4),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        (logs_dir / "watermark_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
        (logs_dir / "watermark_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (logs_dir / "watermark_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
        if proc.returncode == 0 and tmp_mp4.exists() and tmp_mp4.stat().st_size > 0:
            tmp_mp4.replace(final_mp4)
        else:
            if tmp_mp4.exists():
                tmp_mp4.unlink(missing_ok=True)
            logger.warning("final video watermark skipped: %s", (proc.stderr or "")[-400:])
    except Exception as exc:
        logger.warning("final video watermark failed; keeping original final video: %s", exc)


def _format_vtt_ts(total_sec: float) -> str:
    millis = int((total_sec % 1) * 1000)
    seconds = int(total_sec) % 60
    minutes = (int(total_sec) // 60) % 60
    hours = int(total_sec) // 3600
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _write_vtt_from_plan(plan: dict[str, Any], out_path: pathlib.Path) -> None:
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    lines = ["WEBVTT", ""]
    cursor = 0.0

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        try:
            duration = float(scene.get("duration_sec") or 12)
        except Exception:
            duration = 12.0
        duration = max(1.0, duration)
        heading = str(scene.get("heading") or "").strip()
        beats = scene.get("beats") if isinstance(scene.get("beats"), list) else []
        beat_texts: list[str] = []
        for item in beats[:3]:
            if isinstance(item, dict):
                text = str(item.get("say") or item.get("text") or "").strip()
            else:
                text = str(item or "").strip()
            if text:
                beat_texts.append(text)
        if not beat_texts:
            narration = str(scene.get("narration") or heading).strip()
            beat_texts = [narration] if narration else [heading or "Scene"]

        beat_duration = duration / max(1, len(beat_texts))
        for beat_idx, text in enumerate(beat_texts):
            start = _format_vtt_ts(cursor + beat_idx * beat_duration)
            end = _format_vtt_ts(cursor + (beat_idx + 1) * beat_duration)
            caption = f"{heading}: {text}" if heading and beat_idx == 0 else text
            lines.append(f"{start} --> {end}")
            lines.append(caption[:180])
            lines.append("")
        cursor += duration

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bundle_for_scene_code(plan: dict[str, Any], scene_codes: list[str], raw_plan: str) -> str:
    pieces = [
        "# Structured UpcurvEd Manim bundle v2",
        "# The LLM returned only the compact plan below.",
        "# Python scene scripts were generated deterministically by the backend templates.",
        "",
        "<<<PLAN_JSON>>>",
        json.dumps(plan, ensure_ascii=True, indent=2),
        "<<<END_PLAN_JSON>>>",
        "",
    ]
    for idx, code in enumerate(scene_codes, start=1):
        pieces.extend(
            [
                f"<<<SCENE_{idx}_CODE>>>",
                code.strip(),
                f"<<<END_SCENE_{idx}_CODE>>>",
                "",
            ]
        )

    pieces.extend(["<<<RAW_MODEL_PLAN>>>", (raw_plan or "").strip(), "<<<END_RAW_MODEL_PLAN>>>", ""])
    return "\n".join(pieces)




def _extract_python_code(raw: str) -> str:
    """Extract a Python source file from a model response."""
    text = (raw or "").strip()
    fence = re.search(r"```(?:python|py)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return text.strip()


def _looks_like_complete_manim_scene(code: str) -> bool:
    cleaned = (code or "").strip()
    if not (
        "from manim import" in cleaned
        and "VoiceoverScene" in cleaned
        and "class GeneratedScene" in cleaned
        and "def construct" in cleaned
        and "self.voiceover" in cleaned
    ):
        return False
    # Creative scenes should be meaningfully animated and paced, not static posters.
    if cleaned.count("self.voiceover") < 2:
        return False
    if cleaned.count("self.play") < 4:
        return False
    motion_markers = (
        ".animate",
        "Transform(",
        "ReplacementTransform(",
        "MoveAlongPath(",
        "GrowArrow(",
        "Rotate(",
        "GrowFromCenter(",
        "Create(",
        "Indicate(",
    )
    return any(marker in cleaned for marker in motion_markers)


def _creative_scene_slots(plan: dict[str, Any]) -> list[int]:
    """Return zero-based scene indexes eligible for LLM-authored creative code."""
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    if not scenes:
        return []

    preferred_kinds = {
        "diagram",
        "flow_diagram",
        "cycle_diagram",
        "timeline",
        "comparison",
        "chart",
        "system_map",
        "pseudo_3d",
        "creative",
    }
    preferred: list[int] = []
    fallback: list[int] = []
    for idx, scene in enumerate(scenes):
        # Keep title and recap deterministic. Creative coding is most valuable in the middle.
        if idx == 0 or idx == len(scenes) - 1:
            continue
        if not isinstance(scene, dict):
            continue
        kind = str(scene.get("kind") or "").strip().lower()
        if kind in preferred_kinds:
            preferred.append(idx)
        else:
            fallback.append(idx)

    ordered = preferred + fallback
    try:
        count = int(os.environ.get("UPCURVED_CREATIVE_SCENE_COUNT", "1"))
    except Exception:
        count = 2
    count = max(0, min(2, count))
    if os.environ.get("UPCURVED_DISABLE_CREATIVE_SCENE_CODE", "").strip() in {"1", "true", "yes"}:
        count = 0
    return ordered[:count]


def _maybe_generate_creative_scene_codes(
    *,
    plan: dict[str, Any],
    scene_codes: list[str],
    provider_name: str | None,
    api_key: str | None,
    model: str | None,
    original_goal: str,
    logs_dir: pathlib.Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Replace one or two middle template scenes with LLM-authored Manim scenes.

    This is intentionally best-effort. If the model returns incomplete code, an API
    error occurs, or the creative render fails, the renderer falls back to the safe
    deterministic template for that scene.
    """
    if not provider_name or not api_key:
        return scene_codes, []

    updated = list(scene_codes)
    logs: list[dict[str, Any]] = []
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []

    for idx in _creative_scene_slots(plan):
        if idx < 0 or idx >= len(scenes):
            continue
        scene = scenes[idx]
        if not isinstance(scene, dict):
            continue

        scene_no = idx + 1
        try:
            raw_code = call_llm(
                provider=provider_name,
                api_key=api_key,
                model=model,
                system=STRUCTURED_VIDEO_CREATIVE_SCENE_SYSTEM,
                user=build_structured_video_creative_scene_prompt(
                    plan=plan,
                    scene=scene,
                    scene_index=scene_no,
                    original_goal=original_goal,
                ),
                temperature=0.34,
                max_tokens=3600,
            )
            (logs_dir / f"creative_scene_{scene_no}_raw.py").write_text(raw_code or "", encoding="utf-8")
            code = _extract_python_code(raw_code or "")
            if not _looks_like_complete_manim_scene(code):
                raise RuntimeError("Creative scene model output was not a complete GeneratedScene Manim file.")

            # Keep scene code isolated and renderable. sanitize_minimally will run again
            # before rendering; this earlier pass catches obvious formatting issues.
            updated[idx] = sanitize_minimally(code).strip() + "\n"
            scene["render_source"] = "creative_llm"
            logs.append({"scene_index": scene_no, "status": "creative_code_generated"})
        except Exception as exc:
            logger.warning("creative scene generation skipped for scene %s: %s", scene_no, exc)
            logs.append({"scene_index": scene_no, "status": "template_fallback", "reason": str(exc)[:400]})

    return updated, logs

def _render_structured_plan(
    *,
    plan: dict[str, Any],
    raw_plan: str,
    final_job_id: str,
    provider_name: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    original_goal: str = "",
) -> dict[str, Any]:
    final_job_dir = STORAGE / "jobs" / final_job_id
    logs_dir = final_job_dir / "logs"
    final_job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    (logs_dir / "structured_plan.json").write_text(
        json.dumps(plan, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    scene_codes = [build_template_scene_code(scene) for scene in plan["scenes"]]
    scene_codes, creative_logs = _maybe_generate_creative_scene_codes(
        plan=plan,
        scene_codes=scene_codes,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        original_goal=original_goal or str(plan.get("title") or ""),
        logs_dir=logs_dir,
    )
    (logs_dir / "creative_scene_generation.json").write_text(
        json.dumps(creative_logs, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    clips: list[pathlib.Path] = []
    scene_results: list[dict[str, Any]] = []

    for idx, code in enumerate(scene_codes, start=1):
        scene = plan["scenes"][idx - 1]
        clip_path, scene_result = _render_scene_clip(
            code=code,
            scene=scene,
            final_job_id=final_job_id,
            scene_index=idx,
        )
        clips.append(clip_path)
        scene_results.append(scene_result)

    (logs_dir / "structured_scene_results.json").write_text(
        json.dumps(scene_results, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    final_mp4 = final_job_dir / "video.mp4"
    _concat_clips(clips, final_mp4, logs_dir)
    _apply_final_watermark(final_mp4, logs_dir)

    final_vtt = final_job_dir / "video.vtt"
    _write_vtt_from_plan(plan, final_vtt)

    scene_code = _bundle_for_scene_code(plan, scene_codes, raw_plan or "")
    (final_job_dir / "scene_bundle.txt").write_text(scene_code, encoding="utf-8")

    used_fallback = any(bool(item.get("used_fallback")) for item in scene_results)

    return {
        "ok": True,
        "status": "ok",
        "job_id": final_job_id,
        "video_url": to_static_url(final_mp4),
        "vtt_url": to_static_url(final_vtt),
        "scene_code": scene_code,
        "scene_plan": plan,
        "scene_results": scene_results,
        "used_fallback": used_fallback,
    }


def generate_structured_manim_video(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    provider_name, api_key = _pick_provider_and_key(provider, provider_keys)
    final_job_id = job_id or str(uuid.uuid4())[:8]
    final_job_dir = STORAGE / "jobs" / final_job_id
    logs_dir = final_job_dir / "logs"
    final_job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "structured_manim_generation_start job_id=%s provider=%s model=%s mode=plan_only_templates",
        final_job_id,
        provider_name,
        model,
    )

    raw_plan = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_SYSTEM,
        user=build_structured_video_user_prompt(prompt),
        temperature=0.28,
        max_tokens=2200,
    )

    (logs_dir / "structured_raw_plan.txt").write_text(raw_plan or "", encoding="utf-8")
    plan = parse_structured_video_plan(raw_plan or "", topic=prompt)
    return _render_structured_plan(
        plan=plan,
        raw_plan=raw_plan or "",
        final_job_id=final_job_id,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        original_goal=prompt,
    )


def edit_structured_manim_video(
    *,
    original_bundle: str,
    edit_instructions: str,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Edit a structured video by editing its compact scene plan, not raw Manim.
    The full video is then re-rendered from deterministic templates.
    """
    provider_name, api_key = _pick_provider_and_key(provider, provider_keys)
    final_job_id = job_id or str(uuid.uuid4())[:8]
    final_job_dir = STORAGE / "jobs" / final_job_id
    logs_dir = final_job_dir / "logs"
    final_job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    original_plan = parse_plan_from_scene_bundle(original_bundle, topic="Edited video")
    (logs_dir / "structured_original_plan.json").write_text(
        json.dumps(original_plan, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    logger.info(
        "structured_manim_edit_start job_id=%s provider=%s model=%s",
        final_job_id,
        provider_name,
        model,
    )

    raw_edited_plan = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_EDIT_SYSTEM,
        user=build_structured_video_edit_user_prompt(original_plan, edit_instructions),
        temperature=0.18,
        max_tokens=2200,
    )

    (logs_dir / "structured_raw_edited_plan.txt").write_text(
        raw_edited_plan or "",
        encoding="utf-8",
    )
    edited_plan = parse_structured_video_plan(
        raw_edited_plan or "",
        topic=str(original_plan.get("title") or "Edited video"),
    )
    return _render_structured_plan(
        plan=edited_plan,
        raw_plan=raw_edited_plan or "",
        final_job_id=final_job_id,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        original_goal=str(original_plan.get("title") or "Edited video"),
    )
