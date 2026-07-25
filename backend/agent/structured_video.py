"""Structured educational Manim generation for UpcurvEd.

New generations expose only two model-facing choices: reliable standard component scenes, or
``custom_manim_scene`` with one complete runnable ``MANIM_SCRIPT``. Complete scripts are
sanitized, preflighted, rendered, repaired in batches, simplified in batches when necessary,
and finally replaced by the existing domain-neutral component fallback only as a last resort.
Legacy ``MANIM_BODY`` bundles remain readable and are migrated through the complete-script path.
"""

from __future__ import annotations

import html
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import textwrap
import time
import uuid
from typing import Any

from backend.agent.code_sanitize import SanitizeResult, sanitize_manim_script, sanitize_minimally
from backend.agent.llm.clients import call_llm
from backend.agent.llm.provider_config import (
    get_default_model,
    resolve_provider_and_key as _pick_provider_and_key,
)
from backend.agent.prompts import (
    STRUCTURED_VIDEO_BATCH_RENDER_REPAIR_SYSTEM,
    STRUCTURED_VIDEO_BATCH_SANITIZER_REPAIR_SYSTEM,
    STRUCTURED_VIDEO_BATCH_SIMPLIFY_SYSTEM,
    STRUCTURED_VIDEO_EDIT_SYSTEM,
    STRUCTURED_VIDEO_PLAN_REPAIR_SYSTEM,
    STRUCTURED_VIDEO_SYSTEM,
    build_structured_video_batch_render_repair_prompt,
    build_structured_video_batch_sanitizer_repair_prompt,
    build_structured_video_batch_simplify_prompt,
    build_structured_video_edit_user_prompt,
    build_structured_video_plan_repair_prompt,
    build_structured_video_user_prompt,
)
from backend.agent.video_components import (
    build_code_snippet_scene_code,
    build_component_scene_code,
    build_concept_fallback_scene_code,
    build_legacy_custom_scene_code,
    portable_math_text,
)
from backend.runner.job_runner import (
    STORAGE,
    check_manim_runtime,
    cleanup_structured_job_artifacts,
    run_job_from_code,
    to_static_url,
)
from backend.utils.failure_log import (
    append_generation_audit,
    mark_diagnostic_retention,
    prune_diagnostic_bundles,
    summarize_error,
)
from backend.utils.diagnostics import diagnostic_category, diagnostic_retryable, public_error_message

logger = logging.getLogger(__name__)

_PLAN_START = "<<<PLAN_JSON>>>"
_PLAN_END = "<<<END_PLAN_JSON>>>"
_RAW_PLAN_START = "<<<RAW_MODEL_RESPONSE>>>"
_RAW_PLAN_END = "<<<END_RAW_MODEL_RESPONSE>>>"
_VIDEO_META_TAG = "VIDEO_META"
_SCENE_PLAN_TAG = "SCENE_PLAN"
_VIDEO_PLAN_TAG = "VIDEO_PLAN"  # legacy JSON transport
_MANIM_SCRIPT_TAG = "MANIM_SCRIPT"
_MANIM_BODY_TAG = "MANIM_BODY"  # legacy saved bundles only

_INITIAL_MAX_TOKENS = int(os.getenv("UPCURVED_VIDEO_INITIAL_MAX_TOKENS", "12000"))
_PLAN_REPAIR_MAX_TOKENS = int(os.getenv("UPCURVED_VIDEO_PLAN_REPAIR_MAX_TOKENS", "8000"))
_SANITIZER_REPAIR_MAX_TOKENS = int(os.getenv("UPCURVED_VIDEO_SANITIZER_REPAIR_MAX_TOKENS", "8000"))
_RENDER_REPAIR_MAX_TOKENS = int(os.getenv("UPCURVED_VIDEO_RENDER_REPAIR_MAX_TOKENS", "8000"))
_SIMPLIFY_MAX_TOKENS = int(os.getenv("UPCURVED_VIDEO_SIMPLIFY_MAX_TOKENS", "7000"))
_SCENE_RENDER_TIMEOUT = int(os.getenv("UPCURVED_SCENE_RENDER_TIMEOUT_SECONDS", "300"))
_MAX_CUSTOM_SCENES = int(os.getenv("UPCURVED_MAX_CUSTOM_SCENES", "3"))
_VOICE_SYNTHESIS_RETRIES = max(0, int(os.getenv("UPCURVED_VOICE_RETRIES", "2")))
_VOICE_RETRY_BASE_DELAY = max(0.1, float(os.getenv("UPCURVED_VOICE_RETRY_DELAY_SECONDS", "1.5")))

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
    "code",
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


class StructuredVideoFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        affected_scenes: list[int] | None = None,
        error_category: str | None = None,
        during_stage: str | None = None,
        retryable: bool | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.affected_scenes = affected_scenes or []
        self.error_category = error_category
        self.during_stage = during_stage or stage
        self.retryable = retryable


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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "required"}


def _derive_display_points(value: Any, *, limit: int = 3) -> list[str]:
    """Create short learner-facing points from existing narration without another LLM call."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []

    raw_parts = re.split(r"(?<=[.!?])\s+|[;•]+", text)
    candidates: list[str] = []
    for raw in raw_parts:
        part = re.sub(r"^[\s\-–—•]+", "", raw).strip()
        if not part:
            continue
        # Long single sentences often contain useful learner-facing clauses.
        clauses = re.split(
            r",\s+|\s+(?:and|but|so|because|while|whereas)\s+",
            part,
            flags=re.IGNORECASE,
        )
        useful = [clause.strip(" ,.;:") for clause in clauses if len(clause.strip().split()) >= 3]
        if len(useful) >= 2 and len(part) > 105:
            candidates.extend(useful)
        else:
            candidates.append(part.strip(" ,;"))

    points: list[str] = []
    for candidate in candidates:
        point = _short_text(candidate, 112, "").rstrip(" .")
        if not point:
            continue
        normalized = re.sub(r"[^a-z0-9]+", " ", point.lower()).strip()
        if normalized and normalized not in {
            re.sub(r"[^a-z0-9]+", " ", existing.lower()).strip()
            for existing in points
        }:
            points.append(point)
        if len(points) >= limit:
            break
    return points


def _standard_visible_content_score(scene: dict[str, Any]) -> int:
    """Estimate whether a deterministic scene has enough learner-facing material.

    A lone subtitle or question is not enough for a long teaching scene. Formula and ordered
    step renderers count as substantial content; otherwise require at least two visible ideas.
    """
    steps = [
        value
        for value in (scene.get("steps") or scene.get("calculation_steps") or [])
        if str(value).strip()
    ]
    if steps:
        return max(2, len(steps))
    if str(scene.get("formula") or "").strip():
        return 2
    if str(scene.get("code_snippet") or "").strip():
        return 2

    score = 0
    score += len([value for value in (scene.get("key_points") or []) if str(value).strip()])
    score += len([value for value in (scene.get("labels") or []) if str(value).strip()])
    score += 1 if str(scene.get("subtitle") or "").strip() else 0
    score += 1 if str(scene.get("learner_question") or "").strip() else 0
    return score


def _scene_has_standard_visible_content(scene: dict[str, Any]) -> bool:
    return _standard_visible_content_score(scene) >= 2


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


def _clean_code_block(source: Any) -> str:
    text = str(source or "").replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    text = text.strip("\n")
    text = re.sub(r"^[ \t]*```(?:python)?[ \t]*(?:\n)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:\n)?[ \t]*```[ \t]*$", "", text)
    return textwrap.dedent(text).strip()


def _normalize_code_snippet(value: Any) -> str:
    """Preserve the complete learner-facing source code without executing it."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    text = re.sub(r"^[ \t]*```(?:[A-Za-z0-9_+-]+)?[ \t]*(?:\n)?", "", text)
    text = re.sub(r"(?:\n)?[ \t]*```[ \t]*$", "", text)
    text = text.strip("\n")
    if not text.strip():
        return ""
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip()


def _extract_tagged_section(text: str, tag: str) -> str | None:
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
    """Extract blocks independently and salvage a final block missing its closing tag."""
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
    source = str(block or "")
    pattern = re.compile(
        rf"<{re.escape(tag)}\s*>\s*(.*?)\s*</{re.escape(tag)}\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    values = [html.unescape(match.group(1).strip()) for match in pattern.finditer(source)]
    if values:
        return [value for value in values if value]

    line_pattern = re.compile(
        rf"^\s*{re.escape(tag)}\s*:\s*(.+?)\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    values = [html.unescape(match.group(1).strip()) for match in line_pattern.finditer(source)]
    if values:
        return [value for value in values if value]

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
    source = str(text or "").strip()
    scene_blocks = _extract_tagged_blocks(
        source,
        _SCENE_PLAN_TAG,
        stop_tags=(_MANIM_SCRIPT_TAG, _MANIM_BODY_TAG),
    )
    if not scene_blocks:
        return None

    meta_blocks = _extract_tagged_blocks(
        source,
        _VIDEO_META_TAG,
        stop_tags=(_SCENE_PLAN_TAG, _MANIM_SCRIPT_TAG, _MANIM_BODY_TAG),
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
        "essential_visual": "ESSENTIAL_VISUAL",
        "requires_3d": "REQUIRES_3D",
        "code_goal": "CODE_GOAL",
        "code_snippet": "CODE_SNIPPET",
        "manim_script_ref": "MANIM_SCRIPT_REF",
        "manim_body_ref": "MANIM_BODY_REF",
    }
    list_fields = {
        "required_visual_elements": "REQUIRED_VISUAL_ELEMENT",
        "labels": "LABEL",
        "key_points": "KEY_POINT",
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
        parsed_steps, parsed_narrations = _tagged_step_pairs(block)
        if parsed_steps:
            scene["steps"] = parsed_steps
            scene["step_narrations"] = parsed_narrations
        if len(scene) > 1:
            plan["scenes"].append(scene)

    if not plan["scenes"]:
        return None

    code_positions = [
        match.start()
        for tag in (_MANIM_SCRIPT_TAG, _MANIM_BODY_TAG)
        for match in [re.search(rf"<{re.escape(tag)}\b", source, flags=re.IGNORECASE)]
        if match
    ]
    transport_text = source[: min(code_positions)].strip() if code_positions else source
    return plan, transport_text


def _extract_code_sections(text: str, tag: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for attrs, body in _extract_tagged_blocks(str(text or ""), tag):
        ref = _attribute_value(attrs, "id")
        cleaned = _clean_code_block(body)
        if ref and cleaned:
            sections[ref] = cleaned
    return sections


def _extract_ordered_repair_scripts(
    raw_text: str,
    requested_refs: list[str],
) -> tuple[dict[str, str], bool]:
    """Parse tagged scripts, or safely salvage an exact ordered set of Python fences.

    Salvage is used only when the number of complete GeneratedScene blocks exactly matches the
    number of requested scene ids. Ambiguous responses are never guessed.
    """
    tagged = _extract_code_sections(raw_text, _MANIM_SCRIPT_TAG)
    if tagged:
        return tagged, False

    blocks = [
        _clean_code_block(match.group(1))
        for match in re.finditer(
            r"```(?:python|py)?\s*(.*?)```",
            str(raw_text or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    blocks = [block for block in blocks if "class GeneratedScene" in block]
    refs = [str(ref or "").strip() for ref in requested_refs if str(ref or "").strip()]
    if refs and len(blocks) == len(refs):
        return dict(zip(refs, blocks)), True

    cleaned = _clean_code_block(raw_text)
    if len(refs) == 1 and "class GeneratedScene" in cleaned:
        return {refs[0]: cleaned}, True
    return {}, False


def _matching_replacement(
    replacements: dict[str, str],
    *,
    ref: str,
    scene_id: str,
    scene_index: int,
) -> str:
    candidates = [ref, f"scene_{scene_id}" if scene_id else "", scene_id, f"scene_{scene_index}"]
    matched = next((value for value in candidates if value and value in replacements), None)
    return replacements.get(matched, "") if matched else ""


def _script_ref_for_scene(scene: dict[str, Any], index: int) -> str:
    existing = str(
        scene.get("manim_script_ref")
        or scene.get("manim_body_ref")
        or ""
    ).strip()
    if existing:
        return existing
    scene_id = str(scene.get("id") or index).strip()
    return f"scene_{scene_id}"


def _attach_manim_code(
    plan: dict[str, Any],
    scripts: dict[str, str],
    legacy_bodies: dict[str, str],
) -> dict[str, Any]:
    scenes = plan.get("scenes")
    if not isinstance(scenes, list):
        return plan
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        custom_like = (
            scene.get("type") == "custom_manim_scene"
            or scene.get("manim_script_ref")
            or scene.get("manim_body_ref")
        )
        if not custom_like:
            continue
        ref = _script_ref_for_scene(scene, index)
        scene["manim_script_ref"] = ref
        scene_id = str(scene.get("id") or "").strip()
        candidates = [ref, f"scene_{scene_id}" if scene_id else "", scene_id, f"scene_{index}"]
        script_match = next((value for value in candidates if value and value in scripts), None)
        body_match = next((value for value in candidates if value and value in legacy_bodies), None)
        if script_match:
            scene["manim_script"] = scripts[script_match]
            scene.pop("manim_body", None)
            scene.pop("manim_body_ref", None)
        elif body_match:
            scene["manim_body"] = legacy_bodies[body_match]
            scene["manim_body_ref"] = ref
    return plan


def _parse_structured_response(
    raw: str,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], str, str | None, bool]:
    text = str(raw or "").strip()
    scripts = _extract_code_sections(text, _MANIM_SCRIPT_TAG)
    legacy_bodies = _extract_code_sections(text, _MANIM_BODY_TAG)

    tagged = _parse_tagged_video_plan(text)
    if tagged is not None:
        parsed, transport_text = tagged
        return parsed, scripts, legacy_bodies, transport_text, None, False

    plan_text = _extract_tagged_section(text, _VIDEO_PLAN_TAG)
    source_plan_text = text if plan_text is None else plan_text
    parsed, parsed_plan_text, was_repaired = _extract_json_object_with_local_repair(source_plan_text)
    repaired_plan_text = parsed_plan_text if was_repaired else None
    return parsed, scripts, legacy_bodies, source_plan_text, repaired_plan_text, was_repaired


def _split_plan_and_code(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    cloned = json.loads(json.dumps(plan or {}, ensure_ascii=False))
    scripts: dict[str, str] = {}
    legacy_bodies: dict[str, str] = {}
    scenes = cloned.get("scenes")
    if not isinstance(scenes, list):
        return cloned, scripts, legacy_bodies
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        script = _clean_code_block(scene.pop("manim_script", ""))
        body = _clean_code_block(scene.pop("manim_body", ""))
        custom_like = (
            scene.get("type") == "custom_manim_scene"
            or script
            or body
            or scene.get("manim_script_ref")
            or scene.get("manim_body_ref")
        )
        if not custom_like:
            continue
        ref = _script_ref_for_scene(scene, index)
        scene["manim_script_ref"] = ref
        if script:
            scripts[ref] = script
            scene.pop("manim_body_ref", None)
        elif body:
            legacy_bodies[ref] = body
            scene["manim_body_ref"] = ref
    return cloned, scripts, legacy_bodies


def _safe_ref(value: Any, fallback: str = "scene") -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_") or fallback


def _write_response_debug_artifacts(
    *,
    logs_dir: pathlib.Path,
    prefix: str,
    raw_text: str,
    plan_text: str,
    scripts: dict[str, str],
    legacy_bodies: dict[str, str],
    repaired_plan_text: str | None = None,
    plan_was_repaired: bool = False,
) -> None:
    """Persist only the compact plan transport needed to reconstruct an abnormal run."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    if plan_text.strip():
        (logs_dir / f"{prefix}_plan_transport.txt").write_text(plan_text, encoding="utf-8")
    if plan_was_repaired and repaired_plan_text is not None:
        (logs_dir / f"{prefix}_plan_repaired.json").write_text(
            repaired_plan_text, encoding="utf-8"
        )

def _remember_response_debug_context(
    metrics: dict[str, Any],
    *,
    prefix: str,
    raw_text: str,
    plan_text: str,
    scripts: dict[str, str],
    legacy_bodies: dict[str, str],
    repaired_plan_text: str | None = None,
    plan_was_repaired: bool = False,
) -> None:
    """Keep initial model artifacts in memory unless a run actually becomes abnormal."""
    metrics.setdefault("_response_debug_contexts", []).append(
        {
            "prefix": prefix,
            "raw_text": raw_text,
            "plan_text": plan_text,
            "scripts": dict(scripts),
            "legacy_bodies": dict(legacy_bodies),
            "repaired_plan_text": repaired_plan_text,
            "plan_was_repaired": bool(plan_was_repaired),
        }
    )


def _flush_response_debug_contexts(
    metrics: dict[str, Any],
    logs_dir: pathlib.Path,
) -> None:
    """Persist remembered model artifacts once, only for abnormal runs."""
    if metrics.get("_debug_contexts_flushed"):
        return
    contexts = metrics.get("_response_debug_contexts") or []
    for context in contexts:
        _write_response_debug_artifacts(
            logs_dir=logs_dir,
            prefix=str(context.get("prefix") or "structured"),
            raw_text=str(context.get("raw_text") or ""),
            plan_text=str(context.get("plan_text") or ""),
            scripts=dict(context.get("scripts") or {}),
            legacy_bodies=dict(context.get("legacy_bodies") or {}),
            repaired_plan_text=context.get("repaired_plan_text"),
            plan_was_repaired=bool(context.get("plan_was_repaired")),
        )
    metrics["_debug_contexts_flushed"] = True


def _record_local_script_adjustments(
    metrics: dict[str, Any],
    *,
    scene_index: int,
    stage: str,
    result: SanitizeResult,
) -> None:
    changes = [str(value).strip() for value in result.changes if str(value).strip()]
    if not changes:
        return
    metrics.setdefault("local_script_adjustments", []).append(
        {
            "scene": int(scene_index),
            "stage": str(stage),
            "changes": list(dict.fromkeys(changes)),
        }
    )
    adjusted = metrics.setdefault("_locally_adjusted_scene_ids", set())
    adjusted.add(int(scene_index))
    metrics["local_sanitizer_corrections"] = len(adjusted)


def _scene_diagnostic_entry(metrics: dict[str, Any], scene_index: int) -> dict[str, Any]:
    table = metrics.setdefault("_scene_diagnostics", {})
    return table.setdefault(str(int(scene_index)), {"scene": int(scene_index), "attempts": []})


def _record_scene_diagnostic(
    metrics: dict[str, Any],
    *,
    scene_index: int,
    stage: str,
    ok: bool,
    category: str = "",
    error: str = "",
    changes: list[str] | None = None,
    detail_files: list[str] | None = None,
    voice_retries: int = 0,
) -> None:
    entry = _scene_diagnostic_entry(metrics, scene_index)
    attempt: dict[str, Any] = {"stage": str(stage), "ok": bool(ok)}
    if category:
        attempt["category"] = str(category)
    if error:
        attempt["error"] = _short_text(error, 500, "")
    clean_changes = [str(value).strip() for value in (changes or []) if str(value).strip()]
    if clean_changes:
        attempt["changes"] = list(dict.fromkeys(clean_changes))
    clean_files = [str(value).strip() for value in (detail_files or []) if str(value).strip()]
    if clean_files:
        attempt["detail_files"] = list(dict.fromkeys(clean_files))
    if voice_retries:
        attempt["voice_retries"] = int(voice_retries)
    entry.setdefault("attempts", []).append(attempt)


def _write_scene_diagnostics(metrics: dict[str, Any], logs_dir: pathlib.Path) -> None:
    values = metrics.get("_scene_diagnostics") or {}
    if not values:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    ordered = [values[key] for key in sorted(values, key=lambda value: int(value))]
    (logs_dir / "scene_diagnostics.json").write_text(
        _safe_json({"scenes": ordered}), encoding="utf-8"
    )


def _write_unique_detail(
    metrics: dict[str, Any],
    logs_dir: pathlib.Path,
    filename: str,
    content: str,
) -> str:
    """Write a diagnostic detail once and reuse its filename for identical content."""
    import hashlib

    value = str(content or "")
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()
    known = metrics.setdefault("_detail_hashes", {})
    if digest in known:
        return str(known[digest])
    details = logs_dir / "details"
    details.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_ref(filename)
    path = details / safe_name
    path.write_text(value + ("\n" if value and not value.endswith("\n") else ""), encoding="utf-8")
    relative = str(path.relative_to(logs_dir))
    known[digest] = relative
    return relative


def _record_transport_salvage(metrics: dict[str, Any], *, stage: str, refs: list[str]) -> None:
    metrics["transport_salvages"] = int(metrics.get("transport_salvages") or 0) + 1
    values = metrics.setdefault("local_plan_adjustments", [])
    message = f"{stage}: mapped {len(refs)} ordered Python block(s) to requested scene ids locally."
    if message not in values:
        values.append(message)


def _raise_for_voice_failures(states: dict[int, dict[str, Any]]) -> None:
    for state in states.values():
        if state.get("status") != "render_failed":
            continue
        if state.get("last_error_category") != "voice_synthesis":
            continue
        index = int(state["scene_index"])
        stage = str((state.get("attempts") or [{}])[-1].get("stage") or "scene_render")
        raise StructuredVideoFailure(
            f"Scene {index} could not complete because voice generation was temporarily unavailable: "
            f"{summarize_error(state.get('last_render_detail'))}",
            stage=stage,
            affected_scenes=[index],
            error_category="voice_synthesis",
            during_stage=stage,
            retryable=True,
        )


def _audit_outcome(metrics: dict[str, Any], *, failed: bool) -> str:
    if failed:
        return "failed"
    if metrics.get("component_fallback_scene_ids"):
        return "completed_with_fallback"
    if metrics.get("simplified_scene_ids"):
        return "simplified"
    if (
        metrics.get("plan_repaired_by_model")
        or metrics.get("sanitizer_repaired_scene_ids")
        or metrics.get("render_repaired_scene_ids")
        or int(metrics.get("voice_retry_count") or 0) > 0
    ):
        return "recovered"
    if (
        metrics.get("local_json_plan_repair")
        or metrics.get("local_plan_adjustments")
        or metrics.get("local_script_adjustments")
    ):
        return "normalized_locally"
    return "clean_success"

def _append_audit_and_cleanup(
    *,
    job_id: str,
    plan: dict[str, Any] | None,
    provider_name: str | None,
    model: str | None,
    metrics: dict[str, Any],
    failed: bool,
    failure_stage: str | None = None,
    affected_scenes: list[int] | None = None,
    error_summary: str | None = None,
    error_category: str | None = None,
    during_stage: str | None = None,
    retryable: bool | None = None,
    has_final_artifact: bool = False,
) -> None:
    scenes = plan.get("scenes") if isinstance(plan, dict) else []
    scenes = scenes if isinstance(scenes, list) else []
    creative = sum(
        1
        for scene in scenes
        if isinstance(scene, dict) and scene.get("type") == "custom_manim_scene"
    )
    duration = max(
        0.0,
        time.monotonic() - float(metrics.get("_started_monotonic") or time.monotonic()),
    )
    abnormal = bool(
        failed
        or metrics.get("plan_repaired_by_model")
        or metrics.get("recovery_stages")
        or metrics.get("simplified_scene_ids")
        or metrics.get("component_fallback_scene_ids")
        or int(metrics.get("voice_retry_count") or 0) > 0
    )

    try:
        append_generation_audit(
            {
                "job_id": job_id,
                "operation": metrics.get("operation") or "generate",
                "outcome": _audit_outcome(metrics, failed=failed),
                "provider": provider_name,
                "model": model,
                "llm_calls": metrics.get("llm_calls"),
                "total_scenes": len(scenes),
                "creative_scenes": creative,
                "rendered_initially": metrics.get("rendered_initially"),
                "plan_repaired_by_model": metrics.get("plan_repaired_by_model"),
                "sanitizer_repaired_scenes": metrics.get("sanitizer_repaired_scene_ids"),
                "render_repaired_scenes": metrics.get("render_repaired_scene_ids"),
                "simplified_scene_ids": metrics.get("simplified_scene_ids"),
                "component_fallback_scene_ids": metrics.get("component_fallback_scene_ids"),
                "recovery_stages": metrics.get("recovery_stages"),
                "local_json_plan_repair": metrics.get("local_json_plan_repair"),
                "local_plan_adjustments": metrics.get("local_plan_adjustments"),
                "local_script_adjustments": metrics.get("local_script_adjustments"),
                "voice_retry_count": metrics.get("voice_retry_count"),
                "transport_salvages": metrics.get("transport_salvages"),
                "failure_stage": failure_stage,
                "during_stage": during_stage,
                "error_category": error_category,
                "retryable": retryable,
                "affected_scenes": affected_scenes or [],
                "error_summary": error_summary,
                "duration_seconds": duration,
            }
        )
    except Exception as exc:
        logger.warning("generation_audit_append_failed job_id=%s error=%s", job_id, exc)

    if abnormal:
        mark_diagnostic_retention(
            job_id=job_id,
            status="failed" if failed else _audit_outcome(metrics, failed=False),
            has_final_artifact=has_final_artifact,
        )
    try:
        cleanup_structured_job_artifacts(job_id, keep_diagnostics=abnormal)
    except Exception as exc:
        logger.warning("structured_job_cleanup_failed job_id=%s error=%s", job_id, exc)
    try:
        prune_diagnostic_bundles()
    except Exception as exc:
        logger.warning("diagnostic_prune_failed error=%s", exc)

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
            "advanced_manim_scene": "custom_manim_scene",
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
        code_snippet = _normalize_code_snippet(
            incoming.get("code_snippet") or incoming.get("source_code") or ""
        )
        if visual_mode in {"graph", "code"} or code_snippet:
            scene_type = "custom_manim_scene"
        if code_snippet and visual_mode == "text":
            visual_mode = "code"

        scene_title = _short_text(
            incoming.get("title") or incoming.get("heading"), 68, f"{title} {index}"
        )
        scene_subtitle = _short_text(incoming.get("subtitle"), 100, "")
        narration = _short_text(incoming.get("narration"), 900, scene_title)
        visual = _short_text(incoming.get("visual") or incoming.get("visual_goal"), 280, "")
        learner_question = _short_text(incoming.get("learner_question"), 180, "")
        required_elements = _normalize_string_list(
            incoming.get("required_visual_elements"), limit=6, item_limit=72
        )
        labels = _normalize_labels(incoming.get("labels"))
        key_points = _normalize_string_list(
            incoming.get("key_points") or incoming.get("display_points"),
            limit=5,
            item_limit=120,
        )
        formula = _normalize_math(incoming.get("formula") or incoming.get("equation"), 220)
        essential_visual = (
            _coerce_bool(incoming.get("essential_visual"))
            or visual_mode in {"graph", "code"}
            or bool(code_snippet)
        )
        requires_3d = _coerce_bool(incoming.get("requires_3d"))

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
            [_short_text(value, 460, "") for value in raw_step_narrations[:6]]
            if isinstance(raw_step_narrations, list)
            else []
        )
        step_narrations = [
            provided_step_narrations[step_index]
            if step_index < len(provided_step_narrations)
            and provided_step_narrations[step_index]
            else _fallback_step_narration(step, step_index, len(steps))
            for step_index, step in enumerate(steps)
        ]

        try:
            duration = float(incoming.get("duration_sec") or 10)
        except Exception:
            duration = 10.0
        duration = max(4.0, min(90.0, duration))
        if steps:
            duration = max(
                duration,
                min(
                    90.0,
                    _minimum_sequence_duration(
                        narration,
                        step_narrations,
                        has_formula=bool(formula),
                    ),
                ),
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
            "key_points": key_points,
            "essential_visual": essential_visual,
            "requires_3d": requires_3d,
            "duration_sec": duration,
        }
        if formula:
            scene["formula"] = formula
        if code_snippet:
            scene["code_snippet"] = code_snippet
        if steps:
            scene["steps"] = steps
            scene["step_narrations"] = step_narrations

        if scene_type == "custom_manim_scene":
            scene["code_goal"] = _short_text(incoming.get("code_goal") or visual, 280, visual)
            scene["manim_script_ref"] = _script_ref_for_scene(incoming, index)
            script = _clean_code_block(incoming.get("manim_script") or "")
            body = _clean_code_block(incoming.get("manim_body") or "")
            if script:
                scene["manim_script"] = script
            elif body:
                scene["manim_body"] = body
                scene["manim_body_ref"] = scene["manim_script_ref"]
        scenes.append(scene)

    if not scenes:
        raise RuntimeError("The model returned no usable video scenes.")

    # Preserve a genuine opening hook. The first scene no longer has to be a title card.
    if scenes[0].get("type") == "title_scene" and scenes[0].get("learner_question"):
        scenes[0]["type"] = "question_scene"
        if scenes[0].get("visual_mode") == "text":
            scenes[0]["visual_mode"] = "diagram"

    # A later title card usually wastes teaching time; render it as a concise recap/concept.
    for scene_index, scene in enumerate(scenes, start=1):
        if scene_index > 1 and scene.get("type") == "title_scene":
            scene["type"] = "concept_scene"
            if scene.get("visual_mode") == "text":
                scene["visual_mode"] = "diagram"

    # Enforce the agreed maximum while keeping essential graph/3D/code visuals first.
    custom_indices = [index for index, scene in enumerate(scenes) if scene.get("type") == "custom_manim_scene"]
    if len(custom_indices) > _MAX_CUSTOM_SCENES:
        ranked = sorted(
            custom_indices,
            key=lambda idx: (
                not bool(scenes[idx].get("essential_visual")),
                not bool(scenes[idx].get("code_snippet")),
                not bool(scenes[idx].get("requires_3d")),
                idx,
            ),
        )
        keep = set(ranked[:_MAX_CUSTOM_SCENES])
        for idx in custom_indices:
            if idx in keep:
                continue
            scene = scenes[idx]
            scene["type"] = "concept_scene"
            scene["visual_mode"] = "code" if scene.get("code_snippet") else "diagram"
            scene["essential_visual"] = bool(scene.get("code_snippet"))
            for field in (
                "manim_script",
                "manim_script_ref",
                "manim_body",
                "manim_body_ref",
                "code_goal",
                "requires_3d",
            ):
                scene.pop(field, None)

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
    """Return only structural errors that make the plan unusable.

    Pedagogical and visual preferences are prompt guidance. They never trigger speculative
    repair calls before a scene has had a chance to render.
    """
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        return ["The plan contains no scenes."]
    return []

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
    """Apply only unambiguous transport normalizations without judging visual quality."""
    fixes: list[str] = []
    scenes = plan.get("scenes")
    if not isinstance(scenes, list):
        return fixes

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        if scene.get("code_snippet"):
            changed = False
            if scene.get("visual_mode") != "code":
                scene["visual_mode"] = "code"
                changed = True
            if scene.get("type") != "custom_manim_scene":
                scene["type"] = "custom_manim_scene"
                scene["manim_script_ref"] = _script_ref_for_scene(scene, index)
                changed = True
            if not scene.get("essential_visual"):
                scene["essential_visual"] = True
                changed = True
            if changed:
                fixes.append(f"Scene {index}: preserved learner-facing CODE_SNIPPET as a custom code scene.")

        if index > 1 and scene.get("type") == "title_scene":
            scene["type"] = "concept_scene"
            if scene.get("visual_mode") == "text":
                scene["visual_mode"] = "diagram"
            fixes.append(f"Scene {index}: converted a later title card into a teaching scene.")

        # Standard components need at least one visible idea, but this never affects custom code.
        if scene.get("type") != "custom_manim_scene" and index > 1 and not _scene_has_standard_visible_content(scene):
            points = _derive_display_points(scene.get("narration"), limit=3)
            if points:
                scene["key_points"] = points
                fixes.append(f"Scene {index}: derived visible text for the standard renderer.")
    return fixes

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
        "essential_visual",
        "requires_3d",
        "labels",
        "key_points",
        "code_snippet",
        "manim_script_ref",
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
        custom_like = (
            str(scene.get("type") or "").strip().lower() == "custom_manim_scene"
            or str(scene.get("visual_mode") or "").strip().lower() == "graph"
            or bool(scene.get("manim_script_ref"))
            or bool(scene.get("manim_body_ref"))
        )
        if custom_like and not str(scene.get("manim_script") or "").strip():
            script = _clean_code_block(original.get("manim_script") or "")
            if script:
                scene["manim_script"] = script
        if custom_like and not str(scene.get("manim_script") or "").strip() and not str(
            scene.get("manim_body") or ""
        ).strip():
            body = _clean_code_block(original.get("manim_body") or "")
            if body:
                scene["manim_body"] = body
    return edited_plan


def _repair_plan_if_needed(
    plan: dict[str, Any],
    *,
    topic: str,
    provider_name: str,
    api_key: str,
    model: str | None,
    logs_dir: pathlib.Path,
    metrics: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Normalize the plan locally; never spend an LLM call on quality heuristics."""
    local_fixes = _apply_local_plan_quality_fixes(plan, topic=topic)
    if local_fixes:
        metrics.setdefault("local_plan_adjustments", []).extend(local_fixes)
        logger.info("structured_video_plan_local_fixes fixes=%s", local_fixes)
    errors = _plan_quality_errors(plan)
    if errors:
        raise StructuredVideoFailure(
            "; ".join(errors), stage="plan_structure", error_category="malformed_plan"
        )
    return plan, False

def _scene_prompt_data(scene: dict[str, Any]) -> dict[str, Any]:
    data = dict(scene)
    for field in ("manim_script", "manim_body"):
        data.pop(field, None)
    return data


def _enforce_scene_script_contract(
    scene: dict[str, Any],
    result: SanitizeResult,
) -> SanitizeResult:
    """Keep only sanitizer hard errors; do not enforce visual implementation heuristics."""
    return result

def _sanitize_error_list(result: SanitizeResult) -> list[str]:
    errors = list(result.validation_errors)
    if result.compile_error:
        errors.append(result.compile_error)
    if result.unresolved_references:
        errors.append("Unresolved references: " + ", ".join(result.unresolved_references))
    if result.blocked_operations:
        errors.append("Blocked operations: " + ", ".join(result.blocked_operations))
    return list(dict.fromkeys(errors))


def _write_sanitize_artifacts(
    *,
    logs_dir: pathlib.Path,
    scene_index: int,
    stage: str,
    original_script: str,
    result: SanitizeResult,
    metrics: dict[str, Any],
) -> None:
    errors = _sanitize_error_list(result)
    detail_files: list[str] = []
    if result.requires_repair:
        detail_files.append(
            _write_unique_detail(
                metrics, logs_dir, f"scene_{scene_index:02d}_{stage}_original.py", original_script
            )
        )
        if result.source.strip() != str(original_script or "").strip():
            detail_files.append(
                _write_unique_detail(
                    metrics, logs_dir, f"scene_{scene_index:02d}_{stage}_sanitized.py", result.source
                )
            )
    _record_scene_diagnostic(
        metrics,
        scene_index=scene_index,
        stage=f"{stage}_preflight",
        ok=not result.requires_repair,
        category="hard_preflight" if result.requires_repair else "",
        error="; ".join(errors),
        changes=result.changes,
        detail_files=detail_files,
    )

def _legacy_wrapper_preflight(source: str) -> SanitizeResult:
    prepared = sanitize_minimally(source)
    compile_error: str | None = None
    try:
        compile(prepared, "<legacy-custom-scene>", "exec")
    except Exception as exc:
        compile_error = f"{type(exc).__name__}: {exc}"
    return SanitizeResult(
        source=prepared,
        changes=["Wrapped legacy MANIM_BODY in the compatibility scene shell"],
        validation_errors=[] if compile_error is None else [compile_error],
        compile_error=compile_error,
        requires_repair=compile_error is not None,
        uses_3d=bool(re.search(
            r"\b(?:ThreeDAxes|Surface|Polyhedron|Cube|Sphere|Prism|Cone|Cylinder|"
            r"Dot3D|Line3D|Arrow3D|set_camera_orientation|move_camera|"
            r"begin_ambient_camera_rotation)\b",
            prepared,
        )),
    )


def _prepare_custom_states(
    plan: dict[str, Any],
    *,
    provider_name: str,
    api_key: str,
    model: str | None,
    logs_dir: pathlib.Path,
    metrics: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    states: dict[int, dict[str, Any]] = {}
    scenes = plan.get("scenes") or []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict) or scene.get("type") != "custom_manim_scene":
            continue
        ref = _script_ref_for_scene(scene, index)
        script = _clean_code_block(scene.get("manim_script") or "")
        legacy_body = _clean_code_block(scene.get("manim_body") or "")
        source_kind = "complete_script"
        if script:
            original_script = script
            sanitize_result = _enforce_scene_script_contract(
                scene, sanitize_manim_script(original_script)
            )
        elif legacy_body:
            source_kind = "legacy_body"
            original_script = build_legacy_custom_scene_code(scene, legacy_body)
            sanitize_result = _enforce_scene_script_contract(
                scene, _legacy_wrapper_preflight(original_script)
            )
        else:
            original_script = ""
            sanitize_result = _enforce_scene_script_contract(
                scene, sanitize_manim_script("")
            )

        _record_local_script_adjustments(
            metrics,
            scene_index=index,
            stage="initial",
            result=sanitize_result,
        )
        if sanitize_result.requires_repair:
            _flush_response_debug_contexts(metrics, logs_dir)
            if legacy_body:
                (logs_dir / f"scene_{index:02d}_legacy_body.py").write_text(
                    legacy_body + "\n", encoding="utf-8"
                )
            _write_sanitize_artifacts(
                logs_dir=logs_dir,
                scene_index=index,
                stage="initial",
                original_script=original_script,
                result=sanitize_result,
                metrics=metrics,
            )

        state = {
            "scene_index": index,
            "scene": scene,
            "ref": ref,
            "source_kind": source_kind,
            "original_script": original_script,
            "current_script": sanitize_result.source,
            "sanitize_result": sanitize_result,
            "status": "ready" if not sanitize_result.requires_repair else "preflight_failed",
            "clip": None,
            "rendered_code": None,
            "render_source": None,
            "used_fallback": False,
            "sanitizer_repaired": False,
            "attempts": [],
        }
        if sanitize_result.requires_repair:
            state["attempts"].append({
                "stage": "sanitizer_preflight",
                "ok": False,
                "error": summarize_error(
                    "\n".join(_sanitize_error_list(sanitize_result)),
                    fallback="Sanitizer preflight failed.",
                ),
            })
        states[index] = state

    failures = [state for state in states.values() if state["status"] == "preflight_failed"]
    if not failures:
        return states

    _flush_response_debug_contexts(metrics, logs_dir)
    request_failures: list[dict[str, Any]] = []
    for state in failures:
        result: SanitizeResult = state["sanitize_result"]
        request_failures.append({
            "ref": state["ref"],
            "scene": _scene_prompt_data(state["scene"]),
            "errors": _sanitize_error_list(result),
            "changes": result.changes,
            "removed_imports": result.removed_imports,
            "original_script": state["original_script"],
            "sanitized_script": result.source,
        })

    metrics["llm_calls"] += 1
    metrics["recovery_stages"].append("sanitizer_repair")
    try:
        raw = call_llm(
            provider=provider_name,
            api_key=api_key,
            model=model,
            system=STRUCTURED_VIDEO_BATCH_SANITIZER_REPAIR_SYSTEM,
            user=build_structured_video_batch_sanitizer_repair_prompt(
                failures=request_failures
            ),
            temperature=0.08,
            max_tokens=_SANITIZER_REPAIR_MAX_TOKENS,
        )
        raw_text = _coerce_llm_text(raw)
        requested_refs = [str(state["ref"]) for state in failures]
        replacements, salvaged = _extract_ordered_repair_scripts(raw_text, requested_refs)
        if salvaged:
            _record_transport_salvage(metrics, stage="sanitizer repair", refs=requested_refs)
        if salvaged or not replacements:
            _write_unique_detail(metrics, logs_dir, "sanitizer_repair_transport.txt", raw_text)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        (logs_dir / "sanitizer_repair_call_error.txt").write_text(
            detail + "\n", encoding="utf-8"
        )
        for state in failures:
            state["attempts"].append({
                "stage": "sanitizer_repair_call",
                "ok": False,
                "error": summarize_error(detail),
            })
            _record_scene_diagnostic(
                metrics,
                scene_index=int(state["scene_index"]),
                stage="sanitizer_repair_call",
                ok=False,
                category=diagnostic_category(detail),
                error=summarize_error(detail),
            )
        return states

    for state in failures:
        ref = str(state["ref"])
        index = int(state["scene_index"])
        scene_id = str(state["scene"].get("id") or "").strip()
        replacement = _matching_replacement(
            replacements, ref=ref, scene_id=scene_id, scene_index=index
        )
        if not replacement:
            state["attempts"].append({
                "stage": "sanitizer_repair",
                "ok": False,
                "error": "No matching MANIM_SCRIPT was returned.",
            })
            _record_scene_diagnostic(
                metrics,
                scene_index=index,
                stage="sanitizer_repair",
                ok=False,
                category="repair_transport",
                error="No matching MANIM_SCRIPT was returned.",
            )
            continue
        repaired = _enforce_scene_script_contract(
            state["scene"], sanitize_manim_script(replacement)
        )
        _record_local_script_adjustments(
            metrics,
            scene_index=index,
            stage="sanitizer_repair",
            result=repaired,
        )
        _write_sanitize_artifacts(
            logs_dir=logs_dir,
            scene_index=index,
            stage="sanitizer_repair",
            original_script=replacement,
            result=repaired,
            metrics=metrics,
        )
        state["current_script"] = repaired.source
        state["sanitize_result"] = repaired
        if repaired.requires_repair:
            state["attempts"].append({
                "stage": "sanitizer_repair",
                "ok": False,
                "error": summarize_error("\n".join(_sanitize_error_list(repaired))),
            })
            continue
        state["status"] = "ready"
        state["sanitizer_repaired"] = True
        state["scene"]["manim_script"] = repaired.source
        state["scene"].pop("manim_body", None)
        state["scene"].pop("manim_body_ref", None)
        state["attempts"].append({"stage": "sanitizer_repair", "ok": True})
        metrics["sanitizer_repaired"] += 1
        metrics.setdefault("sanitizer_repaired_scene_ids", []).append(index)
    return states


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
    last_result: dict[str, Any] = {}
    last_detail = ""
    for attempt in range(_VOICE_SYNTHESIS_RETRIES + 1):
        actual_job_id = scene_job_id if attempt == 0 else f"{scene_job_id}-voice-retry-{attempt}"
        result = run_job_from_code(
            code.strip() + "\n",
            job_id=actual_job_id,
            timeout_seconds=_SCENE_RENDER_TIMEOUT,
            inject_watermark=False,
            retain_logs=False,
        )
        if result.get("ok") and result.get("video_url"):
            path = _video_url_to_path(str(result["video_url"]))
            if path.exists():
                result["voice_retry_count"] = attempt
                result["error_category"] = ""
                return path, result, ""
        detail = str(
            result.get("error_log")
            or result.get("compile_log")
            or result.get("error")
            or "Manim render failed."
        )
        category = diagnostic_category(detail)
        result["error_category"] = category
        result["voice_retry_count"] = attempt
        last_result, last_detail = result, detail
        if category != "voice_synthesis" or attempt >= _VOICE_SYNTHESIS_RETRIES:
            break
        time.sleep(_VOICE_RETRY_BASE_DELAY * (attempt + 1))
    return None, last_result, last_detail

def _attempt_custom_render(
    state: dict[str, Any],
    *,
    final_job_id: str,
    logs_dir: pathlib.Path,
    stage: str,
    render_source: str,
    metrics: dict[str, Any],
) -> bool:
    index = int(state["scene_index"])
    code = str(state.get("current_script") or "").strip()
    stage_slug = _safe_ref(stage)
    scene_job_id = f"{final_job_id}-scene-{index:02d}-{stage_slug}"
    clip, result, detail = _render_code_once(code=code, scene_job_id=scene_job_id)
    voice_retries = int(result.get("voice_retry_count") or 0)
    if voice_retries:
        metrics["voice_retry_count"] = int(metrics.get("voice_retry_count") or 0) + voice_retries
        if "voice_retry" not in metrics.setdefault("recovery_stages", []):
            metrics["recovery_stages"].append("voice_retry")
    category = str(result.get("error_category") or (diagnostic_category(detail) if detail else ""))
    command = result.get("render_command")
    command_text = " ".join(str(value) for value in command) if isinstance(command, list) else str(command or "")
    attempt = {
        "stage": stage,
        "ok": clip is not None,
        "job_id": result.get("job_id"),
        "error_code": result.get("error"),
        "error_category": category,
        "error": "" if clip is not None else summarize_error(detail),
        "render_command": command_text,
        "voice_retries": voice_retries,
    }
    state["attempts"].append(attempt)
    if clip is None:
        _flush_response_debug_contexts(metrics, logs_dir)
        source_file = _write_unique_detail(
            metrics, logs_dir, f"scene_{index:02d}_{stage_slug}_executed.py", code
        )
        error_file = _write_unique_detail(
            metrics, logs_dir, f"scene_{index:02d}_{stage_slug}_render_error.txt", detail
        )
        _record_scene_diagnostic(
            metrics,
            scene_index=index,
            stage=stage,
            ok=False,
            category=category or "render",
            error=summarize_error(detail),
            detail_files=[source_file, error_file],
            voice_retries=voice_retries,
        )
        state["status"] = "render_failed"
        state["last_render_detail"] = detail
        state["last_render_result"] = result
        state["last_error_category"] = category
        return False
    _record_scene_diagnostic(
        metrics,
        scene_index=index,
        stage=stage,
        ok=True,
        category="voice_synthesis_recovered" if voice_retries else "",
        voice_retries=voice_retries,
    )
    state["clip"] = clip
    state["rendered_code"] = code
    state["render_source"] = render_source
    state["status"] = "rendered"
    state["last_error_category"] = ""
    return True

def _render_standard_scene(
    scene: dict[str, Any],
    *,
    final_job_id: str,
    scene_index: int,
    logs_dir: pathlib.Path,
    metrics: dict[str, Any],
) -> tuple[pathlib.Path, dict[str, Any], str]:
    code = sanitize_minimally(build_component_scene_code(scene))
    clip, result, detail = _render_code_once(
        code=code,
        scene_job_id=f"{final_job_id}-scene-{scene_index:02d}-component",
    )
    voice_retries = int(result.get("voice_retry_count") or 0)
    if voice_retries:
        metrics["voice_retry_count"] = int(metrics.get("voice_retry_count") or 0) + voice_retries
        if "voice_retry" not in metrics.setdefault("recovery_stages", []):
            metrics["recovery_stages"].append("voice_retry")
    if clip is None:
        _flush_response_debug_contexts(metrics, logs_dir)
        category = str(result.get("error_category") or diagnostic_category(detail))
        source_file = _write_unique_detail(
            metrics, logs_dir, f"scene_{scene_index:02d}_component.py", code
        )
        error_file = _write_unique_detail(
            metrics, logs_dir, f"scene_{scene_index:02d}_component_render_error.txt", detail
        )
        _record_scene_diagnostic(
            metrics,
            scene_index=scene_index,
            stage="component",
            ok=False,
            category=category,
            error=summarize_error(detail),
            detail_files=[source_file, error_file],
            voice_retries=voice_retries,
        )
        raise StructuredVideoFailure(
            f"Standard scene {scene_index} failed to render: {summarize_error(detail)}",
            stage="standard_scene_render",
            affected_scenes=[scene_index],
            error_category=category,
            during_stage="standard_scene_render",
            retryable=diagnostic_retryable(detail),
        )
    _record_scene_diagnostic(
        metrics,
        scene_index=scene_index,
        stage="component",
        ok=True,
        category="voice_synthesis_recovered" if voice_retries else "",
        voice_retries=voice_retries,
    )
    return clip, {
        "scene_index": scene_index,
        "scene_type": scene.get("type"),
        "render_source": "component",
        "used_fallback": False,
        "job_id": result.get("job_id"),
        "attempts": [{"stage": "component", "ok": True, "job_id": result.get("job_id")}],
    }, code

def _batch_runtime_repair(
    states: dict[int, dict[str, Any]],
    *,
    provider_name: str,
    api_key: str,
    model: str | None,
    final_job_id: str,
    logs_dir: pathlib.Path,
    metrics: dict[str, Any],
) -> None:
    failures = [
        state
        for state in states.values()
        if state.get("status") == "render_failed"
        and state.get("last_error_category") != "voice_synthesis"
        and state.get("attempts")
        and state["attempts"][-1].get("stage") == "initial_render"
    ]
    if not failures:
        return

    _flush_response_debug_contexts(metrics, logs_dir)
    request = []
    for state in failures:
        request.append({
            "ref": state["ref"],
            "scene": _scene_prompt_data(state["scene"]),
            "original_script": state["original_script"],
            "executed_script": state["current_script"],
            "traceback": state.get("last_render_detail") or "",
            "render_stage": "initial_render",
            "render_command": state["attempts"][-1].get("render_command") or "",
        })

    metrics["llm_calls"] += 1
    metrics["recovery_stages"].append("render_repair")
    try:
        raw = call_llm(
            provider=provider_name,
            api_key=api_key,
            model=model,
            system=STRUCTURED_VIDEO_BATCH_RENDER_REPAIR_SYSTEM,
            user=build_structured_video_batch_render_repair_prompt(failures=request),
            temperature=0.1,
            max_tokens=_RENDER_REPAIR_MAX_TOKENS,
        )
        raw_text = _coerce_llm_text(raw)
        requested_refs = [str(state["ref"]) for state in failures]
        replacements, salvaged = _extract_ordered_repair_scripts(raw_text, requested_refs)
        if salvaged:
            _record_transport_salvage(metrics, stage="render repair", refs=requested_refs)
        if salvaged or not replacements:
            _write_unique_detail(metrics, logs_dir, "render_repair_transport.txt", raw_text)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        (logs_dir / "render_repair_call_error.txt").write_text(detail + "\n", encoding="utf-8")
        for state in failures:
            state["attempts"].append({
                "stage": "render_repair_call",
                "ok": False,
                "error": summarize_error(detail),
            })
            _record_scene_diagnostic(
                metrics,
                scene_index=int(state["scene_index"]),
                stage="render_repair_call",
                ok=False,
                category=diagnostic_category(detail),
                error=summarize_error(detail),
            )
        return

    for state in failures:
        index = int(state["scene_index"])
        ref = str(state["ref"])
        scene_id = str(state["scene"].get("id") or "").strip()
        replacement = _matching_replacement(
            replacements, ref=ref, scene_id=scene_id, scene_index=index
        )
        if not replacement:
            state["attempts"].append({
                "stage": "focused_render_repair",
                "ok": False,
                "error": "No matching MANIM_SCRIPT was returned.",
            })
            _record_scene_diagnostic(
                metrics,
                scene_index=index,
                stage="focused_render_repair",
                ok=False,
                category="repair_transport",
                error="No matching MANIM_SCRIPT was returned.",
            )
            continue
        sanitized = _enforce_scene_script_contract(
            state["scene"], sanitize_manim_script(replacement)
        )
        _record_local_script_adjustments(
            metrics,
            scene_index=index,
            stage="focused_render_repair",
            result=sanitized,
        )
        _write_sanitize_artifacts(
            logs_dir=logs_dir,
            scene_index=index,
            stage="focused_render_repair",
            original_script=replacement,
            result=sanitized,
            metrics=metrics,
        )
        if sanitized.requires_repair:
            state["current_script"] = sanitized.source
            state["attempts"].append({
                "stage": "focused_render_repair_preflight",
                "ok": False,
                "error": summarize_error("\n".join(_sanitize_error_list(sanitized))),
            })
            continue
        state["current_script"] = sanitized.source
        if _attempt_custom_render(
            state,
            final_job_id=final_job_id,
            logs_dir=logs_dir,
            stage="focused_render_repair",
            render_source="custom_render_repaired",
            metrics=metrics,
        ):
            state["scene"]["manim_script"] = sanitized.source
            state["scene"].pop("manim_body", None)
            state["scene"].pop("manim_body_ref", None)
            repaired_ids = metrics.setdefault("render_repaired_scene_ids", [])
            if index not in repaired_ids:
                repaired_ids.append(index)
            metrics["render_repaired"] = len(repaired_ids)


def _batch_simplify_remaining(
    states: dict[int, dict[str, Any]],
    *,
    provider_name: str,
    api_key: str,
    model: str | None,
    final_job_id: str,
    logs_dir: pathlib.Path,
    metrics: dict[str, Any],
) -> None:
    failures = [state for state in states.values() if state.get("status") != "rendered"]
    if not failures:
        return

    _flush_response_debug_contexts(metrics, logs_dir)
    request = []
    for state in failures:
        history = [
            {
                "stage": attempt.get("stage"),
                "error": attempt.get("error") or attempt.get("error_code") or "",
            }
            for attempt in state.get("attempts") or []
            if not attempt.get("ok")
        ]
        request.append({
            "ref": state["ref"],
            "scene": _scene_prompt_data(state["scene"]),
            "history": history,
            "original_script": state["original_script"],
            "latest_script": state.get("current_script") or "",
        })

    metrics["llm_calls"] += 1
    metrics["recovery_stages"].append("simpler_scene_retry")
    try:
        raw = call_llm(
            provider=provider_name,
            api_key=api_key,
            model=model,
            system=STRUCTURED_VIDEO_BATCH_SIMPLIFY_SYSTEM,
            user=build_structured_video_batch_simplify_prompt(failures=request),
            temperature=0.08,
            max_tokens=_SIMPLIFY_MAX_TOKENS,
        )
        raw_text = _coerce_llm_text(raw)
        requested_refs = [str(state["ref"]) for state in failures]
        replacements, salvaged = _extract_ordered_repair_scripts(raw_text, requested_refs)
        if salvaged:
            _record_transport_salvage(metrics, stage="simpler scene", refs=requested_refs)
        if salvaged or not replacements:
            _write_unique_detail(metrics, logs_dir, "simpler_scene_transport.txt", raw_text)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        (logs_dir / "simpler_scene_call_error.txt").write_text(detail + "\n", encoding="utf-8")
        for state in failures:
            state["attempts"].append({
                "stage": "simpler_scene_call",
                "ok": False,
                "error": summarize_error(detail),
            })
            _record_scene_diagnostic(
                metrics,
                scene_index=int(state["scene_index"]),
                stage="simpler_scene_call",
                ok=False,
                category=diagnostic_category(detail),
                error=summarize_error(detail),
            )
        return

    for state in failures:
        index = int(state["scene_index"])
        ref = str(state["ref"])
        scene_id = str(state["scene"].get("id") or "").strip()
        replacement = _matching_replacement(
            replacements, ref=ref, scene_id=scene_id, scene_index=index
        )
        if not replacement:
            state["attempts"].append({
                "stage": "simpler_scene_retry",
                "ok": False,
                "error": "No matching MANIM_SCRIPT was returned.",
            })
            _record_scene_diagnostic(
                metrics,
                scene_index=index,
                stage="simpler_scene_retry",
                ok=False,
                category="repair_transport",
                error="No matching MANIM_SCRIPT was returned.",
            )
            continue
        sanitized = _enforce_scene_script_contract(
            state["scene"], sanitize_manim_script(replacement)
        )
        _record_local_script_adjustments(
            metrics,
            scene_index=index,
            stage="simpler_scene",
            result=sanitized,
        )
        _write_sanitize_artifacts(
            logs_dir=logs_dir,
            scene_index=index,
            stage="simpler_scene",
            original_script=replacement,
            result=sanitized,
            metrics=metrics,
        )
        if sanitized.requires_repair:
            state["current_script"] = sanitized.source
            state["attempts"].append({
                "stage": "simpler_scene_preflight",
                "ok": False,
                "error": summarize_error("\n".join(_sanitize_error_list(sanitized))),
            })
            continue
        state["current_script"] = sanitized.source
        if _attempt_custom_render(
            state,
            final_job_id=final_job_id,
            logs_dir=logs_dir,
            stage="simpler_scene_retry",
            render_source="custom_simplified",
            metrics=metrics,
        ):
            state["scene"]["manim_script"] = sanitized.source
            state["scene"].pop("manim_body", None)
            state["scene"].pop("manim_body_ref", None)
            simplified_ids = metrics.setdefault("simplified_scene_ids", [])
            if index not in simplified_ids:
                simplified_ids.append(index)
            metrics["simplified_scenes"] = len(simplified_ids)


def _apply_component_fallbacks(
    states: dict[int, dict[str, Any]],
    *,
    final_job_id: str,
    logs_dir: pathlib.Path,
    metrics: dict[str, Any],
) -> None:
    failures = [state for state in states.values() if state.get("status") != "rendered"]
    if failures:
        _flush_response_debug_contexts(metrics, logs_dir)
    for state in failures:
        index = int(state["scene_index"])
        if str(state["scene"].get("code_snippet") or "").strip():
            fallback_source = build_code_snippet_scene_code(state["scene"])
        else:
            fallback_source = build_concept_fallback_scene_code(state["scene"])
        fallback_code = sanitize_minimally(fallback_source)
        state["current_script"] = fallback_code
        if not _attempt_custom_render(
            state,
            final_job_id=final_job_id,
            logs_dir=logs_dir,
            stage="component_fallback",
            render_source="component_fallback",
            metrics=metrics,
        ):
            category = str(state.get("last_error_category") or "render")
            raise StructuredVideoFailure(
                f"Scene {index} failed after creative repair, simplification, and component fallback: "
                f"{summarize_error(state.get('last_render_detail'))}",
                stage="component_fallback",
                affected_scenes=[index],
                error_category=category,
                during_stage="component_fallback",
                retryable=diagnostic_retryable(state.get("last_render_detail")),
            )
        state["used_fallback"] = True
        fallback_ids = metrics.setdefault("component_fallback_scene_ids", [])
        if index not in fallback_ids:
            fallback_ids.append(index)
        metrics["component_fallbacks"] = len(fallback_ids)

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
    transport_plan, scripts, legacy_bodies = _split_plan_and_code(plan)
    parts = [
        "# Structured UpcurvEd Manim bundle v5",
        _PLAN_START,
        json.dumps(transport_plan, ensure_ascii=False, indent=2),
        _PLAN_END,
    ]
    for ref, script in scripts.items():
        parts.extend([
            f'<MANIM_SCRIPT id="{ref}">',
            script.rstrip(),
            "</MANIM_SCRIPT>",
        ])
    for ref, body in legacy_bodies.items():
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
    scripts = _extract_code_sections(text, _MANIM_SCRIPT_TAG)
    bodies = _extract_code_sections(text, _MANIM_BODY_TAG)
    parsed = _attach_manim_code(parsed, scripts, bodies)
    return _normalize_plan(parsed, topic=topic)


def _build_generation_diagnostics(
    plan: dict[str, Any] | None,
    *,
    provider_name: str | None,
    model: str | None,
    metrics: dict[str, Any],
    failed: bool = False,
    failure_stage: str | None = None,
    failure_summary: str | None = None,
    error_category: str | None = None,
    retryable: bool | None = None,
    during_stage: str | None = None,
) -> dict[str, Any]:
    scenes = plan.get("scenes") if isinstance(plan, dict) else []
    scenes = scenes if isinstance(scenes, list) else []
    creative = sum(
        1 for scene in scenes if isinstance(scene, dict) and scene.get("type") == "custom_manim_scene"
    )
    repaired_ids = sorted({
        int(value)
        for value in (
            list(metrics.get("sanitizer_repaired_scene_ids") or [])
            + list(metrics.get("render_repaired_scene_ids") or [])
        )
    })
    fallback_count = len(set(metrics.get("component_fallback_scene_ids") or []))
    simplified_count = len(set(metrics.get("simplified_scene_ids") or []))
    plan_repaired_by_model = bool(metrics.get("plan_repaired_by_model"))

    if failed:
        quality_status = "failed"
    elif fallback_count:
        quality_status = "completed_with_fallback"
    elif simplified_count:
        quality_status = "simplified"
    elif plan_repaired_by_model or repaired_ids:
        quality_status = "recovered"
    elif creative == 0:
        quality_status = "standard"
    else:
        quality_status = "full_quality"

    diagnostics: dict[str, Any] = {
        "quality_status": quality_status,
        "provider": str(provider_name or ""),
        "model": str(model or ""),
        "llm_calls": int(metrics.get("llm_calls") or 0),
        "total_scenes": len(scenes),
        "creative_scenes": creative,
        "repaired_scenes": len(repaired_ids),
        "plan_repaired_by_model": plan_repaired_by_model,
        "simplified_scenes": simplified_count,
        "component_fallbacks": fallback_count,
        "recovery_stages": list(dict.fromkeys(metrics.get("recovery_stages") or [])),
        "voice_retries": int(metrics.get("voice_retry_count") or 0),
        "failure_stage": failure_stage,
    }
    if error_category:
        diagnostics["error_category"] = error_category
    if during_stage:
        diagnostics["during_stage"] = during_stage
    if retryable is not None:
        diagnostics["retryable"] = bool(retryable)
    if failed and failure_summary:
        diagnostics["summary"] = failure_summary
    return diagnostics

def _runtime_preflight_result(
    *,
    final_job_id: str,
    provider_name: str | None,
    model: str | None,
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
    logs_dir = job_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    runtime = check_manim_runtime()
    if runtime.get("ok"):
        return None

    (logs_dir / "runtime_preflight.json").write_text(_safe_json(runtime), encoding="utf-8")
    detail = str(runtime.get("stderr") or runtime.get("stdout") or "Manim runtime preflight failed.")
    summary = summarize_error(detail, fallback="Manim runtime preflight failed.")
    diagnostics = _build_generation_diagnostics(
        None,
        provider_name=provider_name,
        model=model,
        metrics=metrics,
        failed=True,
        failure_stage="runtime_dependency_preflight",
        failure_summary=public_error_message(detail),
        error_category=diagnostic_category(detail),
        retryable=diagnostic_retryable(detail),
        during_stage="runtime_dependency_preflight",
    )
    _append_audit_and_cleanup(
        job_id=final_job_id,
        plan=None,
        provider_name=provider_name,
        model=model,
        metrics=metrics,
        failed=True,
        failure_stage="runtime_dependency_preflight",
        error_summary=summary,
        has_final_artifact=False,
    )
    return {
        "ok": False,
        "status": "error",
        "error": "render_environment_failed",
        "error_detail": detail,
        "job_id": final_job_id,
        "video_url": None,
        "scene_results": [],
        "generation_diagnostics": diagnostics,
    }


def _render_structured_plan(
    plan: dict[str, Any],
    *,
    provider_name: str,
    api_key: str,
    model: str | None,
    final_job_id: str,
    raw_plan: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
    logs_dir = job_dir / "logs"
    job_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    custom_states = _prepare_custom_states(
        plan,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        logs_dir=logs_dir,
        metrics=metrics,
    )
    scene_assets: dict[int, tuple[pathlib.Path, dict[str, Any], str]] = {}
    for index, scene in enumerate(plan.get("scenes") or [], start=1):
        if scene.get("type") != "custom_manim_scene":
            scene_assets[index] = _render_standard_scene(
                scene,
                final_job_id=final_job_id,
                scene_index=index,
                logs_dir=logs_dir,
                metrics=metrics,
            )
            continue
        state = custom_states[index]
        if state.get("status") != "ready":
            continue
        if _attempt_custom_render(
            state,
            final_job_id=final_job_id,
            logs_dir=logs_dir,
            stage="initial_render",
            render_source=(
                "custom_sanitizer_repaired"
                if state.get("sanitizer_repaired")
                else "custom_initial"
            ),
            metrics=metrics,
        ) and not state.get("sanitizer_repaired"):
            metrics["rendered_initially"] += 1

    _raise_for_voice_failures(custom_states)

    _batch_runtime_repair(
        custom_states,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        final_job_id=final_job_id,
        logs_dir=logs_dir,
        metrics=metrics,
    )
    _raise_for_voice_failures(custom_states)
    _batch_simplify_remaining(
        custom_states,
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        final_job_id=final_job_id,
        logs_dir=logs_dir,
        metrics=metrics,
    )
    _raise_for_voice_failures(custom_states)
    _apply_component_fallbacks(
        custom_states,
        final_job_id=final_job_id,
        logs_dir=logs_dir,
        metrics=metrics,
    )

    for index, state in custom_states.items():
        attempts = [
            {
                "stage": attempt.get("stage"),
                "ok": bool(attempt.get("ok")),
                "job_id": attempt.get("job_id"),
                "error_code": attempt.get("error_code"),
                "error": _short_text(attempt.get("error"), 500, ""),
            }
            for attempt in state.get("attempts") or []
        ]
        metadata = {
            "scene_index": index,
            "scene_type": state["scene"].get("type"),
            "render_source": state.get("render_source"),
            "used_fallback": bool(state.get("used_fallback")),
            "sanitizer_repaired": bool(state.get("sanitizer_repaired")),
            "source_kind": state.get("source_kind"),
            "attempts": attempts,
        }
        scene_assets[index] = (
            state["clip"],
            metadata,
            str(state.get("rendered_code") or ""),
        )

    clips: list[pathlib.Path] = []
    scene_results: list[dict[str, Any]] = []
    scene_codes: list[str] = []
    for index in range(1, len(plan.get("scenes") or []) + 1):
        asset = scene_assets.get(index)
        if not asset or asset[0] is None:
            raise StructuredVideoFailure(
                f"Scene {index} did not produce a renderable clip.",
                stage="scene_assembly",
                affected_scenes=[index],
            )
        clip, metadata, code = asset
        clips.append(clip)
        scene_results.append(metadata)
        scene_codes.append(code)

    final_mp4 = job_dir / "video.mp4"
    final_vtt = job_dir / "video.vtt"
    try:
        _concat_clips(clips, final_mp4, logs_dir)
        _apply_final_watermark(final_mp4, logs_dir)
        _write_vtt_from_plan(plan, final_vtt)
    except Exception as exc:
        raise StructuredVideoFailure(
            f"Final video assembly failed: {exc}",
            stage="final_video_assembly",
        ) from exc

    scene_bundle = _bundle_for_scene_code(plan, scene_codes, raw_plan)
    (job_dir / "scene_bundle.txt").write_text(scene_bundle, encoding="utf-8")
    diagnostics = _build_generation_diagnostics(
        plan,
        provider_name=provider_name,
        model=model,
        metrics=metrics,
    )
    used_fallback = bool(metrics.get("component_fallback_scene_ids"))
    if metrics.get("recovery_stages") or metrics.get("component_fallback_scene_ids"):
        _flush_response_debug_contexts(metrics, logs_dir)
        _write_scene_diagnostics(metrics, logs_dir)

    _append_audit_and_cleanup(
        job_id=final_job_id,
        plan=plan,
        provider_name=provider_name,
        model=model,
        metrics=metrics,
        failed=False,
        has_final_artifact=True,
    )

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
        "plan_repaired": bool(metrics.get("plan_repaired_by_model")),
        "generation_diagnostics": diagnostics,
    }


def _new_metrics(operation: str = "generate") -> dict[str, Any]:
    return {
        "operation": operation,
        "_started_monotonic": time.monotonic(),
        "llm_calls": 0,
        "rendered_initially": 0,
        "sanitizer_repaired": 0,
        "render_repaired": 0,
        "simplified_scenes": 0,
        "component_fallbacks": 0,
        "local_sanitizer_corrections": 0,
        "plan_repaired": False,
        "plan_repaired_by_model": False,
        "local_json_plan_repair": False,
        "local_plan_adjustments": [],
        "local_script_adjustments": [],
        "sanitizer_repaired_scene_ids": [],
        "render_repaired_scene_ids": [],
        "simplified_scene_ids": [],
        "component_fallback_scene_ids": [],
        "recovery_stages": [],
        "voice_retry_count": 0,
        "transport_salvages": 0,
        "_response_debug_contexts": [],
        "_debug_contexts_flushed": False,
        "_scene_diagnostics": {},
        "_detail_hashes": {},
    }

def _failure_result(
    *,
    exc: Exception,
    job_id: str,
    provider_name: str | None,
    model: str | None,
    metrics: dict[str, Any],
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    stage = exc.stage if isinstance(exc, StructuredVideoFailure) else "video_generation"
    affected = exc.affected_scenes if isinstance(exc, StructuredVideoFailure) else []
    detail = f"{type(exc).__name__}: {exc}"
    category = (
        exc.error_category
        if isinstance(exc, StructuredVideoFailure) and exc.error_category
        else diagnostic_category(detail)
    )
    retryable = (
        exc.retryable
        if isinstance(exc, StructuredVideoFailure) and exc.retryable is not None
        else diagnostic_retryable(detail)
    )
    during_stage = (
        exc.during_stage if isinstance(exc, StructuredVideoFailure) else stage
    )
    technical_summary = summarize_error(detail, fallback="Structured video generation failed.")
    public_summary = public_error_message(detail)
    diagnostics = _build_generation_diagnostics(
        plan,
        provider_name=provider_name,
        model=model,
        metrics=metrics,
        failed=True,
        failure_stage=stage,
        failure_summary=public_summary,
        error_category=category,
        retryable=retryable,
        during_stage=during_stage,
    )
    job_dir = pathlib.Path(STORAGE) / "jobs" / job_id
    logs_dir = job_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    _flush_response_debug_contexts(metrics, logs_dir)
    _write_scene_diagnostics(metrics, logs_dir)
    (logs_dir / "structured_failure.txt").write_text(detail + "\n", encoding="utf-8")
    (logs_dir / "failure_manifest.json").write_text(
        _safe_json({
            "stage": stage,
            "during_stage": during_stage,
            "error_category": category,
            "retryable": bool(retryable),
            "affected_scenes": affected,
            "llm_calls": int(metrics.get("llm_calls") or 0),
            "voice_retries": int(metrics.get("voice_retry_count") or 0),
            "summary": technical_summary,
        }),
        encoding="utf-8",
    )
    _append_audit_and_cleanup(
        job_id=job_id,
        plan=plan,
        provider_name=provider_name,
        model=model,
        metrics=metrics,
        failed=True,
        failure_stage=stage,
        during_stage=during_stage,
        error_category=category,
        retryable=retryable,
        affected_scenes=affected,
        error_summary=technical_summary,
        has_final_artifact=False,
    )
    logger.exception("structured_video_failed job_id=%s stage=%s category=%s", job_id, stage, category)
    return {
        "ok": False,
        "status": "error",
        "error": "structured_video_failed",
        "error_detail": detail,
        "error_category": category,
        "retryable": bool(retryable),
        "during_stage": during_stage,
        "job_id": job_id,
        "video_url": None,
        "scene_results": [],
        "generation_diagnostics": diagnostics,
    }

def generate_structured_manim_video(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    final_job_id = str(job_id or uuid.uuid4().hex[:12])
    metrics = _new_metrics("generate")
    plan: dict[str, Any] | None = None
    provider_name: str | None = provider
    resolved_model: str | None = model
    try:
        provider_name, api_key = _pick_provider_and_key(provider, provider_keys)
        resolved_model = str(model or get_default_model(provider_name) or "").strip() or None
        preflight_error = _runtime_preflight_result(
            final_job_id=final_job_id,
            provider_name=provider_name,
            model=resolved_model,
            metrics=metrics,
        )
        if preflight_error is not None:
            return preflight_error

        job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
        logs_dir = job_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "structured_manim_generation_start job_id=%s provider=%s model=%s mode=complete_scripts",
            final_job_id,
            provider_name,
            resolved_model,
        )
        metrics["llm_calls"] += 1
        raw = call_llm(
            provider=provider_name,
            api_key=api_key,
            model=resolved_model,
            system=STRUCTURED_VIDEO_SYSTEM,
            user=build_structured_video_user_prompt(prompt),
            temperature=0.28,
            max_tokens=_INITIAL_MAX_TOKENS,
        )
        raw_text = _coerce_llm_text(raw)
        parsed, scripts, bodies, plan_text, repaired_plan_text, plan_was_repaired = (
            _parse_structured_response(raw_text)
        )
        if plan_was_repaired:
            metrics["local_json_plan_repair"] = True
        _remember_response_debug_context(
            metrics,
            prefix="structured",
            raw_text=raw_text,
            plan_text=plan_text,
            scripts=scripts,
            legacy_bodies=bodies,
            repaired_plan_text=repaired_plan_text,
            plan_was_repaired=plan_was_repaired,
        )
        parsed = _attach_manim_code(parsed, scripts, bodies)
        plan = _normalize_plan(parsed, topic=prompt)
        plan, repaired = _repair_plan_if_needed(
            plan,
            topic=prompt,
            provider_name=provider_name,
            api_key=api_key,
            model=resolved_model,
            logs_dir=logs_dir,
            metrics=metrics,
        )
        metrics["plan_repaired"] = False
        metrics["plan_repaired_by_model"] = False
        return _render_structured_plan(
            plan,
            provider_name=provider_name,
            api_key=api_key,
            model=resolved_model,
            final_job_id=final_job_id,
            raw_plan=raw_text,
            metrics=metrics,
        )
    except Exception as exc:
        return _failure_result(
            exc=exc,
            job_id=final_job_id,
            provider_name=provider_name,
            model=resolved_model,
            metrics=metrics,
            plan=plan,
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
    final_job_id = str(job_id or uuid.uuid4().hex[:12])
    metrics = _new_metrics("edit")
    plan: dict[str, Any] | None = None
    provider_name: str | None = provider
    resolved_model: str | None = model
    try:
        original_plan = parse_plan_from_scene_bundle(original_bundle, topic="Edited video")
        provider_name, api_key = _pick_provider_and_key(provider, provider_keys)
        resolved_model = str(model or get_default_model(provider_name) or "").strip() or None
        preflight_error = _runtime_preflight_result(
            final_job_id=final_job_id,
            provider_name=provider_name,
            model=resolved_model,
            metrics=metrics,
        )
        if preflight_error is not None:
            return preflight_error

        job_dir = pathlib.Path(STORAGE) / "jobs" / final_job_id
        logs_dir = job_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        metrics["llm_calls"] += 1
        raw = call_llm(
            provider=provider_name,
            api_key=api_key,
            model=resolved_model,
            system=STRUCTURED_VIDEO_EDIT_SYSTEM,
            user=build_structured_video_edit_user_prompt(original_plan, edit_instructions),
            temperature=0.18,
            max_tokens=_INITIAL_MAX_TOKENS,
        )
        raw_text = _coerce_llm_text(raw)
        parsed, scripts, bodies, plan_text, repaired_plan_text, plan_was_repaired = (
            _parse_structured_response(raw_text)
        )
        if plan_was_repaired:
            metrics["local_json_plan_repair"] = True
        _remember_response_debug_context(
            metrics,
            prefix="structured_edit",
            raw_text=raw_text,
            plan_text=plan_text,
            scripts=scripts,
            legacy_bodies=bodies,
            repaired_plan_text=repaired_plan_text,
            plan_was_repaired=plan_was_repaired,
        )
        parsed = _attach_manim_code(parsed, scripts, bodies)
        parsed = _inherit_missing_scene_fields(parsed, original_plan)
        plan = _normalize_plan(parsed, topic=str(original_plan.get("title") or "Edited video"))
        plan, repaired = _repair_plan_if_needed(
            plan,
            topic=str(original_plan.get("title") or "Edited video"),
            provider_name=provider_name,
            api_key=api_key,
            model=resolved_model,
            logs_dir=logs_dir,
            metrics=metrics,
        )
        metrics["plan_repaired"] = False
        metrics["plan_repaired_by_model"] = False
        return _render_structured_plan(
            plan,
            provider_name=provider_name,
            api_key=api_key,
            model=resolved_model,
            final_job_id=final_job_id,
            raw_plan=raw_text,
            metrics=metrics,
        )
    except Exception as exc:
        return _failure_result(
            exc=exc,
            job_id=final_job_id,
            provider_name=provider_name,
            model=resolved_model,
            metrics=metrics,
            plan=plan,
        )
