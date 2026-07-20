# backend/agent/structured_video.py
"""
Structured Manim video generation.

One LLM call returns:
- a compact PLAN_JSON block
- five independent Manim scene scripts

Each scene is rendered separately. If an AI scene fails, only that scene is
replaced with a safe template fallback. Successful clips are concatenated into
one final downloadable video.
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
        return json.loads(clean)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            raise RuntimeError("Structured video plan is missing valid JSON.")
        return json.loads(match.group(0))


def parse_structured_video_bundle(raw: str) -> tuple[dict[str, Any], list[str]]:
    plan_text = _extract_block(raw, "PLAN_JSON")
    if not plan_text:
        raise RuntimeError("Missing PLAN_JSON block in structured video bundle.")

    plan = _normalize_plan(_extract_json_object(plan_text))

    scene_codes: list[str] = []
    for idx in range(1, 6):
        code = _extract_block(raw, f"SCENE_{idx}_CODE")
        if not code:
            raise RuntimeError(f"Missing SCENE_{idx}_CODE block in structured video bundle.")
        scene_codes.append(code)

    return plan, scene_codes


def _normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    title = str(plan.get("title") or "Generated Lesson").strip()[:90]
    scenes_in = plan.get("scenes")
    if not isinstance(scenes_in, list):
        scenes_in = []

    default_kinds = ["title", "key_points", "diagram", "creative", "recap"]
    scenes: list[dict[str, Any]] = []

    for idx in range(5):
        incoming = scenes_in[idx] if idx < len(scenes_in) and isinstance(scenes_in[idx], dict) else {}
        kind = str(incoming.get("kind") or default_kinds[idx]).strip().lower()
        if kind not in ("title", "key_points", "diagram", "creative", "recap"):
            kind = default_kinds[idx]

        heading = str(incoming.get("heading") or f"Scene {idx + 1}").strip()[:80]
        narration = str(incoming.get("narration") or incoming.get("caption") or heading).strip()[:260]
        visual_goal = str(incoming.get("visual_goal") or incoming.get("visual") or "").strip()[:320]

        bullets_in = incoming.get("bullets")
        bullets: list[str] = []
        if isinstance(bullets_in, list):
            for item in bullets_in[:4]:
                text = str(item or "").strip()
                if text:
                    bullets.append(text[:60])

        if not bullets:
            if kind in ("title", "recap"):
                bullets = ["Key idea", "Simple example", "Takeaway"]
            else:
                bullets = ["Observe", "Connect", "Remember"]

        try:
            duration = int(incoming.get("duration_sec") or (6 if idx == 0 else 8))
        except Exception:
            duration = 8
        duration = max(4, min(14, duration))

        scenes.append(
            {
                "id": idx + 1,
                "kind": kind,
                "heading": heading,
                "narration": narration,
                "bullets": bullets,
                "visual_goal": visual_goal,
                "duration_sec": duration,
            }
        )

    return {"title": title, "audience": str(plan.get("audience") or "general"), "scenes": scenes}


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def build_scene_fallback_code(scene: dict[str, Any]) -> str:
    heading = str(scene.get("heading") or "Key idea").strip()[:70] or "Key idea"
    narration = (
        str(scene.get("narration") or scene.get("caption") or heading).strip()[:240]
        or f"Here is the key idea: {heading}."
    )

    bullets = scene.get("bullets")
    if not isinstance(bullets, list) or not bullets:
        bullets = ["Main idea", "Visual example", "Quick takeaway"]
    bullets = [str(b or "").strip()[:54] for b in bullets[:4] if str(b or "").strip()]
    if not bullets:
        bullets = ["Main idea", "Visual example", "Quick takeaway"]

    kind = str(scene.get("kind") or "fallback").strip()[:30]
    heading_json = _safe_json(heading)
    narration_json = _safe_json(narration)
    bullets_json = _safe_json(bullets)
    kind_json = _safe_json(kind)

    return f'''
from manim import *  # noqa: F403,F405
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class GeneratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(lang="en"))

        heading = {heading_json}
        narration = {narration_json}
        bullets_data = {bullets_json}
        scene_kind = {kind_json}

        bg = Rectangle(width=config.frame_width, height=config.frame_height)
        bg.set_fill("#0f172a", opacity=1)
        bg.set_stroke(width=0)
        self.add(bg)

        with self.voiceover(text=narration) as tracker:
            label = Text(scene_kind.upper(), font_size=20, color=BLUE_C)
            label.to_edge(UP, buff=0.3)

            title = Text(heading, font_size=38, color=WHITE)
            title.next_to(label, DOWN, buff=0.35)

            card = RoundedRectangle(
                width=10.6,
                height=4.5,
                corner_radius=0.25,
                stroke_color=BLUE_C,
                stroke_width=2,
                fill_color="#1e293b",
                fill_opacity=0.92,
            )
            card.shift(DOWN * 0.35)

            bullet_mobs = VGroup(
                *[
                    Text("• " + item, font_size=28, color=WHITE)
                    for item in bullets_data
                ]
            )
            bullet_mobs.arrange(DOWN, aligned_edge=LEFT, buff=0.35)
            bullet_mobs.move_to(card.get_center())

            accent = Circle(radius=0.18, color=YELLOW, fill_opacity=0.9)
            accent.next_to(title, LEFT, buff=0.25)

            self.play(FadeIn(label), FadeIn(accent), Write(title), run_time=1.0)
            self.play(FadeIn(card), run_time=0.6)
            self.play(
                LaggedStart(
                    *[FadeIn(item, shift=UP * 0.2) for item in bullet_mobs],
                    lag_ratio=0.18,
                ),
                run_time=2.0,
            )
            self.wait(0.4)

        snapshot = list(self.mobjects)
        if snapshot:
            self.play(*[FadeOut(m) for m in snapshot], run_time=0.6)
        self.wait(0.1)
'''.strip() + "\\n"


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

    first_code = sanitize_minimally(code)
    first = run_job_from_code(first_code, job_id=scene_job_id, timeout_seconds=240)
    if first.get("ok") and first.get("video_url"):
        return _video_url_to_path(first["video_url"]), {
            "scene_index": scene_index,
            "used_fallback": False,
            "job_id": first.get("job_id"),
        }

    logger.warning(
        "structured video scene %s failed; using fallback. error=%s",
        scene_index,
        first.get("error") or first.get("error_log") or "unknown",
    )

    fallback_code = build_scene_fallback_code(scene)
    fallback_job_id = f"{final_job_id}_s{scene_index:02d}_fallback"
    fallback = run_job_from_code(fallback_code, job_id=fallback_job_id, timeout_seconds=240)

    if fallback.get("ok") and fallback.get("video_url"):
        return _video_url_to_path(fallback["video_url"]), {
            "scene_index": scene_index,
            "used_fallback": True,
            "primary_error": first.get("error") or first.get("error_log"),
            "primary_job_id": first.get("job_id"),
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
        "\\n".join([f"file '{clip.as_posix()}'" for clip in clips]) + "\\n",
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
        raise RuntimeError(f"ffmpeg concat failed: {(reencode_proc.stderr or copy_proc.stderr)[-1000:]}")


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

    out_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


def _bundle_for_scene_code(plan: dict[str, Any], scene_codes: list[str], raw_bundle: str) -> str:
    pieces = [
        "# Structured UpcurvEd Manim bundle",
        "# This is not one monolithic Manim script.",
        "# It contains the plan and the per-scene scripts used to build the final video.",
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

    pieces.extend(["<<<RAW_MODEL_BUNDLE>>>", raw_bundle.strip(), "<<<END_RAW_MODEL_BUNDLE>>>", ""])
    return "\\n".join(pieces)


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
        "structured_manim_generation_start job_id=%s provider=%s model=%s",
        final_job_id,
        provider_name,
        model,
    )

    raw_bundle = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_SYSTEM,
        user=build_structured_video_user_prompt(prompt),
        temperature=0.35,
        max_tokens=10000,
    )

    (logs_dir / "structured_raw_bundle.txt").write_text(raw_bundle or "", encoding="utf-8")
    plan, scene_codes = parse_structured_video_bundle(raw_bundle or "")
    (logs_dir / "structured_plan.json").write_text(
        json.dumps(plan, ensure_ascii=True, indent=2),
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

    final_vtt = final_job_dir / "video.vtt"
    _write_vtt_from_plan(plan, final_vtt)

    scene_code = _bundle_for_scene_code(plan, scene_codes, raw_bundle or "")
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
