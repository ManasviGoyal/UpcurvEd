"""
Structured Manim video generation: dynamic scene-object architecture.

The first LLM call returns one JSON video object containing both the lesson plan
and any bounded ``manim_body`` code required by creative scenes. Standard scene
types are rendered by deterministic backend components. A creative scene gets
at most one conditional repair LLM call when its body fails validation or
rendering; if repair still fails, that scene becomes a deterministic concept
scene so the complete video can continue.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import textwrap
import uuid
from typing import Any

from backend.agent.code_sanitize import sanitize_minimally
from backend.agent.llm.clients import call_llm
from backend.agent.prompts import (
    STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM,
    STRUCTURED_VIDEO_EDIT_SYSTEM,
    STRUCTURED_VIDEO_SYSTEM,
    build_structured_video_creative_repair_prompt,
    build_structured_video_edit_user_prompt,
    build_structured_video_user_prompt,
)
from backend.agent.video_components import (
    build_component_scene_code,
    build_concept_fallback_scene_code,
    build_custom_scene_code,
)
from backend.runner.job_runner import STORAGE, run_job_from_code, to_static_url

logger = logging.getLogger(f"app.{__name__}")

_ALLOWED_TYPES = {
    "title_scene",
    "question_scene",
    "concept_scene",
    "process_scene",
    "comparison_scene",
    "custom_manim_scene",
}

_GENERIC_LABELS = {
    "begin",
    "case a",
    "case b",
    "change",
    "concept",
    "equation",
    "example",
    "formula",
    "idea",
    "input",
    "key difference",
    "main idea",
    "output",
    "process",
    "result",
    "step",
    "takeaway",
    "what changes",
    "what stays",
    "why it matters",
}

# Kept only so previously generated structured bundles can still be edited.
_OLD_KIND_TO_TYPE = {
    "title": "title_scene",
    "key_points": "concept_scene",
    "diagram": "concept_scene",
    "flow_diagram": "process_scene",
    "cycle_diagram": "process_scene",
    "timeline": "process_scene",
    "comparison": "comparison_scene",
    "chart": "comparison_scene",
    "system_map": "concept_scene",
    "pseudo_3d": "custom_manim_scene",
    "creative": "custom_manim_scene",
}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


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

    match = re.search(r"\{[\s\S]*\}", clean)
    if not match:
        raise RuntimeError("Structured video plan is missing valid JSON.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise RuntimeError("Structured video JSON was not an object.")
    return parsed


def _extract_python_code(raw: str) -> str:
    text = (raw or "").strip()
    fence = re.search(r"```(?:python|py)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return text.strip()


def _short_text(value: Any, limit: int, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\x00", "")
    return text[:limit].strip() or fallback


def _is_generic_label(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return normalized in _GENERIC_LABELS


def _label_candidate(value: Any, limit: int = 42) -> str:
    text = _short_text(value, limit, "")
    text = re.split(r"[.;:]", text, maxsplit=1)[0].strip()
    return text


def _normalize_scene_labels(
    labels_in: Any,
    *,
    fallback_labels: list[Any],
    scene_title: str,
    scene_subtitle: str,
    visual: str,
) -> list[str]:
    labels: list[str] = []

    def add(value: Any) -> None:
        label = _label_candidate(value)
        if not label or _is_generic_label(label):
            return
        if label.lower() in {item.lower() for item in labels}:
            return
        labels.append(label)

    if isinstance(labels_in, list):
        for item in labels_in[:5]:
            add(item)

    for item in (scene_title, scene_subtitle, visual):
        if len(labels) >= 3:
            break
        add(item)

    for item in fallback_labels:
        if len(labels) >= 3:
            break
        add(item)

    if not labels:
        labels = [scene_title or "Key relationship"]

    while len(labels) < 3:
        candidate = f"{scene_title} detail {len(labels) + 1}".strip()
        if candidate.lower() not in {item.lower() for item in labels}:
            labels.append(_short_text(candidate, 42, "Key relationship"))

    return labels[:5]


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _default_plan(topic: str) -> dict[str, Any]:
    """Local emergency plan used only when model JSON is missing or malformed."""
    safe_topic = _short_text(topic, 60, "Learning topic")
    return {
        "title": safe_topic,
        "subtitle": "A short visual explanation",
        "audience": "general",
        "scenes": [
            {
                "id": 1,
                "type": "title_scene",
                "title": safe_topic,
                "subtitle": "The main idea in one picture",
                "narration": f"Let us build a clear picture of {safe_topic}.",
                "visual": "Reveal the lesson title and its central idea.",
                "labels": [safe_topic, "main idea"],
                "duration_sec": 9,
            },
            {
                "id": 2,
                "type": "question_scene",
                "title": "Start with a question",
                "subtitle": f"What should we notice about {safe_topic}?",
                "narration": f"A useful question helps us identify what matters most in {safe_topic}.",
                "visual": "Show one central question and three clues.",
                "labels": ["what changes", "what stays", "why it matters"],
                "duration_sec": 11,
            },
            {
                "id": 3,
                "type": "process_scene",
                "title": "Follow the idea",
                "subtitle": "See the relationship step by step",
                "narration": f"Now follow the important parts of {safe_topic} in a simple sequence.",
                "visual": "Show three connected steps.",
                "labels": ["begin", "change", "result"],
                "duration_sec": 13,
            },
            {
                "id": 4,
                "type": "comparison_scene",
                "title": "Make the difference visible",
                "subtitle": "Compare two cases",
                "narration": f"A comparison makes the main lesson about {safe_topic} easier to remember.",
                "visual": "Show two labeled cases side by side.",
                "labels": ["case A", "case B", "key difference"],
                "duration_sec": 12,
            },
        ],
    }


def _default_scene_type(index: int, total: int) -> str:
    if index == 0:
        return "title_scene"
    if total > 2 and index == total - 1:
        return "comparison_scene"
    if index == 1:
        return "question_scene"
    return "concept_scene"


def _scene_type_from(incoming: dict[str, Any], index: int, total: int) -> str:
    raw_type = _short_text(
        incoming.get("type") or incoming.get("scene_type"), 36, ""
    ).lower().replace(" ", "_")
    raw_kind = _short_text(incoming.get("kind"), 36, "").lower().replace(" ", "_")
    scene_type = raw_type or _OLD_KIND_TO_TYPE.get(raw_kind, "")
    if scene_type not in _ALLOWED_TYPES:
        scene_type = _default_scene_type(index, total)
    if index == 0:
        return "title_scene"
    return scene_type


def _clean_student_narration(value: Any, fallback: str) -> str:
    text = _short_text(value, 420, fallback)
    banned = (
        "visual beat",
        "this scene",
        "scene ",
        "hook",
        "template",
        "input",
        "process output",
    )
    lower = text.lower()
    if any(word in lower for word in banned):
        return fallback
    return text


def _normalize_plan(plan: dict[str, Any], topic: str | None = None) -> dict[str, Any]:
    """Normalize the number of scenes returned by the model; do not force a count."""
    fallback = _default_plan(topic or "Learning topic")
    title = _short_text(plan.get("title"), 80, fallback["title"])
    subtitle = _short_text(
        plan.get("subtitle"), 100, fallback.get("subtitle", "A short visual explanation")
    )

    scenes_in = plan.get("scenes")
    if not isinstance(scenes_in, list) or not any(isinstance(x, dict) for x in scenes_in):
        scenes_in = list(fallback["scenes"])

    # The model chooses the scene count. This is only a safety ceiling against
    # accidental giant outputs, and can be raised without changing the prompt.
    max_scenes = _env_int("UPCURVED_MAX_SCENES", 10, 1, 24)
    scenes_in = [x for x in scenes_in if isinstance(x, dict)][:max_scenes]
    if not scenes_in:
        scenes_in = list(fallback["scenes"])

    max_custom = _env_int("UPCURVED_MAX_CUSTOM_SCENES", 2, 0, 6)
    custom_seen = 0
    scenes: list[dict[str, Any]] = []
    total = len(scenes_in)

    for index, incoming in enumerate(scenes_in):
        fallback_scene = fallback["scenes"][min(index, len(fallback["scenes"]) - 1)]
        scene_type = _scene_type_from(incoming, index, total)
        if scene_type == "custom_manim_scene":
            if custom_seen >= max_custom:
                scene_type = "concept_scene"
            else:
                custom_seen += 1

        scene_title = _short_text(
            incoming.get("title") or incoming.get("heading"),
            72,
            fallback_scene["title"],
        )
        scene_subtitle = _short_text(
            incoming.get("subtitle"), 90, fallback_scene.get("subtitle", "")
        )
        fallback_narration = str(fallback_scene.get("narration") or scene_title)
        narration = _clean_student_narration(
            incoming.get("narration") or incoming.get("say") or incoming.get("caption"),
            fallback_narration,
        )
        visual = _short_text(
            incoming.get("visual")
            or incoming.get("visual_goal")
            or incoming.get("code_goal"),
            260,
            fallback_scene.get("visual", "Show the idea clearly."),
        )

        formula = _short_text(
            incoming.get("formula") or incoming.get("equation"),
            180,
            "",
        )

        labels_in = (
            incoming.get("labels")
            if isinstance(incoming.get("labels"), list)
            else incoming.get("bullets")
        )
        labels = _normalize_scene_labels(
            labels_in,
            fallback_labels=list(
                fallback_scene.get("labels") or fallback_scene.get("bullets") or []
            ),
            scene_title=scene_title,
            scene_subtitle=scene_subtitle,
            visual=visual,
        )

        try:
            duration = int(incoming.get("duration_sec") or fallback_scene.get("duration_sec") or 12)
        except Exception:
            duration = int(fallback_scene.get("duration_sec") or 12)
        duration = max(6, min(30, duration))
        if scene_type == "custom_manim_scene":
            duration = max(10, duration)

        scene: dict[str, Any] = {
            "id": index + 1,
            "type": scene_type,
            "kind": scene_type,
            "heading": scene_title,
            "title": scene_title,
            "subtitle": scene_subtitle,
            "narration": narration,
            "visual": visual,
            "visual_goal": visual,
            "labels": labels,
            "bullets": labels[:4],
            "duration_sec": duration,
        }
        if formula:
            scene["formula"] = formula

        if scene_type == "custom_manim_scene":
            scene["code_goal"] = _short_text(
                incoming.get("code_goal") or visual,
                320,
                f"Animate a clear topic-specific visual for {scene_title}.",
            )
            body = str(incoming.get("manim_body") or incoming.get("code_body") or "").strip()
            if body:
                scene["manim_body"] = body

        scenes.append(scene)

    return {
        "title": title,
        "subtitle": subtitle,
        "audience": str(plan.get("audience") or "general"),
        "scenes": scenes,
    }


def parse_structured_video_plan(raw: str, topic: str) -> dict[str, Any]:
    try:
        plan_text = _extract_block(raw, "PLAN_JSON") or raw
        return _normalize_plan(_extract_json_object(plan_text), topic=topic)
    except Exception as exc:
        logger.warning("structured video plan parse failed; using local default plan: %s", exc)
        return _normalize_plan(_default_plan(topic), topic=topic)


def parse_plan_from_scene_bundle(bundle: str, topic: str = "Edited video") -> dict[str, Any]:
    plan_text = _extract_block(bundle or "", "PLAN_JSON")
    if not plan_text:
        raise RuntimeError(
            "Original video is not a structured scene bundle; PLAN_JSON is missing. "
            "Legacy monolithic videos are no longer supported by the edit endpoint."
        )
    return _normalize_plan(_extract_json_object(plan_text), topic=topic)


def is_structured_scene_bundle(text: str | None) -> bool:
    value = text or ""
    return "<<<PLAN_JSON>>>" in value and "<<<END_PLAN_JSON>>>" in value


def build_template_scene_code(scene: dict[str, Any]) -> str:
    return build_component_scene_code(scene)


def _video_url_to_path(video_url: str) -> pathlib.Path:
    relative = video_url.replace("/static/", "", 1)
    return STORAGE / relative


def _render_error_detail(result: dict[str, Any]) -> str:
    value = (
        result.get("error")
        or result.get("error_log")
        or result.get("stderr")
        or result.get("compile_log")
        or result.get("message")
        or "Unknown Manim render error."
    )
    return str(value)[-5000:]


def _run_scene_code(
    *,
    code: str,
    job_id: str,
    timeout_seconds: int = 240,
) -> tuple[pathlib.Path | None, dict[str, Any]]:
    safe_code = sanitize_minimally(code).strip() + "\n"
    result = run_job_from_code(
        safe_code,
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        inject_watermark=False,
    )
    if result.get("ok") and result.get("video_url"):
        return _video_url_to_path(result["video_url"]), result
    return None, result


def _validate_custom_body(body: str, formula: str = "") -> list[str]:
    """Return actionable validation errors for a model-authored construct body."""
    cleaned = (body or "").strip()
    errors: list[str] = []
    if not cleaned:
        return ["The manim_body is empty."]

    if len(cleaned) > 18000:
        errors.append("The manim_body is too long; keep it under 18,000 characters.")
    if len(cleaned.splitlines()) > 320:
        errors.append("The manim_body has too many lines; keep it under 320 lines.")

    lowered = cleaned.lower()
    forbidden_patterns = {
        r"(^|\n)\s*import\s+": "Imports are not allowed.",
        r"(^|\n)\s*from\s+": "Imports are not allowed.",
        r"(^|\n)\s*class\s+": "Class definitions are not allowed.",
        r"(^|\n)\s*def\s+": "Function definitions are not allowed.",
        r"\bopen\s*\(": "File access with open() is not allowed.",
        r"\brequests\b": "Network libraries are not allowed.",
        r"\bsubprocess\b": "subprocess is not allowed.",
        r"\bos\.": "os access is not allowed.",
        r"\bpathlib\b": "pathlib is not allowed.",
        r"\bsys\.": "sys access is not allowed.",
        r"\beval\s*\(": "eval() is not allowed.",
        r"\bexec\s*\(": "exec() is not allowed.",
        r"__\w+__": "Dunder attribute access is not allowed.",
        r"\bimagemobject\b": "ImageMobject is not allowed.",
        r"\bsvgmobject\b": "SVGMobject is not allowed.",
        r"\bmathtex\b": "MathTex is not allowed.",
        r"\btex\s*\(": "Tex is not allowed.",
        r"\brandom\b": "Random behavior is not allowed.",
    }
    for pattern, message in forbidden_patterns.items():
        if re.search(pattern, lowered, flags=re.IGNORECASE | re.MULTILINE):
            errors.append(message)

    voiceover_count = cleaned.count("self.voiceover")
    if voiceover_count < 2:
        errors.append(f"Expected at least 2 self.voiceover blocks; found {voiceover_count}.")

    play_count = cleaned.count("self.play")
    if play_count < 4:
        errors.append(f"Expected at least 4 self.play calls; found {play_count}.")

    motion_markers = (
        ".animate",
        "mn.Transform(",
        "mn.ReplacementTransform(",
        "mn.MoveAlongPath(",
        "mn.GrowArrow(",
        "mn.Rotate(",
        "mn.GrowFromCenter(",
        "mn.Create(",
        "mn.Indicate(",
        "mn.GrowFromEdge(",
    )
    if not any(marker in cleaned for marker in motion_markers):
        errors.append("The scene needs meaningful movement or transformation.")

    formula_text = str(formula or "").strip()
    if formula_text and "formula" not in cleaned and formula_text not in cleaned:
        errors.append(
            "The scene has a formula field, but manim_body does not display formula. "
            "Use formula_label(formula) or mn.Text(formula)."
        )

    try:
        wrapped = "def _generated(self):\n" + textwrap.indent(cleaned, "    ")
        ast.parse(wrapped)
    except SyntaxError as exc:
        errors.append(f"Python syntax error: {exc.msg} at wrapped line {exc.lineno}.")

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(errors))


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")


def _repair_custom_scene_body(
    *,
    scene: dict[str, Any],
    original_body: str,
    error_detail: str,
    failure_stage: str,
    provider_name: str,
    api_key: str,
    model: str | None,
    logs_dir: pathlib.Path,
    scene_number: int,
) -> str:
    raw = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM,
        user=build_structured_video_creative_repair_prompt(
            scene=scene,
            original_body=original_body,
            failure_stage=failure_stage,
            error_detail=error_detail,
        ),
        temperature=0.08,
        max_tokens=3000,
        max_output_tokens=3000,
    )
    (logs_dir / f"custom_scene_{scene_number}_repair_raw.txt").write_text(
        raw or "", encoding="utf-8"
    )
    return _extract_python_code(raw or "")


def _concept_fallback_scene(
    *,
    scene: dict[str, Any],
    final_job_id: str,
    scene_number: int,
    reason: str,
    prior_result: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[pathlib.Path, str, dict[str, Any]]:
    fallback_code = build_concept_fallback_scene_code(scene)
    fallback_job_id = f"{final_job_id}_s{scene_number:02d}_concept"
    clip, result = _run_scene_code(code=fallback_code, job_id=fallback_job_id)
    if clip is None:
        first_error = _render_error_detail(prior_result or {})
        fallback_error = _render_error_detail(result)
        raise RuntimeError(
            f"Concept fallback failed for scene {scene_number}. "
            f"Original failure: {first_error}. Fallback failure: {fallback_error}"
        )
    scene["render_source"] = "concept_fallback"
    scene_result = dict(metadata or {})
    scene_result.update(
        {
            "scene_index": scene_number,
            "used_fallback": True,
            "render_source": "concept_fallback",
            "fallback_reason": reason[:1000],
            "job_id": result.get("job_id"),
        }
    )
    return clip, fallback_code, scene_result


def _render_component_scene(
    *,
    scene: dict[str, Any],
    final_job_id: str,
    scene_number: int,
) -> tuple[pathlib.Path, str, dict[str, Any]]:
    code = build_component_scene_code(scene)
    scene_job_id = f"{final_job_id}_s{scene_number:02d}"
    clip, result = _run_scene_code(code=code, job_id=scene_job_id)
    if clip is not None:
        return clip, code, {
            "scene_index": scene_number,
            "used_fallback": False,
            "render_source": "component_scene",
            "job_id": result.get("job_id"),
        }

    error_detail = _render_error_detail(result)
    logger.warning(
        "structured component scene %s failed; using concept fallback. error=%s",
        scene_number,
        error_detail[-800:],
    )
    return _concept_fallback_scene(
        scene=scene,
        final_job_id=final_job_id,
        scene_number=scene_number,
        reason=f"Component render failed: {error_detail}",
        prior_result=result,
    )


def _render_custom_scene(
    *,
    scene: dict[str, Any],
    final_job_id: str,
    scene_number: int,
    provider_name: str,
    api_key: str,
    model: str | None,
    logs_dir: pathlib.Path,
) -> tuple[pathlib.Path, str, dict[str, Any]]:
    """Validate/render once, conditionally repair once, then concept fallback."""
    initial_body = str(scene.get("manim_body") or "").strip()
    (logs_dir / f"custom_scene_{scene_number}_initial_body.py").write_text(
        initial_body, encoding="utf-8"
    )

    result_log: dict[str, Any] = {
        "scene_index": scene_number,
        "initial_source": "embedded_manim_body",
        "repair_requested": False,
        "used_fallback": False,
    }

    validation_errors = _validate_custom_body(
        initial_body, str(scene.get("formula") or "")
    )
    _write_json(
        logs_dir / f"custom_scene_{scene_number}_initial_validation.json",
        {"ok": not validation_errors, "errors": validation_errors},
    )
    result_log["initial_validation"] = "passed" if not validation_errors else "failed"

    body_to_render = initial_body
    repaired = False

    if validation_errors:
        result_log["repair_requested"] = True
        result_log["repair_reason"] = "validation"
        try:
            body_to_render = _repair_custom_scene_body(
                scene=scene,
                original_body=initial_body,
                error_detail="\n".join(validation_errors),
                failure_stage="validation",
                provider_name=provider_name,
                api_key=api_key,
                model=model,
                logs_dir=logs_dir,
                scene_number=scene_number,
            )
            repaired = True
        except Exception as exc:
            result_log["repair_call_error"] = str(exc)[:1000]
            logger.warning("creative scene repair call failed for scene %s: %s", scene_number, exc)
            return _concept_fallback_scene(
                scene=scene,
                final_job_id=final_job_id,
                scene_number=scene_number,
                reason=f"Initial validation failed and repair call failed: {exc}",
                metadata=result_log,
            )

        (logs_dir / f"custom_scene_{scene_number}_repaired_body.py").write_text(
            body_to_render, encoding="utf-8"
        )
        repaired_errors = _validate_custom_body(
            body_to_render, str(scene.get("formula") or "")
        )
        _write_json(
            logs_dir / f"custom_scene_{scene_number}_repair_validation.json",
            {"ok": not repaired_errors, "errors": repaired_errors},
        )
        result_log["repair_validation"] = "passed" if not repaired_errors else "failed"
        if repaired_errors:
            result_log["repair_validation_errors"] = repaired_errors
            return _concept_fallback_scene(
                scene=scene,
                final_job_id=final_job_id,
                scene_number=scene_number,
                reason="Repair body failed validation: " + "; ".join(repaired_errors),
                metadata=result_log,
            )

    code = build_custom_scene_code(scene, body_to_render)
    render_suffix = "repair" if repaired else "custom"
    scene_job_id = f"{final_job_id}_s{scene_number:02d}_{render_suffix}"
    clip, render_result = _run_scene_code(code=code, job_id=scene_job_id)
    if clip is not None:
        final_source = "repaired_custom_body" if repaired else "custom_body"
        scene["render_source"] = final_source
        if repaired:
            scene["manim_body"] = body_to_render
        result_log.update(
            {
                "initial_render": "not_attempted" if validation_errors else "success",
                "repair_render": "success" if repaired else "not_needed",
                "render_source": final_source,
                "job_id": render_result.get("job_id"),
            }
        )
        return clip, code, result_log

    render_error = _render_error_detail(render_result)
    (logs_dir / f"custom_scene_{scene_number}_{render_suffix}_render_error.txt").write_text(
        render_error, encoding="utf-8"
    )

    # If validation already caused the one repair call, do not call the model again.
    if repaired:
        result_log["repair_render"] = "failed"
        result_log["repair_render_error"] = render_error[:1500]
        return _concept_fallback_scene(
            scene=scene,
            final_job_id=final_job_id,
            scene_number=scene_number,
            reason=f"Repaired custom scene failed to render: {render_error}",
            prior_result=render_result,
            metadata=result_log,
        )

    # Initial body passed validation but failed at runtime: use the one repair call now.
    result_log["initial_render"] = "failed"
    result_log["initial_render_error"] = render_error[:1500]
    result_log["repair_requested"] = True
    result_log["repair_reason"] = "render"
    try:
        repaired_body = _repair_custom_scene_body(
            scene=scene,
            original_body=initial_body,
            error_detail=render_error,
            failure_stage="render",
            provider_name=provider_name,
            api_key=api_key,
            model=model,
            logs_dir=logs_dir,
            scene_number=scene_number,
        )
    except Exception as exc:
        result_log["repair_call_error"] = str(exc)[:1000]
        return _concept_fallback_scene(
            scene=scene,
            final_job_id=final_job_id,
            scene_number=scene_number,
            reason=f"Initial custom render failed and repair call failed: {exc}",
            prior_result=render_result,
            metadata=result_log,
        )

    (logs_dir / f"custom_scene_{scene_number}_repaired_body.py").write_text(
        repaired_body, encoding="utf-8"
    )
    repaired_errors = _validate_custom_body(
        repaired_body, str(scene.get("formula") or "")
    )
    _write_json(
        logs_dir / f"custom_scene_{scene_number}_repair_validation.json",
        {"ok": not repaired_errors, "errors": repaired_errors},
    )
    result_log["repair_validation"] = "passed" if not repaired_errors else "failed"
    if repaired_errors:
        result_log["repair_validation_errors"] = repaired_errors
        return _concept_fallback_scene(
            scene=scene,
            final_job_id=final_job_id,
            scene_number=scene_number,
            reason="Render-repair body failed validation: " + "; ".join(repaired_errors),
            prior_result=render_result,
            metadata=result_log,
        )

    repaired_code = build_custom_scene_code(scene, repaired_body)
    repaired_job_id = f"{final_job_id}_s{scene_number:02d}_repair"
    repaired_clip, repaired_result = _run_scene_code(
        code=repaired_code, job_id=repaired_job_id
    )
    if repaired_clip is not None:
        scene["render_source"] = "repaired_custom_body"
        scene["manim_body"] = repaired_body
        result_log.update(
            {
                "repair_render": "success",
                "render_source": "repaired_custom_body",
                "job_id": repaired_result.get("job_id"),
            }
        )
        return repaired_clip, repaired_code, result_log

    repaired_render_error = _render_error_detail(repaired_result)
    (logs_dir / f"custom_scene_{scene_number}_repair_render_error.txt").write_text(
        repaired_render_error, encoding="utf-8"
    )
    result_log["repair_render"] = "failed"
    result_log["repair_render_error"] = repaired_render_error[:1500]
    return _concept_fallback_scene(
        scene=scene,
        final_job_id=final_job_id,
        scene_number=scene_number,
        reason=f"Custom scene and one repair attempt both failed: {repaired_render_error}",
        prior_result=repaired_result,
        metadata=result_log,
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
    (logs_dir / "concat_reencode_cmd.txt").write_text(
        " ".join(reencode_cmd), encoding="utf-8"
    )
    (logs_dir / "concat_reencode_stdout.txt").write_text(
        reencode_proc.stdout or "", encoding="utf-8"
    )
    (logs_dir / "concat_reencode_stderr.txt").write_text(
        reencode_proc.stderr or "", encoding="utf-8"
    )

    if reencode_proc.returncode != 0 or not final_mp4.exists():
        detail = (reencode_proc.stderr or copy_proc.stderr or "")[-1500:]
        raise RuntimeError(f"ffmpeg concat failed: {detail}")


def _apply_final_watermark(final_mp4: pathlib.Path, logs_dir: pathlib.Path) -> None:
    try:
        ffmpeg_bin = _find_ffmpeg()
        tmp_mp4 = final_mp4.with_name("video_watermarked.mp4")
        text = "Generated using UpcurvEd"
        vf = (
            "drawtext="
            f"text='{text}':"
            "x=w-tw-18:y=h-th-18:"
            "fontsize=16:"
            "fontcolor=white@0.78:"
            "box=1:boxcolor=black@0.35:boxborderw=6"
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
            logger.warning("final video watermark skipped: %s", (proc.stderr or "")[-500:])
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
        heading = str(scene.get("heading") or scene.get("title") or "").strip()
        narration = str(scene.get("narration") or heading or "Scene").strip()
        start = _format_vtt_ts(cursor)
        end = _format_vtt_ts(cursor + duration)
        caption = f"{heading}: {narration}" if heading else narration
        lines.append(f"{start} --> {end}")
        lines.append(caption[:260])
        lines.append("")
        cursor += duration

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bundle_for_scene_code(plan: dict[str, Any], scene_codes: list[str], raw_plan: str) -> str:
    pieces = [
        "# Structured UpcurvEd Manim bundle v3",
        "# The model returned a dynamic scene plan and any creative Manim bodies in one call.",
        "# Standard scene scripts were generated by deterministic backend components.",
        "",
        "<<<PLAN_JSON>>>",
        json.dumps(plan, ensure_ascii=True, indent=2),
        "<<<END_PLAN_JSON>>>",
        "",
    ]
    for index, code in enumerate(scene_codes, start=1):
        pieces.extend(
            [
                f"<<<SCENE_{index}_CODE>>>",
                code.strip(),
                f"<<<END_SCENE_{index}_CODE>>>",
                "",
            ]
        )

    pieces.extend(
        ["<<<RAW_MODEL_PLAN>>>", (raw_plan or "").strip(), "<<<END_RAW_MODEL_PLAN>>>", ""]
    )
    return "\n".join(pieces)


def _render_structured_plan(
    *,
    plan: dict[str, Any],
    raw_plan: str,
    final_job_id: str,
    provider_name: str,
    api_key: str,
    model: str | None,
) -> dict[str, Any]:
    final_job_dir = STORAGE / "jobs" / final_job_id
    logs_dir = final_job_dir / "logs"
    final_job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    _write_json(logs_dir / "structured_plan.json", plan)

    clips: list[pathlib.Path] = []
    scene_codes: list[str] = []
    scene_results: list[dict[str, Any]] = []

    for scene_number, scene in enumerate(plan["scenes"], start=1):
        if scene.get("type") == "custom_manim_scene":
            clip_path, code, scene_result = _render_custom_scene(
                scene=scene,
                final_job_id=final_job_id,
                scene_number=scene_number,
                provider_name=provider_name,
                api_key=api_key,
                model=model,
                logs_dir=logs_dir,
            )
        else:
            clip_path, code, scene_result = _render_component_scene(
                scene=scene,
                final_job_id=final_job_id,
                scene_number=scene_number,
            )
        clips.append(clip_path)
        scene_codes.append(code)
        scene_results.append(scene_result)
        _write_json(logs_dir / "structured_scene_results.json", scene_results)

    final_mp4 = final_job_dir / "video.mp4"
    _concat_clips(clips, final_mp4, logs_dir)
    _apply_final_watermark(final_mp4, logs_dir)

    final_vtt = final_job_dir / "video.vtt"
    _write_vtt_from_plan(plan, final_vtt)

    scene_code = _bundle_for_scene_code(plan, scene_codes, raw_plan or "")
    (final_job_dir / "scene_bundle.txt").write_text(scene_code, encoding="utf-8")
    _write_json(logs_dir / "structured_final_plan.json", plan)

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


def _inherit_missing_custom_bodies(
    edited_plan: dict[str, Any], original_plan: dict[str, Any]
) -> dict[str, Any]:
    """Preserve unchanged formulas and creative code when an edit omits them."""
    original_scenes = original_plan.get("scenes") if isinstance(original_plan.get("scenes"), list) else []
    edited_scenes = edited_plan.get("scenes") if isinstance(edited_plan.get("scenes"), list) else []
    originals_by_id = {
        str(scene.get("id")): scene
        for scene in original_scenes
        if isinstance(scene, dict) and scene.get("id") is not None
    }

    for index, scene in enumerate(edited_scenes):
        if not isinstance(scene, dict):
            continue

        original = originals_by_id.get(str(scene.get("id")))
        if not isinstance(original, dict) and index < len(original_scenes):
            candidate = original_scenes[index]
            original = candidate if isinstance(candidate, dict) else None
        if not isinstance(original, dict):
            continue

        if not str(scene.get("formula") or "").strip():
            original_formula = str(original.get("formula") or "").strip()
            if original_formula:
                scene["formula"] = original_formula

        if scene.get("type") == "custom_manim_scene" and not str(
            scene.get("manim_body") or ""
        ).strip():
            body = str(original.get("manim_body") or "").strip()
            if body:
                scene["manim_body"] = body
    return edited_plan


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
        "structured_manim_generation_start job_id=%s provider=%s model=%s mode=dynamic_scene_object_one_call",
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
        temperature=0.24,
        max_tokens=9000,
        max_output_tokens=9000,
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
    """Edit the complete dynamic plan, then use the same render/repair pipeline."""
    provider_name, api_key = _pick_provider_and_key(provider, provider_keys)
    final_job_id = job_id or str(uuid.uuid4())[:8]
    final_job_dir = STORAGE / "jobs" / final_job_id
    logs_dir = final_job_dir / "logs"
    final_job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    original_plan = parse_plan_from_scene_bundle(original_bundle, topic="Edited video")
    _write_json(logs_dir / "structured_original_plan.json", original_plan)

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
        temperature=0.12,
        max_tokens=9000,
        max_output_tokens=9000,
    )

    (logs_dir / "structured_raw_edited_plan.txt").write_text(
        raw_edited_plan or "", encoding="utf-8"
    )
    edited_plan = parse_structured_video_plan(
        raw_edited_plan or "",
        topic=str(original_plan.get("title") or "Edited video"),
    )
    edited_plan = _inherit_missing_custom_bodies(edited_plan, original_plan)

    return _render_structured_plan(
        plan=edited_plan,
        raw_plan=raw_edited_plan or "",
        final_job_id=final_job_id,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
    )
