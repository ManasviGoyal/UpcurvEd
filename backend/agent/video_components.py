"""
Reusable Manim scene components for structured UpcurvEd videos.

The model chooses a scene type and fills small fields. This module owns the
stable Manim shell for standard scenes and the wrapper for bounded custom
construct-body code.
"""

from __future__ import annotations

import json
from typing import Any


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def build_component_scene_code(scene: dict[str, Any]) -> str:
    """Return one runnable Manim/Voiceover scene for a structured scene object."""
    scene_json = _safe_json(scene)
    template = r'''
import manim as mn
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))

        scene = __SCENE_JSON__
        scene_type = str(scene.get("type") or scene.get("kind") or "concept_scene")
        title_text = str(scene.get("title") or scene.get("heading") or "Key idea")
        subtitle_text = str(scene.get("subtitle") or "")
        narration = str(scene.get("narration") or title_text)
        visual_goal = str(scene.get("visual") or scene.get("visual_goal") or "")
        formula_text = str(scene.get("formula") or "").replace("\n", " ").strip()
        labels = [str(x) for x in (scene.get("labels") or scene.get("bullets") or []) if str(x).strip()][:5]
        if not labels:
            labels = ["Idea", "Change", "Takeaway"]
        while len(labels) < 3:
            labels.append(["Idea", "Change", "Takeaway"][len(labels)])

        def safe_label(text, limit=46):
            value = str(text or "").replace("\n", " ").strip()
            if len(value) > limit:
                value = value[: limit - 1].rstrip() + "…"
            return value or "Idea"

        def text_mob(text, size=28, color=mn.WHITE):
            return mn.Text(safe_label(text), font_size=size, color=color)

        def formula_mob(text, size=30, color=mn.YELLOW):
            value = str(text or "").replace("\n", " ").strip()
            mob = mn.Text(value or "Formula", font_size=size, color=color)
            if mob.width > 10.5:
                mob.scale_to_fit_width(10.5)
            return mob

        def hold_voiceover(tracker, used_time):
            duration = float(getattr(tracker, "duration", 0) or 0)
            remaining = max(0.2, duration - float(used_time or 0))
            if remaining > 0.2:
                self.wait(remaining)

        def add_background():
            bg = mn.Rectangle(width=mn.config.frame_width, height=mn.config.frame_height)
            bg.set_fill("#0f172a", opacity=1)
            bg.set_stroke(width=0)
            self.add(bg)
            return bg

        def clean_out(bg):
            leftovers = [m for m in list(self.mobjects) if m is not bg]
            if leftovers:
                self.play(*[mn.FadeOut(m) for m in leftovers], run_time=0.55)
            self.wait(0.1)

        bg = add_background()
        header = text_mob(title_text, 36, mn.WHITE).to_edge(mn.UP, buff=0.42)
        type_label = mn.Text(scene_type.replace("_", " ").upper(), font_size=16, color=mn.BLUE_C)
        type_label.next_to(header, mn.DOWN, buff=0.16)

        if scene_type == "title_scene":
            line = mn.Line(start=[-3.9, 0, 0], end=[3.9, 0, 0], color=mn.BLUE_C)
            title = mn.Text(safe_label(title_text, 52), font_size=48, color=mn.WHITE).next_to(line, mn.UP, buff=0.4)
            subtitle = mn.Text(safe_label(subtitle_text or visual_goal or labels[0], 62), font_size=27, color=mn.BLUE_B).next_to(line, mn.DOWN, buff=0.4)
            formula = formula_mob(formula_text, 28) if formula_text else None
            if formula is not None:
                formula.next_to(subtitle, mn.DOWN, buff=0.34)
            with self.voiceover(text=narration) as tracker:
                self.play(mn.Create(line), mn.Write(title), run_time=1.3)
                self.play(mn.FadeIn(subtitle, shift=mn.UP * 0.16), run_time=0.8)
                if formula is not None:
                    self.play(mn.Write(formula), run_time=0.8)
                    self.play(mn.Indicate(formula), run_time=0.65)
                    hold_voiceover(tracker, 3.55)
                else:
                    hold_voiceover(tracker, 2.1)
            fades = [mn.FadeOut(title, shift=mn.UP), mn.Uncreate(line), mn.FadeOut(subtitle, shift=mn.DOWN)]
            if formula is not None:
                fades.append(mn.FadeOut(formula, shift=mn.DOWN))
            self.play(*fades, run_time=0.75)
            self.wait(0.1)
            return

        formula = formula_mob(formula_text) if formula_text else None
        if formula is not None:
            formula.next_to(type_label, mn.DOWN, buff=0.24)
            self.play(
                mn.FadeIn(header, shift=mn.DOWN * 0.1),
                mn.FadeIn(type_label),
                mn.Write(formula),
                run_time=0.65,
            )
        else:
            self.play(mn.FadeIn(header, shift=mn.DOWN * 0.1), mn.FadeIn(type_label), run_time=0.45)

        content_shift = mn.DOWN * 0.25 if formula is not None else mn.ORIGIN

        if scene_type == "question_scene":
            q = mn.Text(safe_label(subtitle_text or visual_goal or labels[0], 70), font_size=34, color=mn.YELLOW).move_to(mn.ORIGIN + mn.UP * 0.35 + content_shift)
            mark = mn.Text("?", font_size=96, color=mn.BLUE_C).next_to(q, mn.LEFT, buff=0.38)
            clues = mn.VGroup(*[text_mob(x, 23, mn.WHITE) for x in labels[:3]]).arrange(mn.DOWN, aligned_edge=mn.LEFT, buff=0.22).next_to(q, mn.DOWN, buff=0.55)
            with self.voiceover(text=narration) as tracker:
                self.play(mn.FadeIn(mark, scale=0.7), mn.Write(q), run_time=1.2)
                self.play(mn.LaggedStart(*[mn.FadeIn(c, shift=mn.UP * 0.12) for c in clues], lag_ratio=0.14), run_time=1.15)
                self.play(mn.Indicate(formula if formula is not None else q), run_time=0.7)
                hold_voiceover(tracker, 3.05)

        elif scene_type == "process_scene":
            names = labels[:3]
            positions = [
                mn.LEFT * 3.35 + mn.DOWN * 0.1 + content_shift,
                mn.ORIGIN + mn.DOWN * 0.1 + content_shift,
                mn.RIGHT * 3.35 + mn.DOWN * 0.1 + content_shift,
            ]
            boxes = mn.VGroup()
            for i, name in enumerate(names):
                box = mn.RoundedRectangle(width=2.05, height=1.05, corner_radius=0.16, color=[mn.BLUE_C, mn.GREEN_C, mn.ORANGE][i])
                box.set_fill("#1e293b", opacity=0.88).move_to(positions[i])
                txt = text_mob(name, 23).move_to(box)
                boxes.add(mn.VGroup(box, txt))
            arrows = mn.VGroup(
                mn.Arrow(boxes[0].get_right(), boxes[1].get_left(), buff=0.18, color=mn.WHITE),
                mn.Arrow(boxes[1].get_right(), boxes[2].get_left(), buff=0.18, color=mn.WHITE),
            )
            dot = mn.Dot(color=mn.YELLOW).scale(1.15).move_to(boxes[0].get_center())
            with self.voiceover(text=narration) as tracker:
                self.play(mn.FadeIn(boxes[0]), mn.FadeIn(dot), run_time=0.8)
                self.play(mn.GrowArrow(arrows[0]), dot.animate.move_to(boxes[1].get_center()), mn.FadeIn(boxes[1]), run_time=1.25)
                self.play(mn.GrowArrow(arrows[1]), dot.animate.move_to(boxes[2].get_center()), mn.FadeIn(boxes[2]), run_time=1.25)
                self.play(mn.Indicate(formula if formula is not None else boxes[2]), run_time=0.75)
                hold_voiceover(tracker, 4.05)

        elif scene_type == "comparison_scene":
            left_title = labels[0]
            right_title = labels[1]
            takeaway = labels[2]
            left = mn.RoundedRectangle(width=3.4, height=2.4, corner_radius=0.22, color=mn.BLUE_C).set_fill("#172554", opacity=0.88).shift(mn.LEFT * 2.25 + mn.DOWN * 0.05 + content_shift)
            right = mn.RoundedRectangle(width=3.4, height=2.4, corner_radius=0.22, color=mn.ORANGE).set_fill("#431407", opacity=0.82).shift(mn.RIGHT * 2.25 + mn.DOWN * 0.05 + content_shift)
            lt = text_mob(left_title, 27).move_to(left.get_center() + mn.UP * 0.28)
            rt = text_mob(right_title, 27).move_to(right.get_center() + mn.UP * 0.28)
            lb = mn.Rectangle(width=1.9, height=0.42, color=mn.BLUE_B).set_fill(mn.BLUE_B, opacity=0.7).next_to(lt, mn.DOWN, buff=0.35)
            rb = mn.Rectangle(width=2.7, height=0.42, color=mn.YELLOW).set_fill(mn.YELLOW, opacity=0.75).next_to(rt, mn.DOWN, buff=0.35)
            note = text_mob(takeaway, 25, mn.GREEN_C).to_edge(mn.DOWN, buff=0.7)
            with self.voiceover(text=narration) as tracker:
                self.play(mn.FadeIn(left, shift=mn.LEFT * 0.2), mn.Write(lt), run_time=0.9)
                self.play(mn.FadeIn(right, shift=mn.RIGHT * 0.2), mn.Write(rt), run_time=0.9)
                self.play(mn.GrowFromEdge(lb, mn.LEFT), mn.GrowFromEdge(rb, mn.LEFT), run_time=1.0)
                self.play(
                    mn.FadeIn(note, shift=mn.UP * 0.15),
                    mn.Indicate(formula if formula is not None else rb),
                    run_time=0.9,
                )
                hold_voiceover(tracker, 3.7)

        else:
            center = mn.Circle(radius=0.78, color=mn.BLUE_C, fill_opacity=0.82).move_to(mn.ORIGIN + mn.DOWN * 0.05 + content_shift)
            center_label = text_mob(labels[0], 24).move_to(center)
            orbit = mn.Circle(radius=1.42, color=mn.BLUE_B).move_to(center)
            side_labels = mn.VGroup(text_mob(labels[1], 23), text_mob(labels[2], 23))
            side_labels[0].next_to(orbit, mn.LEFT, buff=0.45)
            side_labels[1].next_to(orbit, mn.RIGHT, buff=0.45)
            arrow1 = mn.Arrow(side_labels[0].get_right(), orbit.get_left(), buff=0.18, color=mn.WHITE)
            arrow2 = mn.Arrow(orbit.get_right(), side_labels[1].get_left(), buff=0.18, color=mn.WHITE)
            with self.voiceover(text=narration) as tracker:
                self.play(mn.GrowFromCenter(center), mn.Write(center_label), run_time=0.9)
                self.play(mn.Create(orbit), run_time=0.75)
                self.play(mn.FadeIn(side_labels[0], shift=mn.RIGHT * 0.1), mn.GrowArrow(arrow1), run_time=0.85)
                self.play(mn.FadeIn(side_labels[1], shift=mn.LEFT * 0.1), mn.GrowArrow(arrow2), run_time=0.85)
                self.play(
                    mn.Rotate(orbit, angle=mn.PI / 4),
                    mn.Indicate(formula if formula is not None else center),
                    run_time=0.9,
                )
                hold_voiceover(tracker, 4.25)

        clean_out(bg)
'''.strip() + "\n"
    return template.replace("__SCENE_JSON__", scene_json)


def build_concept_fallback_scene_code(scene: dict[str, Any]) -> str:
    """Turn any failed scene into a simple deterministic visual concept scene."""
    safe_scene = dict(scene)
    safe_scene["type"] = "concept_scene"
    safe_scene["kind"] = "concept_scene"
    safe_scene["subtitle"] = str(
        safe_scene.get("subtitle") or safe_scene.get("visual") or "The key relationship"
    )
    labels = safe_scene.get("labels") or safe_scene.get("bullets") or []
    if not isinstance(labels, list) or len(labels) < 3:
        title = str(safe_scene.get("title") or safe_scene.get("heading") or "Key idea")
        formula = str(safe_scene.get("formula") or "").strip()
        safe_scene["labels"] = [
            title,
            formula or str(safe_scene.get("subtitle") or "Key relationship"),
            str(safe_scene.get("visual") or "Why the relationship matters"),
        ]
        safe_scene["bullets"] = safe_scene["labels"]
    return build_component_scene_code(safe_scene)


def build_custom_scene_code(scene: dict[str, Any], body_code: str) -> str:
    """Wrap model-authored construct-body code in a stable VoiceoverScene shell."""
    scene_json = _safe_json(scene)
    body = (body_code or "").strip()
    if not body:
        body = "self.wait(0.1)"
    indented = "\n".join("        " + line if line.strip() else "" for line in body.splitlines())
    template = f'''
import manim as mn
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))
        scene = {scene_json}
        title = str(scene.get("title") or scene.get("heading") or "")
        narration = str(scene.get("narration") or title or "")
        labels = [str(x) for x in (scene.get("labels") or scene.get("bullets") or []) if str(x).strip()][:5]
        visual = str(scene.get("visual") or scene.get("visual_goal") or scene.get("code_goal") or "")
        formula = str(scene.get("formula") or "").replace("\\n", " ").strip()

        def safe_label(text, limit=44):
            value = str(text or "").replace("\\n", " ").strip()
            if len(value) > limit:
                value = value[: limit - 1].rstrip() + "…"
            return value or "Idea"

        def label(text, size=26, color=mn.WHITE):
            return mn.Text(safe_label(text), font_size=size, color=color)

        def formula_label(text, size=30, color=mn.YELLOW):
            value = str(text or "").replace("\\n", " ").strip()
            mob = mn.Text(value or "Formula", font_size=size, color=color)
            if mob.width > 10.5:
                mob.scale_to_fit_width(10.5)
            return mob

        def wait_for_voiceover(tracker, used_time):
            duration = float(getattr(tracker, "duration", 0) or 0)
            remaining = max(0.2, duration - float(used_time or 0))
            if remaining > 0.2:
                self.wait(remaining)

        bg = mn.Rectangle(width=mn.config.frame_width, height=mn.config.frame_height)
        bg.set_fill("#0f172a", opacity=1)
        bg.set_stroke(width=0)
        self.add(bg)

{indented}

        leftovers = [m for m in list(self.mobjects) if m is not bg]
        if leftovers:
            self.play(*[mn.FadeOut(m) for m in leftovers], run_time=0.55)
        self.wait(0.1)
'''.lstrip()
    return template
