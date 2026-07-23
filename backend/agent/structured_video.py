"""Structured Manim video generation for UpcurvEd.

One model response contains low-fragility tagged scene fields plus separate raw Manim bodies.
The parser salvages complete scenes independently and retains legacy JSON compatibility for
existing bundles/models. Standard scenes render deterministically. Custom scenes receive static
validation, one focused repair attempt, and a deterministic fallback when the creative visual is
not essential. Graph scenes remain essential.
"""

from __future__ import annotations

import ast
import html
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
from backend.agent.llm.provider_config import (
    resolve_provider_and_key as _pick_provider_and_key,
)
from backend.agent.prompts import (
    STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM,
    STRUCTURED_VIDEO_EDIT_SYSTEM,
    STRUCTURED_VIDEO_PLAN_REPAIR_SYSTEM,
    STRUCTURED_VIDEO_SYSTEM,
    build_structured_video_creative_repair_prompt,
    build_structured_video_edit_user_prompt,
    build_structured_video_plan_repair_prompt,
    build_structured_video_user_prompt,
)
from backend.agent.video_components import (
    build_component_scene_code,
    build_concept_fallback_scene_code,
    build_custom_scene_code,
    portable_math_text,
)
from backend.runner.job_runner import STORAGE, run_job_from_code, to_static_url


logger = logging.getLogger(__name__)

_PLAN_START = "<<<PLAN_JSON>>>"
_PLAN_END = "<<<END_PLAN_JSON>>>"
_RAW_PLAN_START = "<<<RAW_MODEL_RESPONSE>>>"
_RAW_PLAN_END = "<<<END_RAW_MODEL_RESPONSE>>>"
_VIDEO_META_TAG = "VIDEO_META"
_SCENE_PLAN_TAG = "SCENE_PLAN"
_VIDEO_PLAN_TAG = "VIDEO_PLAN"  # legacy JSON transport
_MANIM_BODY_TAG = "MANIM_BODY"

_ALLOWED_TYPES = {
    "title_scene",
    "question_scene",
    "concept_scene",
    "process_scene",
    "comparison_scene",
    "custom_manim_scene",
}
_ALLOWED_ROLES = {
    "intuition",
    "definition",
    "problem",
    "formula",
    "example",
    "interpretation",
}
_ALLOWED_VISUAL_MODES = {
    "diagram",
    "graph",
    "motion",
    "comparison",
    "process",
    "text",
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
_FORBIDDEN_BODY_PATTERNS = (
    r"(^|\n)\s*(?:from|import)\s+",
    r"(^|\n)\s*class\s+",
    r"(^|\n)\s*def\s+",
    r"\b(?:open|exec|eval|compile|__import__)\s*\(",
    r"\b(?:os|sys|subprocess|pathlib|shutil|socket|requests|urllib)\b",
    r"\.svg\b|SVGMobject\s*\(",
    r"ImageMobject\s*\(",
    r"MathTex\s*\(|Tex\s*\(",
    r"random\.",
)


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2)


def _coerce_llm_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("content", "text", "message", "output"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return str(value or "")


def _short_text(value: Any, limit: int, default: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return default
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _normalize_math(value: Any, limit: int = 220) -> str:
    return _short_text(portable_math_text(value), limit, "")


def _looks_equation_like(value: Any) -> bool:
    """Return True only when text has strong signs of mathematical notation."""
    text = portable_math_text(value)
    if not text:
        return False
    if "=" in text or re.search(r"(?:<=|>=|!=)", text):
        return True
    if re.search(r"[A-Za-z0-9)]\s*[+*/^]\s*[A-Za-z0-9(]", text):
        return True
    if re.search(r"[A-Za-z0-9)]\s*-\s*(?:\d|[A-Za-z]\b|\()", text):
        return True
    if re.search(r"\b(?:sqrt|sin|cos|tan|log|ln)\s*\(", text, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"\b\d+(?:\.\d+)?\s*%", text))


def _normalize_step_text(value: Any, limit: int = 280) -> str:
    text = _short_text(value, limit, "")
    if not text:
        return ""
    return _normalize_math(text, limit) if _looks_equation_like(text) else text


def _math_to_speech(value: Any) -> str:
    text = portable_math_text(value)
    replacements = (
        ("+/-", " plus or minus "),
        (">=", " is greater than or equal to "),
        ("<=", " is less than or equal to "),
        ("!=", " is not equal to "),
        ("=", " equals "),
        ("*", " times "),
        ("/", " divided by "),
        ("+", " plus "),
        ("-", " minus "),
    )
    text = re.sub(r"\^2\b", " squared", text)
    text = re.sub(r"\^3\b", " cubed", text)
    text = re.sub(r"\^\s*([A-Za-z0-9.-]+)", r" to the power of \1", text)
    text = re.sub(r"\bsqrt\s*\(", "the square root of (", text, flags=re.IGNORECASE)
    for source, target in replacements:
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def _strip_sequence_prefix(value: str) -> str:
    return re.sub(
        r"^\s*(?:first|firstly|next|then|after that|finally|lastly)\s*[:,.-]?\s*",
        "",
        str(value or ""),
        flags=re.IGNORECASE,
    ).strip()


def _fallback_step_narration(step_text: str, index: int, total: int) -> str:
    spoken = _math_to_speech(step_text) if _looks_equation_like(step_text) else _short_text(step_text, 420, "")
    spoken = _strip_sequence_prefix(spoken).rstrip(" .")
    if not spoken:
        spoken = "Notice what changes in this step"
    if total <= 1:
        return spoken + "."
    if index <= 0:
        prefix = "First"
    elif index >= total - 1:
        prefix = "Finally"
    else:
        prefix = "Next"
    return f"{prefix}: {spoken}."


def _estimate_speech_seconds(value: Any, words_per_minute: float = 140.0) -> float:
    words = re.findall(r"[A-Za-z0-9']+", str(value or ""))
    if not words:
        return 0.0
    return max(1.2, len(words) * 60.0 / max(80.0, words_per_minute))


def _minimum_sequence_duration(
    narration: str,
    step_narrations: list[str],
    *,
    has_formula: bool,
) -> float:
    """Estimate subtitle metadata duration for the deterministic sequence renderer."""
    intro_animation = 0.75 if has_formula else 0.55
    intro = max(intro_animation, _estimate_speech_seconds(narration))
    steps = sum(
        max(0.65, _estimate_speech_seconds(step_narration)) + 0.75
        for step_narration in step_narrations
    )
    return 0.4 + intro + steps + 0.75 + 3.0 + 0.6


def _normalize_string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value[:limit]:
        text = _short_text(item, item_limit, "")
        if text and text.lower() not in {existing.lower() for existing in output}:
            output.append(text)
    return output


def _normalize_labels(value: Any) -> list[str]:
    labels = _normalize_string_list(value, limit=5, item_limit=44)
    return [
        label
        for label in labels
        if re.sub(r"[^a-z0-9]+", " ", label.lower()).strip() not in _GENERIC_LABELS
    ]


def _json_object_candidate(raw: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("The model did not return a complete JSON video plan.")
    return text[start : end + 1]


def _remove_trailing_json_commas(text: str) -> str:
    """Remove commas immediately before } or ] while respecting JSON strings."""
    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue

        output.append(char)
        index += 1
    return "".join(output)


def _previous_nonspace_index(text: str, start: int) -> int:
    index = min(start, len(text) - 1)
    while index >= 0 and text[index].isspace():
        index -= 1
    return index


def _next_nonspace_index(text: str, start: int) -> int:
    index = max(0, start)
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _is_json_value_end(text: str, index: int) -> bool:
    if index < 0:
        return False
    char = text[index]
    if char in '"}]' or char.isdigit():
        return True
    prefix = text[: index + 1].rstrip()
    return prefix.endswith(("true", "false", "null"))


def _is_json_value_start(char: str) -> bool:
    return bool(char) and (char in '"{[-' or char.isdigit() or char in "tfn")


def _repair_json_punctuation(candidate: str, max_edits: int = 12) -> str:
    """Repair only conservative punctuation mistakes; never rewrite values or keys."""
    repaired = _remove_trailing_json_commas(candidate)
    for _ in range(max_edits):
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ',' delimiter":
                break

            current = _next_nonspace_index(repaired, exc.pos)
            previous = _previous_nonspace_index(repaired, current - 1)
            if (
                current >= len(repaired)
                or not _is_json_value_start(repaired[current])
                or not _is_json_value_end(repaired, previous)
            ):
                break
            repaired = repaired[:current] + "," + repaired[current:]
    return repaired


def _extract_json_object_with_local_repair(raw: str) -> tuple[dict[str, Any], str, bool]:
    candidate = _json_object_candidate(raw)
    try:
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise RuntimeError("The structured video plan must be a JSON object.")
        return parsed, candidate, False
    except json.JSONDecodeError as original_error:
        repaired = _repair_json_punctuation(candidate)
        if repaired != candidate:
            try:
                parsed = json.loads(repaired)
                if not isinstance(parsed, dict):
                    raise RuntimeError("The structured video plan must be a JSON object.")
                logger.warning(
                    "structured_video_json_repaired_locally original_error=%s",
                    original_error,
                )
                return parsed, repaired, True
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"The model returned malformed JSON: {original_error}") from original_error


def _extract_json_object(raw: str) -> dict[str, Any]:
    parsed, _json_text, _was_repaired = _extract_json_object_with_local_repair(raw)
    return parsed

def _clean_body_block(body: str) -> str:
    """Normalize transport indentation without rewriting model-authored Python."""
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    text = text.strip("\n")
    text = re.sub(r"^[ \t]*```(?:python)?[ \t]*(?:\n)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:\n)?[ \t]*```[ \t]*$", "", text)
    return textwrap.dedent(text).strip()


def _extract_tagged_section(text: str, tag: str) -> str | None:
    """Extract one fully closed tagged section. Retained for legacy VIDEO_PLAN JSON."""
    pattern = re.compile(
        rf"<{re.escape(tag)}\s*>\s*(.*?)\s*</{re.escape(tag)}\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(str(text or ""))
    return match.group(1).strip() if match else None


def _extract_tagged_blocks(
    text: str,
    tag: str,
    *,
    stop_tags: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    """Extract blocks independently and salvage a block whose closing tag is omitted.

    The body ends at its closing tag, the next block of the same type, or an explicit stop tag.
    This makes one malformed scene unable to invalidate earlier complete scenes.
    """
    source = str(text or "")
    opening = re.compile(rf"<{re.escape(tag)}\b(?P<attrs>[^>]*)>", re.IGNORECASE)
    starts = list(opening.finditer(source))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(starts):
        content_start = match.end()
        boundary = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        for stop_tag in stop_tags:
            stop = re.search(
                rf"<{re.escape(stop_tag)}\b",
                source[content_start:boundary],
                flags=re.IGNORECASE,
            )
            if stop:
                boundary = min(boundary, content_start + stop.start())

        closing = re.search(
            rf"</{re.escape(tag)}\s*>",
            source[content_start:boundary],
            flags=re.IGNORECASE,
        )
        content_end = content_start + closing.start() if closing else boundary
        body = source[content_start:content_end].strip()
        if body:
            blocks.append((match.group("attrs") or "", body))
    return blocks


def _tag_field_values(block: str, tag: str) -> list[str]:
    """Read repeated field tags with line-oriented fallbacks for minor model mistakes."""
    source = str(block or "")
    pattern = re.compile(
        rf"<{re.escape(tag)}\s*>\s*(.*?)\s*</{re.escape(tag)}\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    values = [html.unescape(match.group(1).strip()) for match in pattern.finditer(source)]
    if values:
        return [value for value in values if value]

    # Accept TAG: value when a model forgets the XML-like wrapper.
    line_pattern = re.compile(
        rf"^\s*{re.escape(tag)}\s*:\s*(.+?)\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    values = [html.unescape(match.group(1).strip()) for match in line_pattern.finditer(source)]
    if values:
        return [value for value in values if value]

    # Accept a one-line opening tag without its closing partner.
    open_line_pattern = re.compile(
        rf"<{re.escape(tag)}\s*>\s*([^\r\n<]+)",
        flags=re.IGNORECASE,
    )
    return [
        html.unescape(match.group(1).strip())
        for match in open_line_pattern.finditer(source)
        if match.group(1).strip()
    ]


def _first_tag_field(block: str, tag: str, default: str = "") -> str:
    values = _tag_field_values(block, tag)
    return values[0] if values else default


def _tagged_step_pairs(block: str) -> tuple[list[str], list[str]]:
    """Preserve STEP_TEXT/STEP_NARRATION pairing even when one narration is omitted."""
    token_pattern = re.compile(
        r"<(STEP_TEXT|CALCULATION_STEP|STEP_NARRATION)\s*>\s*(.*?)\s*</\1\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    steps: list[str] = []
    narrations: list[str] = []
    for match in token_pattern.finditer(str(block or "")):
        tag_name = match.group(1).upper()
        value = html.unescape(match.group(2).strip())
        if not value:
            continue
        if tag_name in {"STEP_TEXT", "CALCULATION_STEP"}:
            steps.append(value)
            narrations.append("")
        elif steps:
            for index in range(len(narrations) - 1, -1, -1):
                if not narrations[index]:
                    narrations[index] = value
                    break

    if steps:
        return steps, narrations

    generic_steps = _tag_field_values(block, "STEP_TEXT")
    legacy_steps = _tag_field_values(block, "CALCULATION_STEP")
    steps = generic_steps or legacy_steps
    flat_narrations = _tag_field_values(block, "STEP_NARRATION")
    narrations = [
        flat_narrations[index] if index < len(flat_narrations) else ""
        for index in range(len(steps))
    ]
    return steps, narrations


def _attribute_value(attrs: str, name: str) -> str:
    match = re.search(
        rf"\b{re.escape(name)}\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
        str(attrs or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return html.unescape(next((group for group in match.groups() if group), "").strip())


def _parse_tagged_video_plan(text: str) -> tuple[dict[str, Any], str] | None:
    """Parse the model-facing tagged plan without any JSON dependency."""
    source = str(text or "").strip()
    scene_blocks = _extract_tagged_blocks(
        source,
        _SCENE_PLAN_TAG,
        stop_tags=(_MANIM_BODY_TAG,),
    )
    if not scene_blocks:
        return None

    meta_blocks = _extract_tagged_blocks(
        source,
        _VIDEO_META_TAG,
        stop_tags=(_SCENE_PLAN_TAG, _MANIM_BODY_TAG),
    )
    meta = meta_blocks[0][1] if meta_blocks else ""
    plan: dict[str, Any] = {
        "title": _first_tag_field(meta, "TITLE"),
        "subtitle": _first_tag_field(meta, "SUBTITLE"),
        "audience": _first_tag_field(meta, "AUDIENCE"),
        "scenes": [],
    }

    scalar_fields = {
        "type": "TYPE",
        "learning_role": "LEARNING_ROLE",
        "learner_question": "LEARNER_QUESTION",
        "visual_mode": "VISUAL_MODE",
        "title": "TITLE",
        "subtitle": "SUBTITLE",
        "narration": "NARRATION",
        "visual": "VISUAL",
        "formula": "FORMULA",
        "duration_sec": "DURATION_SEC",
        "code_goal": "CODE_GOAL",
        "manim_body_ref": "MANIM_BODY_REF",
    }
    list_fields = {
        "required_visual_elements": "REQUIRED_VISUAL_ELEMENT",
        "labels": "LABEL",
    }

    for index, (attrs, block) in enumerate(scene_blocks, start=1):
        scene: dict[str, Any] = {
            "id": _attribute_value(attrs, "id") or _first_tag_field(block, "ID") or index,
        }
        for key, tag_name in scalar_fields.items():
            value = _first_tag_field(block, tag_name)
            if value:
                scene[key] = value
        for key, tag_name in list_fields.items():
            values = _tag_field_values(block, tag_name)
            if values:
                scene[key] = values

        parsed_steps, parsed_step_narrations = _tagged_step_pairs(block)
        if parsed_steps:
            scene["steps"] = parsed_steps
            scene["step_narrations"] = parsed_step_narrations

        # Ignore an empty accidental SCENE_PLAN shell while keeping every usable partial scene.
        if len(scene) > 1:
            plan["scenes"].append(scene)

    if not plan["scenes"]:
        return None

    body_start = re.search(r"<MANIM_BODY\b", source, flags=re.IGNORECASE)
    transport_text = source[: body_start.start()].strip() if body_start else source
    return plan, transport_text


def _extract_manim_body_sections(text: str) -> dict[str, str]:
    pattern = re.compile(
        r"<MANIM_BODY\b(?P<attrs>[^>]*)>(?P<body>.*?)</MANIM_BODY\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    bodies: dict[str, str] = {}
    for match in pattern.finditer(str(text or "")):
        attrs = match.group("attrs")
        id_match = re.search(
            r"\bid\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
            attrs,
            flags=re.IGNORECASE,
        )
        if not id_match:
            continue
        ref = next((group for group in id_match.groups() if group), "").strip()
        body = _clean_body_block(match.group("body"))
        if ref and body:
            bodies[ref] = body
    return bodies


def _body_ref_for_scene(scene: dict[str, Any], index: int) -> str:
    existing = str(scene.get("manim_body_ref") or "").strip()
    if existing:
        return existing
    scene_id = str(scene.get("id") or index).strip()
    return f"scene_{scene_id}"


def _attach_manim_bodies(
    plan: dict[str, Any],
    bodies: dict[str, str],
) -> dict[str, Any]:
    scenes = plan.get("scenes")
    if not isinstance(scenes, list):
        return plan
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        if scene.get("type") == "custom_manim_scene" or scene.get("manim_body_ref"):
            ref = _body_ref_for_scene(scene, index)
            scene["manim_body_ref"] = ref
            scene_id = str(scene.get("id") or "").strip()
            candidates = [ref, f"scene_{scene_id}" if scene_id else "", scene_id, f"scene_{index}"]
            matched = next((candidate for candidate in candidates if candidate and candidate in bodies), None)
            if matched:
                scene["manim_body"] = bodies[matched]
    return plan


def _parse_structured_response(
    raw: str,
) -> tuple[dict[str, Any], dict[str, str], str, str | None, bool]:
    text = str(raw or "").strip()
    bodies = _extract_manim_body_sections(text)

    tagged = _parse_tagged_video_plan(text)
    if tagged is not None:
        parsed, transport_text = tagged
        return parsed, bodies, transport_text, None, False

    # Backward compatibility for older providers, saved responses, and existing tests that
    # still use one JSON VIDEO_PLAN object.
    plan_text = _extract_tagged_section(text, _VIDEO_PLAN_TAG)
    source_plan_text = text if plan_text is None else plan_text
    parsed, parsed_plan_text, was_repaired = _extract_json_object_with_local_repair(source_plan_text)
    repaired_plan_text = parsed_plan_text if was_repaired else None
    return parsed, bodies, source_plan_text, repaired_plan_text, was_repaired


def _split_plan_and_bodies(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    cloned = json.loads(json.dumps(plan or {}, ensure_ascii=False))
    bodies: dict[str, str] = {}
    scenes = cloned.get("scenes")
    if not isinstance(scenes, list):
        return cloned, bodies
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        body = _clean_body_block(scene.pop("manim_body", ""))
        if scene.get("type") == "custom_manim_scene" or body:
            ref = _body_ref_for_scene(scene, index)
            scene["manim_body_ref"] = ref
            if body:
                bodies[ref] = body
    return cloned, bodies


def _write_response_debug_artifacts(
    *,
    logs_dir: pathlib.Path,
    prefix: str,
    raw_text: str,
    plan_text: str,
    bodies: dict[str, str],
    repaired_plan_text: str | None = None,
    plan_was_repaired: bool = False,
) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{prefix}_response_raw.txt").write_text(raw_text, encoding="utf-8")
    (logs_dir / f"{prefix}_plan_transport.txt").write_text(plan_text, encoding="utf-8")
    # Preserve the old debug filename only when the transport really is legacy JSON.
    try:
        json.loads(_json_object_candidate(plan_text))
    except Exception:
        pass
    else:
        (logs_dir / f"{prefix}_plan_raw.json").write_text(plan_text, encoding="utf-8")
    if plan_was_repaired and repaired_plan_text is not None:
        (logs_dir / f"{prefix}_plan_repaired.json").write_text(
            repaired_plan_text,
            encoding="utf-8",
        )
    body_parts: list[str] = []
    for ref, body in bodies.items():
        body_parts.extend([f'<MANIM_BODY id="{ref}">', body, "</MANIM_BODY>", ""])
        safe_ref = re.sub(r"[^A-Za-z0-9_.-]+", "_", ref).strip("_") or "scene"
        (logs_dir / f"{prefix}_{safe_ref}.py").write_text(body + "\n", encoding="utf-8")
    (logs_dir / f"{prefix}_creative_bodies_raw.txt").write_text(
        "\n".join(body_parts), encoding="utf-8"
    )


def _normalize_plan(plan: dict[str, Any], *, topic: str) -> dict[str, Any]:
    title = _short_text(plan.get("title"), 72, _short_text(topic, 72, "Educational video"))
    subtitle = _short_text(plan.get("subtitle"), 100, "")
    audience = _short_text(plan.get("audience"), 60, "general learners")
    incoming_scenes = plan.get("scenes")
    if not isinstance(incoming_scenes, list) or not incoming_scenes:
        raise RuntimeError("The model returned no video scenes.")

    scenes: list[dict[str, Any]] = []
    for index, incoming in enumerate(incoming_scenes[:10], start=1):
        if not isinstance(incoming, dict):
            continue

        scene_type = str(incoming.get("type") or incoming.get("kind") or "concept_scene").strip().lower()
        aliases = {
            "title": "title_scene",
            "question": "question_scene",
            "concept": "concept_scene",
            "process": "process_scene",
            "comparison": "comparison_scene",
            "custom": "custom_manim_scene",
            "creative": "custom_manim_scene",
            "graph": "custom_manim_scene",
            "graph_scene": "custom_manim_scene",
        }
        scene_type = aliases.get(scene_type, scene_type)
        if scene_type not in _ALLOWED_TYPES:
            scene_type = "concept_scene"

        learning_role = str(incoming.get("learning_role") or "").strip().lower()
        if learning_role not in _ALLOWED_ROLES:
            learning_role = "intuition" if index == 2 else "interpretation"

        visual_mode = str(incoming.get("visual_mode") or "").strip().lower()
        if visual_mode not in _ALLOWED_VISUAL_MODES:
            visual_mode = "text" if scene_type != "custom_manim_scene" else "motion"

        # A requested graph can never be silently treated as a standard component.
        if visual_mode == "graph":
            scene_type = "custom_manim_scene"

        scene_title = _short_text(incoming.get("title") or incoming.get("heading"), 68, f"{title} {index}")
        scene_subtitle = _short_text(incoming.get("subtitle"), 100, "")
        narration = _short_text(incoming.get("narration"), 900, scene_title)
        visual = _short_text(incoming.get("visual") or incoming.get("visual_goal"), 240, "")
        learner_question = _short_text(incoming.get("learner_question"), 180, "")
        required_elements = _normalize_string_list(
            incoming.get("required_visual_elements"), limit=6, item_limit=64
        )
        labels = _normalize_labels(incoming.get("labels"))
        formula = _normalize_math(incoming.get("formula") or incoming.get("equation"), 220)
        raw_steps = (
            incoming.get("steps")
            or incoming.get("calculation_steps")
            or incoming.get("worked_steps")
        )
        steps = [
            _normalize_step_text(step, 280)
            for step in _normalize_string_list(raw_steps, limit=6, item_limit=300)
        ]
        steps = [step for step in steps if step]
        raw_step_narrations = incoming.get("step_narrations")
        provided_step_narrations = (
            [
                _short_text(value, 460, "")
                for value in raw_step_narrations[:6]
            ]
            if isinstance(raw_step_narrations, list)
            else []
        )
        step_narrations = [
            provided_step_narrations[index]
            if index < len(provided_step_narrations) and provided_step_narrations[index]
            else _fallback_step_narration(step, index, len(steps))
            for index, step in enumerate(steps)
        ]

        try:
            duration = float(incoming.get("duration_sec") or 10)
        except Exception:
            duration = 10.0
        duration = max(4.0, min(90.0, duration))
        if steps:
            duration = max(
                duration,
                min(90.0, _minimum_sequence_duration(
                    narration, step_narrations, has_formula=bool(formula)
                )),
            )

        scene: dict[str, Any] = {
            "id": incoming.get("id") or index,
            "type": scene_type,
            "learning_role": learning_role,
            "learner_question": learner_question,
            "visual_mode": visual_mode,
            "title": scene_title,
            "subtitle": scene_subtitle,
            "narration": narration,
            "visual": visual,
            "required_visual_elements": required_elements,
            "labels": labels,
            "duration_sec": duration,
        }
        if formula:
            scene["formula"] = formula
        if steps:
            scene["steps"] = steps
            scene["step_narrations"] = step_narrations
        if scene_type == "custom_manim_scene":
            scene["code_goal"] = _short_text(incoming.get("code_goal") or visual, 240, visual)
            scene["manim_body_ref"] = _body_ref_for_scene(incoming, index)
            scene["manim_body"] = _clean_body_block(incoming.get("manim_body") or "")
        scenes.append(scene)

    if not scenes:
        raise RuntimeError("The model returned no usable video scenes.")

    scenes[0]["type"] = "title_scene"
    scenes[0]["visual_mode"] = "text"
    scenes[0].pop("manim_body", None)
    scenes[0].pop("manim_body_ref", None)
    scenes[0].pop("code_goal", None)

    return {
        "title": title,
        "subtitle": subtitle,
        "audience": audience,
        "scenes": scenes,
    }


def _looks_like_instruction_instead_of_math(step: str) -> bool:
    lowered = step.lower().strip()
    imperative = (
        "compute ",
        "calculate ",
        "solve ",
        "show ",
        "substitute the values",
        "simplify the expression",
        "find the answer",
        "mark the roots",
    )
    return any(lowered.startswith(prefix) for prefix in imperative) and "=" not in step


def _plan_quality_errors(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scenes = plan.get("scenes") or []
    if not scenes or scenes[0].get("type") != "title_scene":
        errors.append("Scene 1 must be title_scene.")

    for index, scene in enumerate(scenes, start=1):
        role = str(scene.get("learning_role") or "")
        mode = str(scene.get("visual_mode") or "")
        scene_type = str(scene.get("type") or "")
        body = str(scene.get("manim_body") or "").strip()
        formula = str(scene.get("formula") or "").strip()
        steps = [str(x) for x in (scene.get("steps") or scene.get("calculation_steps") or []) if str(x).strip()]

        if scene_type == "custom_manim_scene" and not body:
            errors.append(f"Scene {index}: custom_manim_scene is missing manim_body.")

        if mode == "graph":
            if scene_type != "custom_manim_scene":
                errors.append(f"Scene {index}: visual_mode=graph must use custom_manim_scene.")
            if not scene.get("required_visual_elements"):
                errors.append(f"Scene {index}: graph scene needs required_visual_elements.")

        if role == "example" and formula:
            if len(steps) < 3:
                errors.append(
                    f"Scene {index}: worked formula example needs at least three explicit STEP_TEXT values: substitution, simplification, and final answer."
                )
            else:
                if sum("=" in step for step in steps) < 2:
                    errors.append(f"Scene {index}: worked math STEP_TEXT values must show actual equations, not only prose.")
                if any(_looks_like_instruction_instead_of_math(step) for step in steps):
                    errors.append(f"Scene {index}: replace calculation instructions with the completed math.")
                if "=" not in steps[-1] and not any(word in steps[-1].lower() for word in ("answer", "therefore", "so ")):
                    errors.append(f"Scene {index}: final worked-math STEP_TEXT must state the answer explicitly.")

    return errors


def _topic_requires_explicit_worked_math(topic: str) -> bool:
    lowered = str(topic or "").lower()
    markers = (
        "solve",
        "calculate",
        "calculation",
        "worked example",
        "work an example",
        "derive",
        "find the value",
        "find x",
        "show the steps",
    )
    return any(marker in lowered for marker in markers)


def _apply_local_plan_quality_fixes(plan: dict[str, Any], *, topic: str) -> list[str]:
    """Repair safe structural omissions locally before considering another model call."""
    fixes: list[str] = []
    scenes = plan.get("scenes")
    if not isinstance(scenes, list):
        return fixes

    requires_worked_math = _topic_requires_explicit_worked_math(topic)
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        scene_type = str(scene.get("type") or "")
        visual_mode = str(scene.get("visual_mode") or "")
        body = str(scene.get("manim_body") or "").strip()

        if visual_mode == "graph" and not scene.get("required_visual_elements"):
            inferred = _short_text(
                scene.get("visual") or scene.get("learner_question") or scene.get("title"),
                64,
                "important graph feature",
            )
            scene["required_visual_elements"] = [inferred]
            fixes.append(f"Scene {index}: inferred a required graph feature locally.")

        # A non-graph custom scene without code can safely become a deterministic component
        # scene. This avoids a whole-plan repair call for an optional creative flourish.
        if scene_type == "custom_manim_scene" and not body and visual_mode != "graph":
            scene["type"] = "concept_scene"
            if visual_mode not in {"diagram", "comparison", "process", "text"}:
                scene["visual_mode"] = "diagram"
            scene.pop("manim_body", None)
            scene.pop("manim_body_ref", None)
            scene.pop("code_goal", None)
            fixes.append(
                f"Scene {index}: converted a code-less optional custom scene to a deterministic concept scene."
            )

        formula = str(scene.get("formula") or "").strip()
        steps = [str(value) for value in (scene.get("steps") or scene.get("calculation_steps") or []) if str(value).strip()]
        weak_example = (
            str(scene.get("learning_role") or "") == "example"
            and formula
            and (
                len(steps) < 3
                or sum("=" in step for step in steps) < 2
                or any(_looks_like_instruction_instead_of_math(step) for step in steps)
            )
        )
        # For a broad explanation, preserve the useful formula scene but stop pretending it is
        # a completed worked example. Explicit solve/calculate requests remain eligible for one
        # focused plan repair call.
        if weak_example and not requires_worked_math:
            scene["learning_role"] = "formula"
            fixes.append(
                f"Scene {index}: reclassified an incomplete optional example as a formula explanation."
            )

    return fixes


def _repair_plan_if_needed(
    plan: dict[str, Any],
    *,
    topic: str,
    provider_name: str,
    api_key: str,
    model: str | None,
    logs_dir: pathlib.Path,
) -> tuple[dict[str, Any], bool]:
    local_fixes = _apply_local_plan_quality_fixes(plan, topic=topic)
    if local_fixes:
        (logs_dir / "plan_local_fixes.json").write_text(
            _safe_json(local_fixes), encoding="utf-8"
        )
        logger.info("structured_video_plan_local_fixes fixes=%s", local_fixes)

    errors = _plan_quality_errors(plan)
    if not errors:
        return plan, bool(local_fixes)

    # Only essential teaching failures remain here: usually a required graph with no usable
    # custom body, or an explicitly requested worked calculation with incomplete math. One
    # focused repair call is allowed; ordinary missing fields were already handled locally.
    (logs_dir / "plan_quality_errors.json").write_text(_safe_json(errors), encoding="utf-8")
    logger.warning("structured_video_plan_repair errors=%s", errors)
    raw = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_PLAN_REPAIR_SYSTEM,
        user=build_structured_video_plan_repair_prompt(plan=plan, errors=errors),
        temperature=0.08,
        max_tokens=6200,
    )
    raw_text = _coerce_llm_text(raw)
    (logs_dir / "plan_repair_response_raw.txt").write_text(raw_text, encoding="utf-8")
    parsed, bodies, plan_text, repaired_plan_text, plan_was_repaired = _parse_structured_response(raw_text)
    _write_response_debug_artifacts(
        logs_dir=logs_dir,
        prefix="plan_repair",
        raw_text=raw_text,
        plan_text=plan_text,
        bodies=bodies,
        repaired_plan_text=repaired_plan_text,
        plan_was_repaired=plan_was_repaired,
    )
    parsed = _attach_manim_bodies(parsed, bodies)
    parsed = _inherit_missing_scene_fields(parsed, plan)
    repaired = _normalize_plan(parsed, topic=topic)
    second_local_fixes = _apply_local_plan_quality_fixes(repaired, topic=topic)
    if second_local_fixes:
        (logs_dir / "plan_repair_local_fixes.json").write_text(
            _safe_json(second_local_fixes), encoding="utf-8"
        )
    remaining = _plan_quality_errors(repaired)
    if remaining:
        (logs_dir / "plan_repair_remaining_errors.json").write_text(
            _safe_json(remaining), encoding="utf-8"
        )
        raise RuntimeError(
            "The model could not produce the required graph or worked math example: "
            + "; ".join(remaining)
        )
    return repaired, True


def _extract_body(raw: Any) -> str:
    return _clean_body_block(_coerce_llm_text(raw))


def _validate_custom_body(body: str, scene: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cleaned = _clean_body_block(body)
    if not cleaned:
        return ["manim_body is empty."]

    for pattern in _FORBIDDEN_BODY_PATTERNS:
        if re.search(pattern, cleaned, flags=re.IGNORECASE | re.MULTILINE):
            errors.append(f"Forbidden custom-code pattern: {pattern}")

    if cleaned.count("self.voiceover") < 1:
        errors.append("Custom scene needs at least 1 self.voiceover block.")
    animation_actions = (
        cleaned.count("self.play")
        + cleaned.count("next_calculation_step(")
        + cleaned.count("add_instruction_step(")
    )
    if animation_actions < 3:
        errors.append("Custom scene needs at least 3 visible animation actions.")

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
        "next_calculation_step(",
    )
    if not any(marker in cleaned for marker in motion_markers):
        errors.append("Custom scene needs meaningful movement or transformation.")

    formula = str(scene.get("formula") or "").strip()
    if formula and "formula" not in cleaned and formula not in cleaned:
        errors.append("The formula field is not displayed. Use formula_label(formula) or mn.Text(formula).")

    if str(scene.get("visual_mode") or "") == "graph":
        if "mn.Axes(" not in cleaned and "mn.NumberPlane(" not in cleaned:
            errors.append("Graph scene must create mn.Axes or mn.NumberPlane.")
        graph_markers = (".plot(", ".plot_line_graph(", ".c2p(", "mn.ParametricFunction(", "mn.FunctionGraph(")
        if not any(marker in cleaned for marker in graph_markers):
            errors.append("Graph scene must plot or draw a coordinate-based relationship.")
        feature_markers = ("mn.Dot(", "mn.DashedLine(", "mn.Line(", "mn.Arrow(", "label(", "formula_label(")
        if not any(marker in cleaned for marker in feature_markers):
            errors.append("Graph scene must visibly mark the graph feature discussed in narration.")

    scene_steps = scene.get("steps") or scene.get("calculation_steps") or []
    if str(scene.get("learning_role") or "") == "example" and scene_steps:
        if (
            "steps" not in cleaned
            and "calculation_steps" not in cleaned
            and "instruction_step_label(" not in cleaned
            and "calculation_step_label(" not in cleaned
            and "add_instruction_step(" not in cleaned
            and "next_calculation_step(" not in cleaned
        ):
            errors.append("Worked example must visibly animate its instructional steps.")

    try:
        ast.parse("def _scene_body():\n" + "\n".join("    " + line for line in cleaned.splitlines()))
    except SyntaxError as exc:
        errors.append(f"Python syntax error: {exc.msg} at line {exc.lineno}.")

    return errors


def _video_url_to_path(video_url: str) -> pathlib.Path:
    value = str(video_url or "")
    if value.startswith("/static/"):
        return pathlib.Path(STORAGE) / value[len("/static/") :]
    candidate = pathlib.Path(value)
    if candidate.is_absolute():
        return candidate
    return pathlib.Path(STORAGE) / value.lstrip("/")


def _render_code_once(
    *,
    code: str,
    scene_job_id: str,
) -> tuple[pathlib.Path | None, dict[str, Any], str]:
    safe_code = sanitize_minimally(code).strip() + "\n"
    result = run_job_from_code(
        safe_code,
        job_id=scene_job_id,
        timeout_seconds=240,
        inject_watermark=False,
    )
    if result.get("ok") and result.get("video_url"):
        path = _video_url_to_path(str(result["video_url"]))
        if path.exists():
            return path, result, ""
    detail = str(
        result.get("error_log")
        or result.get("compile_log")
        or result.get("error")
        or "Manim render failed."
    )
    return None, result, detail


def _render_scene_clip(
    *,
    scene: dict[str, Any],
    final_job_id: str,
    scene_index: int,
    provider_name: str,
    api_key: str,
    model: str | None,
    logs_dir: pathlib.Path,
) -> tuple[pathlib.Path, dict[str, Any], str]:
    scene_job_id = f"{final_job_id}-scene-{scene_index:02d}"
    scene_log_prefix = logs_dir / f"scene_{scene_index:02d}"
    is_custom = scene.get("type") == "custom_manim_scene"

    if not is_custom:
        code = build_component_scene_code(scene)
        (scene_log_prefix.with_suffix(".py")).write_text(code, encoding="utf-8")
        clip, result, detail = _render_code_once(code=code, scene_job_id=scene_job_id)
        if clip is None:
            raise RuntimeError(f"Standard scene {scene_index} failed to render: {detail}")
        return clip, {
            "scene_index": scene_index,
            "scene_type": scene.get("type"),
            "used_fallback": False,
            "job_id": result.get("job_id"),
        }, code

    original_body = _clean_body_block(scene.get("manim_body") or "")
    validation_errors = _validate_custom_body(original_body, scene)
    initial_detail = "; ".join(validation_errors)
    if not validation_errors:
        initial_code = build_custom_scene_code(scene, original_body)
        (logs_dir / f"scene_{scene_index:02d}_initial.py").write_text(initial_code, encoding="utf-8")
        clip, result, render_detail = _render_code_once(code=initial_code, scene_job_id=scene_job_id)
        if clip is not None:
            return clip, {
                "scene_index": scene_index,
                "scene_type": scene.get("type"),
                "render_source": "custom_initial",
                "used_fallback": False,
                "job_id": result.get("job_id"),
            }, initial_code
        initial_detail = render_detail
        failure_stage = "render"
    else:
        failure_stage = "static_validation"

    logger.warning(
        "custom_scene_repair_start scene=%s stage=%s detail=%s",
        scene_index,
        failure_stage,
        initial_detail,
    )
    repair_raw = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM,
        user=build_structured_video_creative_repair_prompt(
            scene=scene,
            original_body=original_body,
            failure_stage=failure_stage,
            error_detail=initial_detail[:3000],
        ),
        temperature=0.12,
        max_tokens=4200,
    )
    repaired_body = _extract_body(repair_raw)
    (logs_dir / f"scene_{scene_index:02d}_repair_raw.py").write_text(repaired_body, encoding="utf-8")
    repaired_errors = _validate_custom_body(repaired_body, scene)
    repair_detail = "; ".join(repaired_errors)
    if not repaired_errors:
        repaired_code = build_custom_scene_code(scene, repaired_body)
        (logs_dir / f"scene_{scene_index:02d}_repaired.py").write_text(repaired_code, encoding="utf-8")
        repaired_job_id = f"{scene_job_id}-repair"
        clip, result, render_detail = _render_code_once(code=repaired_code, scene_job_id=repaired_job_id)
        if clip is not None:
            scene["manim_body"] = repaired_body
            return clip, {
                "scene_index": scene_index,
                "scene_type": scene.get("type"),
                "render_source": "custom_repaired",
                "used_fallback": False,
                "job_id": result.get("job_id"),
                "initial_failure": initial_detail[:1200],
            }, repaired_code
        repair_detail = render_detail

    # A graph is an essential teaching visual. Never replace it with a generic card.
    if str(scene.get("visual_mode") or "") == "graph":
        raise RuntimeError(
            f"Required graph scene {scene_index} could not be rendered after one repair. "
            f"Initial failure: {initial_detail}. Repair failure: {repair_detail}"
        )

    fallback_code = build_concept_fallback_scene_code(scene)
    (logs_dir / f"scene_{scene_index:02d}_fallback.py").write_text(fallback_code, encoding="utf-8")
    fallback_job_id = f"{scene_job_id}-fallback"
    clip, result, fallback_detail = _render_code_once(code=fallback_code, scene_job_id=fallback_job_id)
    if clip is None:
        raise RuntimeError(
            f"Scene {scene_index} custom render and fallback both failed. "
            f"Custom: {initial_detail}; repair: {repair_detail}; fallback: {fallback_detail}"
        )
    return clip, {
        "scene_index": scene_index,
        "scene_type": scene.get("type"),
        "render_source": "concept_fallback",
        "used_fallback": True,
        "job_id": result.get("job_id"),
        "initial_failure": initial_detail[:1200],
        "repair_failure": repair_detail[:1200],
    }, fallback_code


def _find_ffmpeg() -> str:
    for name in ("UPCURVED_FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"):
        candidate = str(os.getenv(name) or "").strip()
        if candidate and pathlib.Path(candidate).exists():
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg not found. Set UPCURVED_FFMPEG_PATH or install ffmpeg.")


def _write_process_logs(prefix: pathlib.Path, cmd: list[str], completed: subprocess.CompletedProcess[str]) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    (prefix.with_name(prefix.name + "_cmd.txt")).write_text(" ".join(cmd), encoding="utf-8")
    (prefix.with_name(prefix.name + "_stdout.txt")).write_text(completed.stdout or "", encoding="utf-8")
    (prefix.with_name(prefix.name + "_stderr.txt")).write_text(completed.stderr or "", encoding="utf-8")


def _concat_clips(clips: list[pathlib.Path], final_mp4: pathlib.Path, logs_dir: pathlib.Path) -> None:
    if not clips:
        raise RuntimeError("No rendered scene clips were produced.")
    ffmpeg = _find_ffmpeg()
    concat_file = logs_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for path in clips) + "\n",
        encoding="utf-8",
    )
    copy_cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(final_mp4),
    ]
    copied = subprocess.run(copy_cmd, capture_output=True, text=True)
    _write_process_logs(logs_dir / "concat_copy", copy_cmd, copied)
    if copied.returncode == 0 and final_mp4.exists():
        return

    reencode_cmd = [
        ffmpeg,
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
    encoded = subprocess.run(reencode_cmd, capture_output=True, text=True)
    _write_process_logs(logs_dir / "concat_reencode", reencode_cmd, encoded)
    if encoded.returncode != 0 or not final_mp4.exists():
        detail = encoded.stderr or copied.stderr or "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg concat failed: {detail[-3000:]}")


def _apply_final_watermark(final_mp4: pathlib.Path, logs_dir: pathlib.Path) -> None:
    ffmpeg = _find_ffmpeg()
    watermarked = final_mp4.with_name("video_watermarked.mp4")
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
        ffmpeg,
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
        str(watermarked),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    _write_process_logs(logs_dir / "watermark", cmd, completed)
    if completed.returncode != 0 or not watermarked.exists():
        raise RuntimeError(f"ffmpeg watermark failed: {(completed.stderr or '')[-3000:]}")
    watermarked.replace(final_mp4)


def _format_vtt_ts(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _write_vtt_from_plan(plan: dict[str, Any], out_path: pathlib.Path) -> None:
    lines = ["WEBVTT", ""]
    cursor = 0.0
    for scene in plan.get("scenes") or []:
        duration = max(1.0, float(scene.get("duration_sec") or 8))
        start = _format_vtt_ts(cursor)
        end = _format_vtt_ts(cursor + duration)
        heading = _short_text(scene.get("title"), 80, "")
        narration = _short_text(scene.get("narration"), 180, "")
        caption = f"{heading}: {narration}" if heading and narration else narration or heading
        lines.extend([f"{start} --> {end}", caption[:180], ""])
        cursor += duration
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bundle_for_scene_code(plan: dict[str, Any], scene_codes: list[str], raw_plan: str) -> str:
    transport_plan, bodies = _split_plan_and_bodies(plan)
    parts = [
        "# Structured UpcurvEd Manim bundle v4",
        _PLAN_START,
        json.dumps(transport_plan, ensure_ascii=False, indent=2),
        _PLAN_END,
    ]
    for ref, body in bodies.items():
        parts.extend([
            f'<MANIM_BODY id="{ref}">',
            body.rstrip(),
            "</MANIM_BODY>",
        ])
    for index, code in enumerate(scene_codes, start=1):
        parts.extend([
            f"<<<SCENE_{index}_CODE>>>",
            code.rstrip(),
            f"<<<END_SCENE_{index}_CODE>>>",
        ])
    parts.extend([_RAW_PLAN_START, raw_plan.rstrip(), _RAW_PLAN_END, ""])
    return "\n".join(parts)


def is_structured_scene_bundle(text: str | None) -> bool:
    value = str(text or "")
    return _PLAN_START in value and _PLAN_END in value


def parse_plan_from_scene_bundle(bundle: str, topic: str = "Edited video") -> dict[str, Any]:
    text = str(bundle or "")
    start = text.find(_PLAN_START)
    end = text.find(_PLAN_END)
    if start < 0 or end <= start:
        raise RuntimeError("Original video is not a structured scene bundle; PLAN_JSON missing.")
    raw = text[start + len(_PLAN_START) : end].strip()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Original structured PLAN_JSON is invalid.")
    # v4 bundles store raw custom bodies outside PLAN_JSON; v3 embedded them.
    parsed = _attach_manim_bodies(parsed, _extract_manim_body_sections(text))
    return _normalize_plan(parsed, topic=topic)


def _inherit_missing_scene_fields(
    edited_plan: dict[str, Any],
    original_plan: dict[str, Any],
) -> dict[str, Any]:
    edited_scenes = edited_plan.get("scenes")
    original_scenes = original_plan.get("scenes")
    if not isinstance(edited_scenes, list) or not isinstance(original_scenes, list):
        return edited_plan
    originals_by_id = {
        str(scene.get("id")): scene
        for scene in original_scenes
        if isinstance(scene, dict) and scene.get("id") is not None
    }
    preserved_fields = (
        "formula",
        "steps",
        "step_narrations",
        "calculation_steps",
        "learning_role",
        "learner_question",
        "visual_mode",
        "required_visual_elements",
        "labels",
        "manim_body_ref",
    )
    for index, scene in enumerate(edited_scenes):
        if not isinstance(scene, dict):
            continue
        original = originals_by_id.get(str(scene.get("id")))
        if not isinstance(original, dict) and index < len(original_scenes):
            candidate = original_scenes[index]
            original = candidate if isinstance(candidate, dict) else None
        if not isinstance(original, dict):
            continue
        for field in preserved_fields:
            if field not in scene or scene.get(field) in (None, "", []):
                if original.get(field) not in (None, "", []):
                    scene[field] = original[field]
        scene_kind = str(scene.get("type") or scene.get("kind") or "").strip().lower()
        custom_like = (
            scene_kind in {"custom_manim_scene", "custom", "creative", "graph", "graph_scene"}
            or str(scene.get("visual_mode") or "").strip().lower() == "graph"
            or bool(scene.get("manim_body_ref"))
        )
        if custom_like and not str(scene.get("manim_body") or "").strip():
            body = _clean_body_block(original.get("manim_body") or "")
            if body:
                scene["manim_body"] = body
    return edited_plan


def _render_structured_plan(
    plan: dict[str, Any],
    *,
    provider_name: str,
    api_key: str,
    model: str | None,
    final_job_id: str,
    raw_plan: str,
    plan_repaired: bool,
) -> dict[str, Any]:
    job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
    logs_dir = job_dir / "logs"
    job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "structured_plan.json").write_text(_safe_json(plan), encoding="utf-8")

    clips: list[pathlib.Path] = []
    scene_results: list[dict[str, Any]] = []
    scene_codes: list[str] = []
    for index, scene in enumerate(plan.get("scenes") or [], start=1):
        clip, metadata, rendered_code = _render_scene_clip(
            scene=scene,
            final_job_id=final_job_id,
            scene_index=index,
            provider_name=provider_name,
            api_key=api_key,
            model=model,
            logs_dir=logs_dir,
        )
        clips.append(clip)
        scene_results.append(metadata)
        scene_codes.append(rendered_code)

    (job_dir / "structured_scene_results.json").write_text(
        _safe_json(scene_results), encoding="utf-8"
    )
    final_mp4 = job_dir / "video.mp4"
    final_vtt = job_dir / "video.vtt"
    _concat_clips(clips, final_mp4, logs_dir)
    _apply_final_watermark(final_mp4, logs_dir)
    _write_vtt_from_plan(plan, final_vtt)

    scene_bundle = _bundle_for_scene_code(plan, scene_codes, raw_plan)
    bundle_path = job_dir / "scene_bundle.txt"
    bundle_path.write_text(scene_bundle, encoding="utf-8")
    used_fallback = any(bool(item.get("used_fallback")) for item in scene_results)

    return {
        "ok": True,
        "status": "ok",
        "job_id": final_job_id,
        "video_url": to_static_url(final_mp4),
        "vtt_url": to_static_url(final_vtt),
        "scene_code": scene_bundle,
        "scene_plan": plan,
        "scene_results": scene_results,
        "used_fallback": used_fallback,
        "plan_repaired": plan_repaired,
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
    final_job_id = str(job_id or uuid.uuid4().hex[:12])
    job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
    logs_dir = job_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "structured_manim_generation_start job_id=%s provider=%s model=%s mode=tagged_fields_and_bodies_one_call",
        final_job_id,
        provider_name,
        model,
    )
    raw = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_SYSTEM,
        user=build_structured_video_user_prompt(prompt),
        temperature=0.28,
        max_tokens=7000,
    )
    raw_text = _coerce_llm_text(raw)
    (logs_dir / "structured_response_raw.txt").write_text(raw_text, encoding="utf-8")
    parsed, bodies, plan_text, repaired_plan_text, plan_was_repaired = _parse_structured_response(raw_text)
    _write_response_debug_artifacts(
        logs_dir=logs_dir,
        prefix="structured",
        raw_text=raw_text,
        plan_text=plan_text,
        bodies=bodies,
        repaired_plan_text=repaired_plan_text,
        plan_was_repaired=plan_was_repaired,
    )
    parsed = _attach_manim_bodies(parsed, bodies)
    plan = _normalize_plan(parsed, topic=prompt)
    plan, repaired = _repair_plan_if_needed(
        plan,
        topic=prompt,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        logs_dir=logs_dir,
    )
    return _render_structured_plan(
        plan,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        final_job_id=final_job_id,
        raw_plan=raw_text,
        plan_repaired=repaired,
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
    original_plan = parse_plan_from_scene_bundle(original_bundle, topic="Edited video")
    provider_name, api_key = _pick_provider_and_key(provider, provider_keys)
    final_job_id = str(job_id or uuid.uuid4().hex[:12])
    job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
    logs_dir = job_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "structured_manim_edit_start job_id=%s provider=%s model=%s",
        final_job_id,
        provider_name,
        model,
    )
    raw = call_llm(
        provider=provider_name,
        api_key=api_key,
        model=model,
        system=STRUCTURED_VIDEO_EDIT_SYSTEM,
        user=build_structured_video_edit_user_prompt(original_plan, edit_instructions),
        temperature=0.18,
        max_tokens=7000,
    )
    raw_text = _coerce_llm_text(raw)
    (logs_dir / "structured_edit_response_raw.txt").write_text(raw_text, encoding="utf-8")
    parsed, bodies, plan_text, repaired_plan_text, plan_was_repaired = _parse_structured_response(raw_text)
    _write_response_debug_artifacts(
        logs_dir=logs_dir,
        prefix="structured_edit",
        raw_text=raw_text,
        plan_text=plan_text,
        bodies=bodies,
        repaired_plan_text=repaired_plan_text,
        plan_was_repaired=plan_was_repaired,
    )
    parsed = _attach_manim_bodies(parsed, bodies)
    parsed = _inherit_missing_scene_fields(parsed, original_plan)
    plan = _normalize_plan(parsed, topic=str(original_plan.get("title") or "Edited video"))
    plan, repaired = _repair_plan_if_needed(
        plan,
        topic=str(original_plan.get("title") or "Edited video"),
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        logs_dir=logs_dir,
    )
    return _render_structured_plan(
        plan,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        final_job_id=final_job_id,
        raw_plan=raw_text,
        plan_repaired=repaired,
    )
