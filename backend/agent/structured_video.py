# backend/agent/structured_video.py
"""
Structured Manim video generation, v2.

One LLM call returns only a compact JSON scene plan. The backend then renders
five deterministic Manim template scenes from that plan and concatenates them
into one final downloadable video.

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
    STRUCTURED_VIDEO_SYSTEM,
    build_structured_video_user_prompt,
)
from backend.runner.job_runner import STORAGE, run_job_from_code, to_static_url

logger = logging.getLogger(f"app.{__name__}")


_ALLOWED_KINDS = ("title", "key_points", "diagram", "creative", "recap")
_DEFAULT_KINDS = ["title", "key_points", "diagram", "creative", "recap"]


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
                "narration": f"This lesson introduces {safe_topic} with simple visuals.",
                "bullets": ["Big idea", "Simple visual"],
                "duration_sec": 6,
            },
            {
                "id": 2,
                "kind": "key_points",
                "heading": "Key points",
                "narration": f"These are the most important ideas about {safe_topic}.",
                "bullets": ["What it means", "How it works", "Why it matters"],
                "duration_sec": 8,
            },
            {
                "id": 3,
                "kind": "diagram",
                "heading": "How it works",
                "narration": f"A simple diagram can show how {safe_topic} works step by step.",
                "bullets": ["Start", "Process", "Result"],
                "visual_goal": "Show a simple flow from start to process to result.",
                "duration_sec": 9,
            },
            {
                "id": 4,
                "kind": "creative",
                "heading": "Visual example",
                "narration": f"A memorable example makes {safe_topic} easier to remember.",
                "bullets": ["Example", "Connection", "Memory hook"],
                "visual_goal": "Show a memorable metaphor with simple shapes.",
                "duration_sec": 9,
            },
            {
                "id": 5,
                "kind": "recap",
                "heading": "Quick recap",
                "narration": f"The main takeaway is to understand the core pattern behind {safe_topic}.",
                "bullets": ["Main idea", "Simple example", "Takeaway"],
                "duration_sec": 7,
            },
        ],
    }


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

        # Keep the scene order stable even when the model drifts.
        if idx in (0, 1, 4):
            kind = _DEFAULT_KINDS[idx]

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
        duration = max(4, min(12, duration))

        scenes.append(
            {
                "id": idx + 1,
                "kind": kind,
                "heading": heading,
                "narration": narration,
                "bullets": bullets[:4],
                "visual_goal": visual_goal,
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


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def build_template_scene_code(scene: dict[str, Any]) -> str:
    """Build a deterministic Manim scene from a normalized scene-plan item."""
    scene_json = _safe_json(scene)

    return f'''
from manim import *  # noqa: F403,F405
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))

        scene = {scene_json}
        kind = str(scene.get("kind") or "key_points")
        heading = str(scene.get("heading") or "Key idea")
        narration = str(scene.get("narration") or heading)
        visual_goal = str(scene.get("visual_goal") or "")
        bullets_data = [str(x) for x in (scene.get("bullets") or []) if str(x).strip()][:4]
        if not bullets_data:
            bullets_data = ["Main idea", "Example", "Takeaway"]

        bg = Rectangle(width=config.frame_width, height=config.frame_height)
        bg.set_fill("#0f172a", opacity=1)
        bg.set_stroke(width=0)
        self.add(bg)

        with self.voiceover(text=narration) as tracker:
            title = Text(heading, font_size=38, color=WHITE)
            title.to_edge(UP, buff=0.42)

            label = Text(kind.replace("_", " ").upper(), font_size=18, color=BLUE_C)
            label.next_to(title, DOWN, buff=0.18)

            card = RoundedRectangle(
                width=10.8,
                height=4.75,
                corner_radius=0.25,
                stroke_color=BLUE_C,
                stroke_width=2,
                fill_color="#1e293b",
                fill_opacity=0.92,
            )
            card.shift(DOWN * 0.35)

            self.play(FadeIn(card), FadeIn(label), Write(title), run_time=1.0)

            if kind == "title":
                icon = Circle(radius=0.82, color=YELLOW, fill_opacity=0.8)
                ring = Circle(radius=1.12, color=BLUE_C)
                icon.move_to(card.get_center() + UP * 0.15)
                ring.move_to(icon)
                subtitle = Text("A quick visual lesson", font_size=28, color=WHITE)
                subtitle.next_to(icon, DOWN, buff=0.55)
                self.play(GrowFromCenter(ring), FadeIn(icon), run_time=0.9)
                self.play(Write(subtitle), run_time=0.8)
                self.play(Rotate(ring, angle=PI / 6), Indicate(icon), run_time=1.0)

            elif kind == "diagram":
                labels = bullets_data[:3]
                while len(labels) < 3:
                    labels.append(["Start", "Process", "Result"][len(labels)])
                left = Circle(radius=0.52, color=BLUE_C, fill_opacity=0.75).shift(LEFT * 3 + DOWN * 0.15)
                mid = Square(side_length=1.02, color=GREEN_C, fill_opacity=0.75).shift(DOWN * 0.15)
                right = Triangle(color=ORANGE, fill_opacity=0.75).scale(0.72).shift(RIGHT * 3 + DOWN * 0.15)
                arrow1 = Arrow(left.get_right(), mid.get_left(), buff=0.25, color=WHITE)
                arrow2 = Arrow(mid.get_right(), right.get_left(), buff=0.25, color=WHITE)
                l1 = Text(labels[0], font_size=24, color=WHITE).next_to(left, DOWN, buff=0.34)
                l2 = Text(labels[1], font_size=24, color=WHITE).next_to(mid, DOWN, buff=0.34)
                l3 = Text(labels[2], font_size=24, color=WHITE).next_to(right, DOWN, buff=0.34)
                goal = Text(visual_goal[:60] or "Step-by-step visual", font_size=20, color=BLUE_B)
                goal.move_to(card.get_bottom() + UP * 0.45)
                self.play(FadeIn(left), Write(l1), run_time=0.7)
                self.play(GrowArrow(arrow1), FadeIn(mid), Write(l2), run_time=0.9)
                self.play(GrowArrow(arrow2), FadeIn(right), Write(l3), run_time=0.9)
                self.play(FadeIn(goal), Indicate(mid), run_time=1.0)

            elif kind == "creative":
                center = Dot(color=YELLOW).scale(1.6).move_to(card.get_center())
                orbiters = VGroup()
                labels = VGroup()
                colors = [BLUE_C, GREEN_C, ORANGE, PURPLE_B]
                for i, item in enumerate(bullets_data[:4]):
                    angle = i * TAU / max(1, len(bullets_data[:4]))
                    pos = card.get_center() + np.array([2.5 * np.cos(angle), 1.25 * np.sin(angle), 0])
                    orb = Circle(radius=0.32, color=colors[i % len(colors)], fill_opacity=0.75).move_to(pos)
                    txt = Text(item, font_size=21, color=WHITE).next_to(orb, DOWN, buff=0.22)
                    orbiters.add(orb)
                    labels.add(txt)
                lines = VGroup(*[Line(center.get_center(), orb.get_center(), color=BLUE_E) for orb in orbiters])
                self.play(FadeIn(center), run_time=0.5)
                self.play(LaggedStart(*[Create(line) for line in lines], lag_ratio=0.1), run_time=0.8)
                self.play(LaggedStart(*[FadeIn(o) for o in orbiters], lag_ratio=0.15), run_time=0.8)
                self.play(LaggedStart(*[Write(t) for t in labels], lag_ratio=0.12), run_time=1.0)
                self.play(Rotate(orbiters, angle=PI / 8, about_point=center.get_center()), Indicate(center), run_time=1.0)

            else:
                bullet_mobs = VGroup(
                    *[
                        Text("• " + item, font_size=28, color=WHITE)
                        for item in bullets_data
                    ]
                )
                bullet_mobs.arrange(DOWN, aligned_edge=LEFT, buff=0.36)
                bullet_mobs.move_to(card.get_center())
                accent = Circle(radius=0.16, color=YELLOW, fill_opacity=0.9)
                accent.next_to(title, LEFT, buff=0.25)
                self.play(FadeIn(accent), run_time=0.3)
                self.play(
                    LaggedStart(
                        *[FadeIn(item, shift=UP * 0.2) for item in bullet_mobs],
                        lag_ratio=0.18,
                    ),
                    run_time=1.8,
                )
                self.play(Indicate(bullet_mobs[0]), run_time=0.7)

            remaining = max(0.1, tracker.duration - 4.2)
            if remaining > 0.1:
                self.wait(remaining)

        snapshot = list(self.mobjects)
        if snapshot:
            self.play(*[FadeOut(m) for m in snapshot], run_time=0.6)
        self.wait(0.1)
'''.strip() + "\n"


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
    result = run_job_from_code(safe_code, job_id=scene_job_id, timeout_seconds=240)
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
    fallback = run_job_from_code(fallback_code, job_id=fallback_job_id, timeout_seconds=240)

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
            duration = float(scene.get("duration_sec") or 8)
        except Exception:
            duration = 8.0
        duration = max(1.0, duration)

        start = _format_vtt_ts(cursor)
        end = _format_vtt_ts(cursor + duration)
        heading = str(scene.get("heading") or "").strip()
        narration = str(scene.get("narration") or heading).strip()
        caption = f"{heading}: {narration}" if heading else narration

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
        temperature=0.35,
        max_tokens=1800,
    )

    (logs_dir / "structured_raw_plan.txt").write_text(raw_plan or "", encoding="utf-8")
    plan = parse_structured_video_plan(raw_plan or "", topic=prompt)
    (logs_dir / "structured_plan.json").write_text(
        json.dumps(plan, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    scene_codes = [build_template_scene_code(scene) for scene in plan["scenes"]]

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
