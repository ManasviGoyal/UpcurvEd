# backend/mcp/story_video_logic.py
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any

from backend.agent.llm.clients import call_llm
from backend.agent.llm.provider_config import (
    resolve_provider_and_key as _pick_provider_and_key,
)
from backend.agent.prompts import ARTIFACT_SAFETY_INSTRUCTION
from backend.runner.job_runner import STORAGE, to_static_url

logger = logging.getLogger(f"app.{__name__}")

THEME_PRESETS: dict[str, dict[str, str]] = {
    "space": {
        "bg0": "#040b2a",
        "bg1": "#0b1e4b",
        "panel": "rgba(10,18,44,0.72)",
        "accent": "#70d7ff",
        "glow": "#79a6ff",
    },
    "jungle": {
        "bg0": "#0b2b1b",
        "bg1": "#164d2f",
        "panel": "rgba(10,40,22,0.74)",
        "accent": "#9df27c",
        "glow": "#55d86b",
    },
    "ocean": {
        "bg0": "#06243b",
        "bg1": "#0a4868",
        "panel": "rgba(4,34,56,0.76)",
        "accent": "#80e6ff",
        "glow": "#53c9ff",
    },
    "city_lab": {
        "bg0": "#111a2f",
        "bg1": "#20345d",
        "panel": "rgba(18,26,48,0.76)",
        "accent": "#b7c8ff",
        "glow": "#8bb0ff",
    },
    "sunset_farm": {
        "bg0": "#3a1c2a",
        "bg1": "#f08c6b",
        "panel": "rgba(38,18,30,0.74)",
        "accent": "#ffd166",
        "glow": "#ff9f7a",
    },
    "meadow": {
        "bg0": "#1f3c2a",
        "bg1": "#6fcf97",
        "panel": "rgba(18,38,26,0.74)",
        "accent": "#c5f277",
        "glow": "#7ee081",
    },
}

HOST_PRESETS: dict[str, dict[str, str]] = {
    "scientist": {
        "kind": "scientist",
        "label": "Scientist Guide",
        "body": "#f2c9a2",
        "accent": "#4f79ff",
        "outfit": "#f7fbff",
    },
    "friendly_robot": {
        "kind": "robot",
        "label": "Robot Guide",
        "body": "#9ab7e9",
        "accent": "#6cf0ff",
        "outfit": "#cfe3ff",
    },
    "animal_guide": {
        "kind": "animal",
        "label": "Animal Guide",
        "body": "#d8c8a8",
        "accent": "#8b6b43",
        "outfit": "#5b4631",
    },
    "explorer": {
        "kind": "explorer",
        "label": "Explorer Guide",
        "body": "#f2c9a2",
        "accent": "#f59e0b",
        "outfit": "#1f2937",
    },
    "artist": {
        "kind": "artist",
        "label": "Artist Guide",
        "body": "#f1c6a8",
        "accent": "#ec4899",
        "outfit": "#fdf2f8",
    },
    "athlete": {
        "kind": "athlete",
        "label": "Athlete Guide",
        "body": "#f0c7a0",
        "accent": "#22c55e",
        "outfit": "#0f172a",
    },
}

_VISUAL_STRATEGIES = (
    "environment_scene",
    "object_simulation",
    "diagram",
    "map_path",
    "timeline",
    "before_after",
    "split_screen",
    "chart",
    "equation_transform",
    "balance_model",
    "probability_tree",
    "cycle",
)
_DEFAULT_VISUAL_SEQUENCE = (
    "environment_scene",
    "object_simulation",
    "map_path",
    "chart",
    "equation_transform",
    "probability_tree",
)
_HOST_ROLES = {"lead", "small_guide", "observer", "absent"}

DRAW_JS_BUNDLE_SYSTEM = f"""{ARTIFACT_SAFETY_INSTRUCTION}

Create concise Canvas drawing bodies for all six scenes of one educational story.
Return no JSON, markdown, explanation, or code fences.

Output exactly one tagged block per scene:
<SCENE_DRAW id="1">
JavaScript body statements only
</SCENE_DRAW>
...
<SCENE_DRAW id="6">
JavaScript body statements only
</SCENE_DRAW>

The runtime already creates a function with these arguments:
x, w, h, dt,
drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar, drawCharacterTemplate,
drawLabel, drawEquation, drawArrow, drawPanel, drawRoute, drawFractionCircle,
drawBarChart, drawMeasurement.

Reliability rules:
- Return body statements only. Do not return function(...), an arrow function, imports, HTML, or JSON.
- Do not define nested functions or arrow functions. Use the supplied helpers instead.
- Do not use fetch, network, DOM access, window, document, storage, eval, Function,
  requestAnimationFrame, setTimeout, setInterval, clearRect, fillText, or strokeText.
- Use quoted strings, not template literals. Close every quote, bracket, brace, and parenthesis.
- Keep each scene about 18-55 lines and under 5,500 characters.
- Use relative positions based on w and h. Small pixel constants for line widths and padding are fine.
- The runtime paints the background. Do not cover the entire canvas with another full-screen rectangle.

Creative rules:
- Follow each scene's visual_strategy and animation_goal.
- Make the topic visualization occupy most of the canvas.
- A guide character is optional. Follow host_role: lead, small_guide, observer, or absent.
- A speech bubble is optional. Use zero or one, only when it improves the story.
- Use drawLabel and drawEquation for essential educational text.
- Use dt for one to three meaningful movements, such as travel, rotation, pouring, growth,
  changing quantities, transforming an equation, or revealing an outcome.
- Make consecutive scenes visibly different in composition and visual strategy.
"""


def _story_prompt(topic: str, host_character: str | None = None, theme: str | None = None) -> str:
    host_options = ", ".join(sorted(HOST_PRESETS.keys()))
    theme_options = ", ".join(sorted(THEME_PRESETS.keys()))
    host_line = f"Main character preference: {host_character}\n" if host_character else ""
    theme_line = f"Visual theme preference: {theme}\n" if theme else ""
    strategies = ", ".join(_VISUAL_STRATEGIES)
    return (
        f"Educational story for children about: {topic}\n"
        f"Available main characters: {host_options}\n"
        f"Available visual themes: {theme_options}\n"
        f"Available visual strategies: {strategies}\n"
        f"{host_line}"
        f"{theme_line}"
        "Return ONLY one strict JSON object, no markdown or comments. "
        "Use double quotes and include every required comma.\n"
        "{"
        "\"title\":\"...\","
        "\"audience\":\"children ages 8-12\","
        "\"characters\":[\"...\"],"
        "\"science_big_idea\":\"one accurate core learning idea\","
        "\"key_vocabulary\":[\"term\",\"term\",\"term\"],"
        "\"misconception_to_fix\":\"common misconception, if relevant\","
        "\"moral\":\"specific learning takeaway\","
        "\"conclusion\":\"curiosity question or practical takeaway\","
        "\"scenes\":[{"
        "\"heading\":\"...\","
        "\"lesson\":\"1-2 accurate sentences explaining the idea\","
        "\"science_fact\":\"specific accurate fact, rule, or mechanism\","
        "\"vocabulary\":[\"term\",\"term\"],"
        "\"cause_effect\":\"cause -> effect or input -> result\","
        "\"misconception_fix\":\"optional correction\","
        "\"caption\":\"short narrator line with concrete learning\","
        "\"speech_bubble\":\"optional, max 8 words\","
        "\"visual\":\"specific drawable visual description\","
        "\"visual_strategy\":\"one available strategy\","
        "\"host_role\":\"lead | small_guide | observer | absent\","
        "\"essential_labels\":[\"short label\",\"short equation or value\"],"
        "\"animation_goal\":\"one visible change over time\","
        "\"duration_sec\":10"
        "}]}\n"
        "Rules: exactly 6 scenes, each exactly 10 seconds. "
        "Use at least four different visual strategies and never repeat one in consecutive scenes. "
        "Let the learning visual dominate; do not place the same character beside the same table in every scene. "
        "Use characters in some scenes but allow diagrams, maps, charts, object transformations, and equations to stand alone. "
        "Each scene must teach one concrete idea through a specific real-world situation, mechanism, comparison, measurement, or worked example. "
        "Choose essential_labels that can be displayed directly, including useful numbers, units, fractions, equations, or short names. "
        "Avoid unsupported precision. If exact numbers vary, say about or give a range. "
        "If the topic includes a named character, keep that name consistent."
    )


def _story_json_candidate(raw: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Story model returned no complete JSON object.")
    return text[start : end + 1]


def _remove_story_trailing_commas(text: str) -> str:
    output: list[str] = []
    quote = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            output.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quote = False
            i += 1
            continue
        if ch == '"':
            quote = True
            output.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1
                continue
        output.append(ch)
        i += 1
    return "".join(output)


def _repair_story_json_punctuation(candidate: str, max_edits: int = 10) -> str:
    repaired = _remove_story_trailing_commas(candidate)
    for _ in range(max_edits):
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ',' delimiter":
                break
            current = exc.pos
            while current < len(repaired) and repaired[current].isspace():
                current += 1
            previous = current - 1
            while previous >= 0 and repaired[previous].isspace():
                previous -= 1
            if current >= len(repaired) or previous < 0:
                break
            current_char = repaired[current]
            previous_char = repaired[previous]
            starts_value = current_char in '"{[-' or current_char.isdigit() or current_char in "tfn"
            ends_value = previous_char in '"}]' or previous_char.isdigit()
            if not starts_value or not ends_value:
                break
            repaired = repaired[:current] + "," + repaired[current:]
    return repaired


def _extract_json(raw: str) -> dict[str, Any]:
    candidate = _story_json_candidate(raw)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as original_error:
        repaired = _repair_story_json_punctuation(candidate)
        if repaired != candidate:
            try:
                parsed = json.loads(repaired)
                logger.warning("story_plan_json_repaired_locally original_error=%s", original_error)
            except json.JSONDecodeError:
                raise RuntimeError(f"Story model returned malformed JSON: {original_error}") from original_error
        else:
            raise RuntimeError(f"Story model returned malformed JSON: {original_error}") from original_error
    if not isinstance(parsed, dict):
        raise RuntimeError("Story model must return one JSON object.")
    return parsed


def _compact_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _normalize_terms(value: Any, limit: int = 4) -> list[str]:
    terms: list[str] = []
    if isinstance(value, list):
        for item in value:
            txt = _compact_text(item, 32)
            if txt and txt.lower() not in {t.lower() for t in terms}:
                terms.append(txt)
            if len(terms) >= limit:
                break
    elif isinstance(value, str):
        for item in re.split(r"[,;]", value):
            txt = _compact_text(item, 32)
            if txt and txt.lower() not in {t.lower() for t in terms}:
                terms.append(txt)
            if len(terms) >= limit:
                break
    return terms


def _short_bubble(value: Any, fallback: str) -> str:
    text = _compact_text(value, 80) or _compact_text(fallback, 80) or "Watch the mechanism"
    words = re.findall(r"[A-Za-z0-9%+-]+", text)
    if not words:
        return "Watch the mechanism"
    return " ".join(words[:8])


def _science_caption(scene: dict[str, Any], lesson: str) -> str:
    fact = _compact_text(scene.get("science_fact"), 180)
    cause = _compact_text(scene.get("cause_effect"), 150)
    caption = _compact_text(scene.get("caption"), 180)
    if fact and cause:
        return f"{fact} {cause}"[:220]
    if fact:
        return fact
    if caption:
        return caption
    return lesson[:220]


def _default_science_scenes(topic: str) -> list[dict[str, Any]]:
    topic_txt = _compact_text(topic, 60) or "this topic"
    return [
        {
            "heading": "Observe the system",
            "lesson": f"Scientists start by asking what parts make {topic_txt} work.",
            "science_fact": f"{topic_txt} can be understood by looking at parts, patterns, and changes.",
            "vocabulary": ["system", "pattern"],
            "cause_effect": "Careful observation reveals what changes and what stays stable.",
            "misconception_fix": "",
            "caption": f"Look for the parts and patterns in {topic_txt}.",
            "speech_bubble": "Look for the pattern",
            "visual": "Scientist guide points to a simple system diagram with colored parts and arrows.",
            "duration_sec": 10,
        },
        {
            "heading": "Find the mechanism",
            "lesson": f"A mechanism explains how one step in {topic_txt} leads to the next.",
            "science_fact": "A mechanism is a chain of cause and effect.",
            "vocabulary": ["mechanism", "cause", "effect"],
            "cause_effect": "One change triggers another change.",
            "misconception_fix": "",
            "caption": "A mechanism connects causes to effects.",
            "speech_bubble": "Cause leads to effect",
            "visual": "Arrows connect three glowing objects from left to right.",
            "duration_sec": 10,
        },
        {
            "heading": "Measure the change",
            "lesson": f"Many science ideas become clearer when we compare before and after states.",
            "science_fact": "Comparing states helps reveal evidence.",
            "vocabulary": ["evidence", "measurement"],
            "cause_effect": "Measurement turns observations into evidence.",
            "misconception_fix": "",
            "caption": "Compare before and after to see evidence.",
            "speech_bubble": "Evidence shows change",
            "visual": "Before and after panels show an object changing with a small chart.",
            "duration_sec": 10,
        },
        {
            "heading": "Use a model",
            "lesson": f"A model is a simplified picture that helps explain {topic_txt}.",
            "science_fact": "Models are useful because they show invisible or complex processes.",
            "vocabulary": ["model", "process"],
            "cause_effect": "A good model shows how the parts interact.",
            "misconception_fix": "",
            "caption": "Models make invisible processes easier to see.",
            "speech_bubble": "Models show hidden steps",
            "visual": "Guide moves small particles through a simple model with arrows.",
            "duration_sec": 10,
        },
        {
            "heading": "Fix a misconception",
            "lesson": f"A strong explanation of {topic_txt} separates what is true from what only sounds true.",
            "science_fact": "Scientific claims should match evidence and mechanisms.",
            "vocabulary": ["claim", "evidence"],
            "cause_effect": "Better evidence improves the explanation.",
            "misconception_fix": "Do not accept a simple story if it misses the mechanism.",
            "caption": "A claim is stronger when evidence supports it.",
            "speech_bubble": "Check the evidence",
            "visual": "Two signs appear; the guide chooses the one connected to evidence dots.",
            "duration_sec": 10,
        },
        {
            "heading": "Apply the idea",
            "lesson": f"Once we understand {topic_txt}, we can use it to make better predictions.",
            "science_fact": "Scientific understanding helps us predict what may happen next.",
            "vocabulary": ["prediction", "application"],
            "cause_effect": "Knowing the mechanism helps predict the outcome.",
            "misconception_fix": "",
            "caption": "Use the mechanism to make a prediction.",
            "speech_bubble": "Predict the next step",
            "visual": "A path of arrows leads from question to model to prediction.",
            "duration_sec": 10,
        },
    ]


def _normalize_story_plan(plan: dict[str, Any], topic: str) -> dict[str, Any]:
    title = _compact_text(plan.get("title") or f"{topic} Story", 80)
    characters_in = plan.get("characters")
    characters: list[str] = []
    if isinstance(characters_in, list):
        for item in characters_in[:5]:
            txt = _compact_text(item, 40)
            if txt:
                characters.append(txt)

    science_big_idea = _compact_text(plan.get("science_big_idea"), 260)
    key_vocabulary = _normalize_terms(plan.get("key_vocabulary"), limit=6)
    misconception_to_fix = _compact_text(plan.get("misconception_to_fix"), 220)
    moral = _compact_text(plan.get("moral") or plan.get("takeaway"), 240)
    conclusion = _compact_text(plan.get("conclusion"), 240)

    scenes_in = plan.get("scenes")
    if not isinstance(scenes_in, list):
        scenes_in = []

    scenes: list[dict[str, Any]] = []
    for i, s in enumerate(scenes_in[:6], start=1):
        if not isinstance(s, dict):
            continue
        heading = _compact_text(s.get("heading") or f"Scene {i}", 60)
        lesson = _compact_text(s.get("lesson"), 260)
        science_fact = _compact_text(s.get("science_fact"), 220)
        cause_effect = _compact_text(s.get("cause_effect"), 180)
        misconception_fix = _compact_text(s.get("misconception_fix"), 180)
        visual = _compact_text(s.get("visual"), 420)
        vocabulary = _normalize_terms(s.get("vocabulary"), limit=4)
        visual_strategy = str(s.get("visual_strategy") or "").strip().lower()
        if visual_strategy not in _VISUAL_STRATEGIES:
            visual_strategy = _DEFAULT_VISUAL_SEQUENCE[(i - 1) % len(_DEFAULT_VISUAL_SEQUENCE)]
        host_role = str(s.get("host_role") or "").strip().lower()
        if host_role not in _HOST_ROLES:
            host_role = ("lead", "small_guide", "absent", "observer", "small_guide", "absent")[(i - 1) % 6]
        essential_labels = _normalize_terms(s.get("essential_labels"), limit=4)
        animation_goal = _compact_text(s.get("animation_goal"), 180)

        if not lesson:
            lesson = science_fact or f"This scene explains one important idea about {topic}."
        if not science_fact:
            science_fact = lesson
        if not visual:
            visual = "A topic-specific visual model with changing objects, labels, and a clear relationship."
        if not animation_goal:
            animation_goal = "Reveal the relationship by changing one meaningful quantity or position."

        caption = _science_caption(s, lesson)
        speech_bubble = _short_bubble(s.get("speech_bubble"), heading) if s.get("speech_bubble") else ""

        scenes.append(
            {
                "id": i,
                "heading": heading,
                "lesson": lesson,
                "science_fact": science_fact,
                "vocabulary": vocabulary,
                "cause_effect": cause_effect,
                "misconception_fix": misconception_fix,
                "caption": caption,
                "speech_bubble": speech_bubble,
                "visual": visual,
                "visual_strategy": visual_strategy,
                "host_role": host_role,
                "essential_labels": essential_labels,
                "animation_goal": animation_goal,
                "duration_sec": 10,
            }
        )

    if len(scenes) < 6:
        defaults = _default_science_scenes(topic)
        for fallback in defaults:
            if len(scenes) >= 6:
                break
            idx = len(scenes) + 1
            fallback = dict(fallback)
            fallback.update(
                {
                    "id": idx,
                    "visual_strategy": _DEFAULT_VISUAL_SEQUENCE[(idx - 1) % len(_DEFAULT_VISUAL_SEQUENCE)],
                    "host_role": ("lead", "small_guide", "absent", "observer", "small_guide", "absent")[(idx - 1) % 6],
                    "essential_labels": list(fallback.get("vocabulary") or [])[:3],
                    "animation_goal": "Reveal the relationship through one visible change.",
                }
            )
            scenes.append(fallback)

    # Preserve valid model choices but deterministically prevent repetitive layouts.
    used: set[str] = set()
    for idx, scene in enumerate(scenes[:6]):
        strategy = str(scene.get("visual_strategy") or "")
        previous = str(scenes[idx - 1].get("visual_strategy") or "") if idx else ""
        if strategy == previous:
            strategy = next(
                candidate
                for candidate in _DEFAULT_VISUAL_SEQUENCE
                if candidate != previous and candidate not in used
            )
            scene["visual_strategy"] = strategy
        used.add(strategy)
    if len(used) < 4:
        for idx, strategy in enumerate(_DEFAULT_VISUAL_SEQUENCE[:4]):
            scenes[idx]["visual_strategy"] = strategy

    if not characters:
        characters = ["Guide", "Curious Learner"]
    if not science_big_idea:
        science_big_idea = f"Understanding {topic} means connecting real situations to patterns, quantities, and cause/effect."
    if not key_vocabulary:
        for scene in scenes:
            for term in scene.get("vocabulary", []):
                if term and term.lower() not in {t.lower() for t in key_vocabulary}:
                    key_vocabulary.append(term)
                if len(key_vocabulary) >= 6:
                    break
            if len(key_vocabulary) >= 6:
                break
    if not key_vocabulary:
        key_vocabulary = ["pattern", "quantity", "relationship"]
    if not moral:
        moral = f"Learning takeaway: {science_big_idea}"
    if not conclusion:
        conclusion = f"What example of {topic} can you notice or test today?"

    return {
        "title": title,
        "audience": "children ages 8-12",
        "characters": characters,
        "science_big_idea": science_big_idea,
        "key_vocabulary": key_vocabulary,
        "misconception_to_fix": misconception_to_fix,
        "moral": moral,
        "conclusion": conclusion,
        "scenes": scenes[:6],
    }


def _find_ffmpeg() -> str:
    for key in ("UPCURVED_FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"):
        val = (os.getenv(key) or "").strip()
        if val and pathlib.Path(val).exists():
            return val
    which = shutil.which("ffmpeg")
    if which:
        return which
    raise RuntimeError("ffmpeg not found for story mode rendering.")


def _pick_theme(theme: str | None, visual: str) -> str:
    t = (theme or "").strip().lower().replace(" ", "_")
    if t in THEME_PRESETS:
        return t
    return "city_lab"


def _pick_host(host_character: str | None) -> str:
    h = (host_character or "").strip().lower().replace(" ", "_")
    if h in HOST_PRESETS:
        return h
    return "friendly_robot"


def _resolve_host_payload(host_character: str | None) -> dict[str, str]:
    host_key = _pick_host(host_character)
    if host_key in HOST_PRESETS:
        return HOST_PRESETS[host_key]
    return HOST_PRESETS["friendly_robot"]


def _matching_outer_brace(text: str, open_index: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    i = open_index
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in {"'", '"'}:
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _clean_draw_js(raw: str) -> str:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"^```(?:javascript|js)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    wrapper = re.match(r"^(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\([^)]*\)\s*\{", text)
    if not wrapper:
        wrapper = re.match(r"^\([^)]*\)\s*=>\s*\{", text)
    if wrapper:
        open_index = text.find("{", wrapper.start())
        close_index = _matching_outer_brace(text, open_index)
        if close_index > open_index and not text[close_index + 1 :].strip().strip(";"):
            text = text[open_index + 1 : close_index].strip()
    return text


def _extract_scene_draw_sections(raw: str) -> dict[int, str]:
    pattern = re.compile(
        r"<SCENE_DRAW\b(?P<attrs>[^>]*)>(?P<body>.*?)</SCENE_DRAW\s*>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    output: dict[int, str] = {}
    for match in pattern.finditer(str(raw or "")):
        attrs = match.group("attrs")
        id_match = re.search(r"\bid\s*=\s*(?:\"(\d+)\"|'(\d+)'|(\d+))", attrs, flags=re.IGNORECASE)
        if not id_match:
            continue
        scene_id = int(next(group for group in id_match.groups() if group))
        body = _clean_draw_js(match.group("body"))
        if body:
            output[scene_id] = body
    return output


def _validate_draw_js(body: str) -> tuple[bool, str]:
    text = str(body or "").strip()
    if not text:
        return False, "empty drawing body"
    if len(text) > 5500 or len(text.splitlines()) > 90:
        return False, "drawing body is too long"
    lowered = text.lower()
    forbidden = (
        "fetch(", "xmlhttprequest", "websocket", "localstorage", "sessionstorage",
        "document.", "window.", "eval(", "new function", "requestanimationframe",
        "settimeout", "setinterval", "clearrect", ".filltext(", ".stroketext(",
        "import ", "require(", "process.", "function(", "function ", "=>", "`",
    )
    if any(token in lowered for token in forbidden):
        return False, "drawing body uses a forbidden or unreliable construct"
    if not re.search(
        r"\b(?:drawCharacterTemplate|drawLabel|drawEquation|drawArrow|drawPanel|drawRoute|"
        r"drawFractionCircle|drawBarChart|drawMeasurement|drawCloud|drawGround|drawStar)\s*\(|"
        r"\bx\.(?:beginPath|fillRect|strokeRect|arc|ellipse|lineTo|moveTo|bezierCurveTo|quadraticCurveTo)\s*\(",
        text,
    ):
        return False, "drawing body contains no visible drawing action"

    stack: list[str] = []
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    pairs = {')': '(', ']': '[', '}': '{'}
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in {"'", '"'}:
            quote = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack.pop() != pairs[ch]:
                return False, "unbalanced JavaScript delimiters"
        i += 1
    if quote or block_comment or stack:
        return False, "unclosed JavaScript quote, comment, or delimiter"
    return True, ""


def _story_draw_bundle_prompt(
    plan: dict[str, Any],
    *,
    host_character: str | None,
    theme: str | None,
) -> str:
    scenes = []
    for idx, scene in enumerate(plan.get("scenes") or [], start=1):
        scenes.append(
            {
                "id": idx,
                "heading": scene.get("heading"),
                "lesson": scene.get("lesson"),
                "visual": scene.get("visual"),
                "visual_strategy": scene.get("visual_strategy"),
                "host_role": scene.get("host_role"),
                "essential_labels": scene.get("essential_labels"),
                "animation_goal": scene.get("animation_goal"),
                "speech_bubble": scene.get("speech_bubble"),
            }
        )
    payload = {
        "story_title": plan.get("title"),
        "host_character": host_character or "friendly_robot",
        "theme": theme or "city_lab",
        "scenes": scenes,
    }
    return (
        "Create all six distinct scene drawing bodies from this compact story plan. "
        "Return exactly six SCENE_DRAW blocks in scene order.\n"
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    )


def _js_text(value: Any, fallback: str = "") -> str:
    return json.dumps(_compact_text(value, 70) or fallback, ensure_ascii=True)


def _deterministic_scene_js(
    scene: dict[str, Any],
    *,
    index: int,
    host_character: str | None,
) -> str:
    strategy = str(scene.get("visual_strategy") or _DEFAULT_VISUAL_SEQUENCE[(index - 1) % 6])
    labels = list(scene.get("essential_labels") or scene.get("vocabulary") or [])
    while len(labels) < 3:
        labels.append(("Input", "Change", "Result")[len(labels)])
    label0, label1, label2 = (_js_text(labels[0]), _js_text(labels[1]), _js_text(labels[2]))
    bubble = _js_text(scene.get("speech_bubble"), "Notice the pattern")
    host = _js_text(host_character or "friendly_robot")
    role = str(scene.get("host_role") or "small_guide")
    guide = ""
    if role != "absent":
        guide_x = "w*0.18" if role in {"lead", "observer"} else "w*0.1"
        guide_scale = "0.95" if role == "lead" else "0.72"
        guide = f"drawCharacterTemplate(x,{guide_x},h*0.82,{guide_scale},{host},Math.sin(dt*2)*4);\n"
        if scene.get("speech_bubble") and role == "lead":
            guide += f"drawSpeechBubble(x,{guide_x},h*0.55,{bubble},15);\n"

    common = "const pulse=0.5+0.5*Math.sin(dt*2);\n"
    if strategy == "map_path":
        body = f"""{common}{guide}drawPanel(x,w*0.22,h*0.16,w*0.68,h*0.58,'rgba(255,255,255,0.08)','#93c5fd');
const pts=[[w*0.28,h*0.68],[w*0.43,h*0.48],[w*0.58,h*0.62],[w*0.78,h*0.34]];
drawRoute(x,pts,'#fbbf24',4);
const t=(Math.sin(dt*0.8)+1)/2;
const px=pts[0][0]+(pts[3][0]-pts[0][0])*t;
const py=pts[0][1]+(pts[3][1]-pts[0][1])*t;
x.fillStyle='#fb7185'; x.beginPath(); x.arc(px,py,8,0,Math.PI*2); x.fill();
drawLabel(x,w*0.3,h*0.72,{label0},15,'#e2e8f0');
drawLabel(x,w*0.72,h*0.28,{label1},15,'#e2e8f0');
drawArrow(x,w*0.42,h*0.72,w*0.63,h*0.72,'#67e8f9',3);
drawMeasurement(x,w*0.42,h*0.76,w*0.63,h*0.76,{label2},'#67e8f9');"""
    elif strategy in {"equation_transform", "balance_model"}:
        body = f"""{common}{guide}drawPanel(x,w*0.26,h*0.18,w*0.62,h*0.58,'rgba(15,23,42,0.72)','#a78bfa');
const shift=Math.min(1,dt/4);
drawEquation(x,w*0.57,h*0.34,{label0},30,'#f8fafc');
drawArrow(x,w*0.48,h*0.46,w*0.66,h*0.46,'#fbbf24',4);
drawEquation(x,w*0.57,h*0.58,{label1},32,'#86efac');
x.strokeStyle='#c4b5fd'; x.lineWidth=5; x.beginPath(); x.moveTo(w*0.42,h*0.68); x.lineTo(w*0.72,h*0.68); x.stroke();
x.fillStyle='#60a5fa'; x.fillRect(w*(0.43+0.05*shift),h*0.62,42,42);
x.fillStyle='#fb7185'; x.beginPath(); x.arc(w*(0.7-0.05*shift),h*0.64,21,0,Math.PI*2); x.fill();
drawLabel(x,w*0.57,h*0.75,{label2},16,'#ddd6fe');"""
    elif strategy == "probability_tree":
        body = f"""{common}{guide}drawPanel(x,w*0.25,h*0.14,w*0.66,h*0.62,'rgba(255,255,255,0.06)','#f9a8d4');
const sx=w*0.38, sy=h*0.4;
x.fillStyle='#f8fafc'; x.beginPath(); x.arc(sx,sy,10,0,Math.PI*2); x.fill();
drawArrow(x,sx+10,sy,w*0.58,h*0.3,'#67e8f9',3);
drawArrow(x,sx+10,sy,w*0.58,h*0.5,'#67e8f9',3);
drawArrow(x,w*0.59,h*0.3,w*0.76,h*(0.24+0.03*pulse),'#fbbf24',3);
drawArrow(x,w*0.59,h*0.5,w*0.76,h*(0.56-0.03*pulse),'#fbbf24',3);
drawLabel(x,w*0.36,h*0.34,{label0},15,'#e2e8f0');
drawLabel(x,w*0.62,h*0.25,{label1},15,'#e2e8f0');
drawLabel(x,w*0.62,h*0.55,{label2},15,'#e2e8f0');
drawFractionCircle(x,w*0.8,h*0.4,44,2,Math.floor(dt)%2,'#f472b6','#334155');"""
    elif strategy in {"chart", "timeline"}:
        body = f"""{common}{guide}drawPanel(x,w*0.24,h*0.14,w*0.68,h*0.64,'rgba(255,255,255,0.06)','#86efac');
const values=[0.32+0.18*pulse,0.52,0.72-0.12*pulse,0.88];
drawBarChart(x,w*0.32,h*0.68,w*0.48,h*0.38,values,['A','B','C','D'],'#60a5fa');
drawArrow(x,w*0.32,h*0.74,w*0.82,h*0.74,'#fbbf24',3);
drawLabel(x,w*0.34,h*0.8,{label0},14,'#e2e8f0');
drawLabel(x,w*0.57,h*0.8,{label1},14,'#e2e8f0');
drawLabel(x,w*0.78,h*0.8,{label2},14,'#e2e8f0');"""
    elif strategy in {"before_after", "split_screen"}:
        body = f"""{common}{guide}drawPanel(x,w*0.24,h*0.18,w*0.28,h*0.5,'rgba(96,165,250,0.14)','#60a5fa');
drawPanel(x,w*0.62,h*0.18,w*0.28,h*0.5,'rgba(134,239,172,0.14)','#86efac');
drawLabel(x,w*0.38,h*0.25,{label0},17,'#dbeafe');
drawLabel(x,w*0.76,h*0.25,{label1},17,'#dcfce7');
const r1=28+8*pulse, r2=54+10*pulse;
x.fillStyle='#60a5fa'; x.beginPath(); x.arc(w*0.38,h*0.48,r1,0,Math.PI*2); x.fill();
x.fillStyle='#86efac'; x.beginPath(); x.arc(w*0.76,h*0.48,r2,0,Math.PI*2); x.fill();
drawArrow(x,w*0.52,h*0.46,w*0.61,h*0.46,'#fbbf24',4);
drawMeasurement(x,w*0.66,h*0.64,w*0.86,h*0.64,{label2},'#86efac');"""
    elif strategy == "cycle":
        body = f"""{common}{guide}const cx=w*0.58, cy=h*0.46, radius=Math.min(w,h)*0.22;
for(let i=0;i<3;i++){{
  const a=dt*0.25+i*Math.PI*2/3;
  const px=cx+Math.cos(a)*radius, py=cy+Math.sin(a)*radius;
  x.fillStyle=['#60a5fa','#fbbf24','#86efac'][i]; x.beginPath(); x.arc(px,py,28,0,Math.PI*2); x.fill();
}}
drawArrow(x,cx-radius*0.45,cy-radius*0.85,cx+radius*0.45,cy-radius*0.85,'#f8fafc',3);
drawArrow(x,cx+radius*0.85,cy-radius*0.15,cx+radius*0.45,cy+radius*0.75,'#f8fafc',3);
drawArrow(x,cx-radius*0.45,cy+radius*0.75,cx-radius*0.85,cy-radius*0.15,'#f8fafc',3);
drawLabel(x,cx,cy-radius-36,{label0},15,'#e2e8f0');
drawLabel(x,cx+radius+40,cy+20,{label1},15,'#e2e8f0');
drawLabel(x,cx-radius-40,cy+20,{label2},15,'#e2e8f0');"""
    else:
        body = f"""{common}{guide}drawPanel(x,w*0.24,h*0.16,w*0.68,h*0.6,'rgba(255,255,255,0.06)','#7dd3fc');
const cx=w*0.58, cy=h*0.47;
x.fillStyle='#60a5fa'; x.beginPath(); x.arc(cx-w*0.18,cy,34+8*pulse,0,Math.PI*2); x.fill();
x.fillStyle='#fbbf24'; x.beginPath(); x.arc(cx,cy,42-6*pulse,0,Math.PI*2); x.fill();
x.fillStyle='#86efac'; x.beginPath(); x.arc(cx+w*0.18,cy,30+10*pulse,0,Math.PI*2); x.fill();
drawArrow(x,cx-w*0.13,cy,cx-w*0.05,cy,'#f8fafc',4);
drawArrow(x,cx+w*0.05,cy,cx+w*0.13,cy,'#f8fafc',4);
drawLabel(x,cx-w*0.18,cy+70,{label0},15,'#dbeafe');
drawLabel(x,cx,cy+82,{label1},15,'#fef3c7');
drawLabel(x,cx+w*0.18,cy+70,{label2},15,'#dcfce7');"""
    return body.strip()


def _prepare_story_drawings(
    plan: dict[str, Any],
    *,
    provider: str,
    api_key: str,
    model: str | None,
    host_character: str | None,
    theme: str | None,
) -> tuple[list[str], list[str]]:
    parsed_bodies: dict[int, str] = {}
    bundle_error = ""
    try:
        raw = call_llm(
            provider=provider,  # type: ignore[arg-type]
            api_key=api_key,
            model=model,
            system=DRAW_JS_BUNDLE_SYSTEM,
            user=_story_draw_bundle_prompt(
                plan,
                host_character=host_character,
                theme=theme,
            ),
            temperature=0.35,
            max_tokens=7000,
            max_output_tokens=7000,
        )
        parsed_bodies = _extract_scene_draw_sections(raw)
        if not parsed_bodies:
            bundle_error = "visual bundle returned no tagged scene bodies"
    except Exception as exc:
        bundle_error = str(exc) or type(exc).__name__
        logger.exception("story: visual bundle generation failed; using deterministic scene fallbacks")

    primary: list[str] = []
    fallbacks: list[str] = []
    for idx, scene in enumerate(plan.get("scenes") or [], start=1):
        fallback = _deterministic_scene_js(
            scene,
            index=idx,
            host_character=host_character,
        )
        fallbacks.append(fallback)
        candidate = _clean_draw_js(parsed_bodies.get(idx, ""))
        valid, reason = _validate_draw_js(candidate)
        if valid:
            primary.append(candidate)
            scene["draw_status"] = "custom"
            scene["draw_error"] = ""
            logger.info("story: scene %d custom drawing accepted strategy=%s", idx, scene.get("visual_strategy"))
        else:
            primary.append(fallback)
            scene["draw_status"] = "deterministic_fallback"
            scene["draw_error"] = reason or bundle_error or "missing drawing body"
            logger.warning(
                "story: scene %d using deterministic fallback strategy=%s reason=%s",
                idx,
                scene.get("visual_strategy"),
                scene["draw_error"],
            )
    return primary, fallbacks


def _build_scene_template_html(
    scene: dict[str, Any],
    host_payload: dict[str, str],
    scene_js: str,
    fallback_js: str,
    theme: str | None = None,
) -> str:
    theme_key = _pick_theme(theme, str(scene.get("visual") or ""))
    payload = {
        "heading": str(scene.get("heading") or "Story Scene"),
        "lesson": str(scene.get("lesson") or ""),
        "caption": str(scene.get("caption") or scene.get("science_fact") or scene.get("lesson") or ""),
        "science_fact": str(scene.get("science_fact") or ""),
        "vocabulary": list(scene.get("vocabulary") or []),
        "cause_effect": str(scene.get("cause_effect") or ""),
        "misconception_fix": str(scene.get("misconception_fix") or ""),
        "speech_bubble": str(scene.get("speech_bubble") or ""),
        "visual": str(scene.get("visual") or ""),
        "visual_strategy": str(scene.get("visual_strategy") or "diagram"),
        "host_role": str(scene.get("host_role") or "small_guide"),
        "essential_labels": list(scene.get("essential_labels") or []),
        "animation_goal": str(scene.get("animation_goal") or ""),
        "draw_status": str(scene.get("draw_status") or "custom"),
        "duration_sec": int(scene.get("duration_sec") or 10),
        "theme": THEME_PRESETS[theme_key],
        "host": host_payload,
    }
    payload_json = json.dumps(payload, ensure_ascii=True)
    scene_js_json = json.dumps(scene_js or "", ensure_ascii=True)
    fallback_js_json = json.dumps(fallback_js or "", ensure_ascii=True)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }}
    canvas {{ display: block; width: 100vw; height: 100vh; }}
  </style>
</head>
<body>
  <canvas id="c"></canvas>
  <script>
    const S = {payload_json};
    const SCENE_DRAW_JS = {scene_js_json};
    const FALLBACK_DRAW_JS = {fallback_js_json};
    const c = document.getElementById('c');
    const x = c.getContext('2d');
        let drawSceneFn = null;
        let fallbackDrawFn = null;
        const DRAW_ARGS = [
            'x', 'w', 'h', 'dt',
            'drawCharacter', 'drawCloud', 'drawGround', 'drawSpeechBubble', 'drawStar',
            'drawCharacterTemplate', 'drawLabel', 'drawEquation', 'drawArrow', 'drawPanel',
            'drawRoute', 'drawFractionCircle', 'drawBarChart', 'drawMeasurement'
        ];
    try {{
      if (SCENE_DRAW_JS && SCENE_DRAW_JS.trim()) {{
                drawSceneFn = new Function(...DRAW_ARGS, SCENE_DRAW_JS);
      }}
    }} catch (e) {{
      drawSceneFn = null;
    }}
    try {{
      if (FALLBACK_DRAW_JS && FALLBACK_DRAW_JS.trim()) {{
                fallbackDrawFn = new Function(...DRAW_ARGS, FALLBACK_DRAW_JS);
      }}
    }} catch (e) {{
      fallbackDrawFn = null;
    }}
        let w = 0, h = 0;
    function rs() {{
      c.width = Math.max(960, window.innerWidth);
      c.height = Math.max(540, window.innerHeight);
      w = c.width; h = c.height;
    }}
    window.addEventListener('resize', rs);
    rs();
    const start = performance.now();
        function drawCharacter(ctx, cx, cy, scale, headColor, bodyColor, eyeColor, mouthUp, bobAmt) {{
            const s = scale || 1;
            const hy = cy;
            ctx.lineCap = 'round';
            // Legs
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 8*s;
            ctx.beginPath(); ctx.moveTo(cx - 8*s, hy - 42*s); ctx.lineTo(cx - 10*s, hy - 8*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 8*s, hy - 42*s); ctx.lineTo(cx + 10*s, hy - 8*s); ctx.stroke();
            // Shoes
            ctx.fillStyle = '#3a3a3a';
            ctx.beginPath(); ctx.ellipse(cx - 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Torso (rounded)
            ctx.fillStyle = bodyColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 66*s, 22*s, 28*s, 0, 0, Math.PI*2); ctx.fill();
            // Arms
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 7*s;
            ctx.beginPath(); ctx.moveTo(cx - 22*s, hy - 78*s); ctx.quadraticCurveTo(cx - 38*s, hy - 68*s, cx - 36*s, hy - 52*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 22*s, hy - 78*s); ctx.quadraticCurveTo(cx + 38*s, hy - 68*s, cx + 36*s, hy - 52*s); ctx.stroke();
            // Hands
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.arc(cx - 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            // Neck
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 96*s, 6*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Head
            ctx.beginPath(); ctx.arc(cx, hy - 112*s, 24*s, 0, Math.PI*2); ctx.fill();
            // Eyes (sclera + pupil)
            ctx.fillStyle = '#fff';
            ctx.beginPath(); ctx.ellipse(cx - 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.fillStyle = eyeColor || '#222';
            ctx.beginPath(); ctx.arc(cx - 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            // Mouth
            ctx.beginPath();
            if (mouthUp) {{
                // Smile
                ctx.arc(cx, hy - 108*s, 6*s, 0, Math.PI);
            }} else {{
                // Frown
                ctx.arc(cx, hy - 102*s, 6*s, Math.PI, 0);
            }}
            ctx.strokeStyle = '#555';
            ctx.lineWidth = 1.5*s;
            ctx.stroke();
        }}
        function drawCloud(ctx, cx, cy, cw) {{
            ctx.fillStyle = 'rgba(255,255,255,0.92)';
            ctx.beginPath(); ctx.arc(cx, cy, cw*0.28, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.22, cy + cw*0.04, cw*0.22, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.22, cy + cw*0.06, cw*0.2, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.08, cy + cw*0.15, cw*0.24, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.08, cy - cw*0.08, cw*0.18, 0, Math.PI*2); ctx.fill();
        }}
        function drawGround(ctx, w2, h2, groundY, grassColor, dirtColor) {{
            ctx.fillStyle = dirtColor || '#8B6543';
            ctx.fillRect(0, groundY, w2, h2 - groundY);
            ctx.fillStyle = grassColor || '#4a7c3f';
            ctx.fillRect(0, groundY, w2, 14);
        }}
        function drawSpeechBubble(ctx, cx, cy, text, fontSize) {{
            const fs = fontSize || 16;
            const maxW = Math.min(w * 0.5, 280);
            ctx.font = '600 ' + fs + 'px Arial';
            const words = String(text || '').split(/\\s+/).filter(Boolean);
            const lines = [];
            let line = '';
            for (const wd of words) {{
                const t = line ? line + ' ' + wd : wd;
                if (ctx.measureText(t).width > maxW && line) {{
                    lines.push(line);
                    line = wd;
                }} else line = t;
            }}
            if (line) lines.push(line);
            const safeLines = lines.slice(0, 3);
            const widths = safeLines.map((l) => ctx.measureText(l).width);
            const textW = widths.length ? Math.max(...widths) : 0;
            const pad = 16;
            const bw = Math.min(maxW, textW) + pad * 2;
            const lineH = fs + 6;
            const bh = safeLines.length * lineH + pad;
            const margin = 8;
            let bx = cx - bw / 2;
            let by = cy - bh - 14;
            if (by < margin) by = margin;
            if (bx < margin) bx = margin;
            if (bx + bw > w - margin) bx = w - margin - bw;
            const textCx = bx + bw / 2;
            const ptrCx = Math.max(bx + 12, Math.min(cx, bx + bw - 12));
            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,0.18)';
            ctx.shadowBlur = 8;
            ctx.shadowOffsetY = 3;
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.fill();
            ctx.restore();
            ctx.strokeStyle = 'rgba(0,0,0,0.08)'; ctx.lineWidth = 1;
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.stroke();
            ctx.fillStyle = '#1e293b';
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            safeLines.forEach((ln, i) => {{
                ctx.fillText(ln, textCx, by + pad / 2 + i * lineH);
            }});
            ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            ctx.moveTo(ptrCx - 8, by + bh);
            ctx.lineTo(ptrCx + 8, by + bh);
            ctx.lineTo(ptrCx, by + bh + 12);
            ctx.closePath(); ctx.fill();
        }}
        function drawStar(ctx, cx, cy, r, color) {{
            ctx.fillStyle = color || '#ffd700';
            ctx.beginPath();
            for (let i = 0; i < 10; i++) {{
                const a = (i * Math.PI / 5) - Math.PI/2;
                const rad = i % 2 === 0 ? r : r * 0.4;
                if (i === 0) ctx.moveTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
                else ctx.lineTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
            }}
            ctx.closePath(); ctx.fill();
        }}
        function drawLabel(ctx, cx, cy, text, fontSize, color) {{
            ctx.save();
            ctx.fillStyle = color || '#f8fafc';
            ctx.font = '600 ' + (fontSize || 16) + 'px Arial';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(String(text || '').slice(0, 40), cx, cy);
            ctx.restore();
        }}
        function drawEquation(ctx, cx, cy, text, fontSize, color) {{
            ctx.save();
            ctx.fillStyle = 'rgba(15,23,42,0.82)';
            const fs = fontSize || 26;
            ctx.font = '700 ' + fs + 'px Arial';
            const label = String(text || '').slice(0, 55);
            const width = Math.min(w * 0.72, ctx.measureText(label).width + 28);
            const height = fs + 24;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(cx - width/2, cy - height/2, width, height, 10);
            else ctx.rect(cx - width/2, cy - height/2, width, height);
            ctx.fill();
            ctx.fillStyle = color || '#f8fafc';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(label, cx, cy);
            ctx.restore();
        }}
        function drawArrow(ctx, x1, y1, x2, y2, color, lineWidth) {{
            const angle = Math.atan2(y2-y1, x2-x1);
            const head = 10 + (lineWidth || 3);
            ctx.save(); ctx.strokeStyle = color || '#f8fafc'; ctx.fillStyle = color || '#f8fafc';
            ctx.lineWidth = lineWidth || 3; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x2,y2);
            ctx.lineTo(x2-head*Math.cos(angle-Math.PI/6), y2-head*Math.sin(angle-Math.PI/6));
            ctx.lineTo(x2-head*Math.cos(angle+Math.PI/6), y2-head*Math.sin(angle+Math.PI/6));
            ctx.closePath(); ctx.fill(); ctx.restore();
        }}
        function drawPanel(ctx, px, py, pw, ph, fill, stroke) {{
            ctx.save(); ctx.fillStyle = fill || 'rgba(255,255,255,0.08)';
            ctx.strokeStyle = stroke || 'rgba(255,255,255,0.25)'; ctx.lineWidth = 2;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(px, py, pw, ph, 16); else ctx.rect(px, py, pw, ph);
            ctx.fill(); ctx.stroke(); ctx.restore();
        }}
        function drawRoute(ctx, points, color, lineWidth) {{
            if (!Array.isArray(points) || points.length < 2) return;
            ctx.save(); ctx.strokeStyle = color || '#fbbf24'; ctx.lineWidth = lineWidth || 4;
            ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.beginPath();
            ctx.moveTo(points[0][0], points[0][1]);
            for (let i=1;i<points.length;i++) ctx.lineTo(points[i][0], points[i][1]);
            ctx.stroke(); ctx.restore();
        }}
        function drawFractionCircle(ctx, cx, cy, radius, parts, active, activeColor, baseColor) {{
            const count = Math.max(2, Math.min(12, Number(parts || 4)));
            for (let i=0;i<count;i++) {{
                const a0 = -Math.PI/2 + i*Math.PI*2/count;
                const a1 = -Math.PI/2 + (i+1)*Math.PI*2/count;
                ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,radius,a0,a1); ctx.closePath();
                ctx.fillStyle = i === active ? (activeColor || '#fbbf24') : (baseColor || '#334155');
                ctx.fill(); ctx.strokeStyle = '#f8fafc'; ctx.lineWidth = 2; ctx.stroke();
            }}
        }}
        function drawBarChart(ctx, px, baseline, pw, ph, values, labels, color) {{
            const vals = Array.isArray(values) ? values : [];
            const gap = pw / Math.max(1, vals.length);
            vals.forEach((value, i) => {{
                const v = Math.max(0, Math.min(1, Number(value || 0)));
                const bh = ph * v;
                ctx.fillStyle = color || '#60a5fa';
                ctx.fillRect(px + i*gap + gap*0.18, baseline-bh, gap*0.64, bh);
                if (labels && labels[i]) drawLabel(ctx, px+i*gap+gap*0.5, baseline+18, labels[i], 12, '#e2e8f0');
            }});
            ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(px,baseline); ctx.lineTo(px+pw,baseline); ctx.stroke();
        }}
        function drawMeasurement(ctx, x1, y1, x2, y2, label, color) {{
            const c = color || '#67e8f9';
            ctx.save(); ctx.strokeStyle = c; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x1,y1-7); ctx.lineTo(x1,y1+7); ctx.moveTo(x2,y2-7); ctx.lineTo(x2,y2+7); ctx.stroke();
            drawLabel(ctx,(x1+x2)/2,(y1+y2)/2-14,label,13,c); ctx.restore();
        }}
        function drawCharacterTemplate(ctx, cx, cy, scale, variant, bobAmt) {{
            const v = String(variant || 'friendly_robot');
            const templates = {{
                scientist: {{ head: '#f2c9a2', body: '#f7fbff', eye: '#1f2937', accent: '#4f79ff' }},
                friendly_robot: {{ head: '#b0d4f1', body: '#e0efff', eye: '#0f172a', accent: '#6cf0ff' }},
                animal_guide: {{ head: '#e0caa8', body: '#6b5640', eye: '#1f2937', accent: '#8b6b43' }},
                explorer: {{ head: '#f2c9a2', body: '#2d3748', eye: '#111827', accent: '#f59e0b' }},
                artist: {{ head: '#f1c6a8', body: '#fdf2f8', eye: '#111827', accent: '#ec4899' }},
                athlete: {{ head: '#f0c7a0', body: '#1a202c', eye: '#111827', accent: '#22c55e' }},
            }};
            const t = templates[v] || templates.friendly_robot;
            drawCharacter(ctx, cx, cy, scale, t.head, t.body, t.eye, true, bobAmt);
            const s = scale || 1;
            if (v === 'scientist') {{
                // Glasses
                ctx.strokeStyle = t.accent; ctx.lineWidth = 2 * s;
                ctx.beginPath(); ctx.arc(cx - 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.arc(cx + 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(cx - 1*s, cy - 116*s); ctx.lineTo(cx + 1*s, cy - 116*s); ctx.stroke();
                // Lab coat collar
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 94*s, 24*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'friendly_robot') {{
                // Antenna
                ctx.strokeStyle = '#888'; ctx.lineWidth = 2*s;
                ctx.beginPath(); ctx.moveTo(cx, cy - 136*s); ctx.lineTo(cx, cy - 148*s); ctx.stroke();
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.arc(cx, cy - 150*s, 4*s, 0, Math.PI*2); ctx.fill();
                // Visor band
                ctx.fillStyle = 'rgba(108,240,255,0.3)';
                ctx.beginPath(); ctx.ellipse(cx, cy - 116*s, 18*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'animal_guide') {{
                // Ears
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 128*s, 8*s, 12*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 128*s, 8*s, 12*s, 0.3, 0, Math.PI*2); ctx.fill();
                ctx.fillStyle = '#f0c0a0';
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 126*s, 4*s, 7*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 126*s, 4*s, 7*s, 0.3, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'explorer') {{
                // Hat
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 134*s, 28*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
                ctx.fillRect(cx - 14*s, cy - 146*s, 28*s, 14*s);
            }} else if (v === 'artist') {{
                // Beret
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx + 2*s, cy - 132*s, 20*s, 10*s, 0.2, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.arc(cx + 2*s, cy - 142*s, 3*s, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'athlete') {{
                // Headband
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 128*s, 26*s, 4*s, 0, 0, Math.PI*2); ctx.fill();
            }}
        }}
        function drawFallbackAnimated(tSec) {{
            const cx = w * 0.5;
            const cy = h * 0.48;
            const bob = Math.sin(tSec * 2.2) * 6;
            const arm = Math.sin(tSec * 3.1) * 8;
            const head = Math.sin(tSec * 1.7) * 0.08;
            x.save();
            x.translate(cx, cy + bob);
            x.rotate(head);
            x.fillStyle = '#e2e8f0';
            x.fillRect(-26, -10, 52, 60);
            x.fillStyle = '#0f172a';
            x.fillRect(-18, 10, 36, 40);
            x.fillStyle = '#fcd34d';
            x.beginPath(); x.arc(0, -28, 22, 0, Math.PI * 2); x.fill();
            x.fillStyle = '#111827';
            x.beginPath(); x.arc(-7, -30, 2.2, 0, Math.PI * 2); x.arc(7, -30, 2.2, 0, Math.PI * 2); x.fill();
            x.strokeStyle = '#111827'; x.lineWidth = 2;
            x.beginPath(); x.arc(0, -24, 7, 0.1, Math.PI - 0.1); x.stroke();
            x.strokeStyle = '#fcd34d'; x.lineWidth = 6;
            x.beginPath(); x.moveTo(-22, 0); x.lineTo(-40, 6 + arm); x.stroke();
            x.beginPath(); x.moveTo(22, 0); x.lineTo(40, 6 - arm); x.stroke();
            x.fillStyle = '#334155';
            x.beginPath(); x.ellipse(-12, 54, 12, 5, 0, 0, Math.PI * 2); x.fill();
            x.beginPath(); x.ellipse(12, 54, 12, 5, 0, 0, Math.PI * 2); x.fill();
            x.restore();

            const tableY = h * 0.62 + Math.sin(tSec * 1.3) * 2;
            x.fillStyle = '#6b4f34';
            x.fillRect(cx - 140, tableY, 280, 18);
            x.fillStyle = '#5a3f28';
            x.fillRect(cx - 120, tableY + 18, 16, 32);
            x.fillRect(cx + 104, tableY + 18, 16, 32);
            x.fillStyle = '#eab308';
            x.beginPath(); x.arc(cx - 40, tableY - 10, 12, 0, Math.PI * 2); x.fill();
            x.fillStyle = '#f97316';
            x.beginPath(); x.arc(cx + 30, tableY - 12, 10, 0, Math.PI * 2); x.fill();
        }}
    function tick(t) {{
      const dt = (t - start) / 1000;
      const g = x.createLinearGradient(0,0,0,h);
      g.addColorStop(0, S.theme.bg0); g.addColorStop(1, S.theme.bg1);
      x.fillStyle = g; x.fillRect(0,0,w,h);
            if (drawSceneFn) {{
                try {{
                    drawSceneFn(x, w, h, dt, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar,
                        drawCharacterTemplate, drawLabel, drawEquation, drawArrow, drawPanel, drawRoute,
                        drawFractionCircle, drawBarChart, drawMeasurement);
                }} catch (e) {{
                    if (fallbackDrawFn) fallbackDrawFn(x, w, h, dt, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar,
                        drawCharacterTemplate, drawLabel, drawEquation, drawArrow, drawPanel, drawRoute,
                        drawFractionCircle, drawBarChart, drawMeasurement);
                    else drawFallbackAnimated(dt);
                }}
            }} else if (fallbackDrawFn) {{
                fallbackDrawFn(x, w, h, dt, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar,
                    drawCharacterTemplate, drawLabel, drawEquation, drawArrow, drawPanel, drawRoute,
                    drawFractionCircle, drawBarChart, drawMeasurement);
            }} else {{
                drawFallbackAnimated(dt);
            }}
      // Bottom-of-canvas info bar
      const barH = 80;
      const barY = h - barH;
      x.fillStyle = S.theme.panel || 'rgba(0,0,0,0.55)';
      x.fillRect(0, barY, w, barH);
      x.fillStyle = '#ffffff';
      x.font = '700 20px Arial';
      x.textAlign = 'center';
      x.textBaseline = 'top';
      x.fillText(String(S.heading || '').slice(0, 60), w / 2, barY + 12);
      x.font = '400 15px Arial';
      x.fillStyle = 'rgba(255,255,255,0.82)';
      const capText = String(S.caption || S.science_fact || S.lesson || '').slice(0, 140);
      x.fillText(capText, w / 2, barY + 40);
      x.textAlign = 'left';
      x.textBaseline = 'alphabetic';
      requestAnimationFrame(tick);
    }}
    requestAnimationFrame(tick);
  </script>
</body>
</html>"""


def _render_html_to_clip(
    html: str,
    out_path: pathlib.Path,
    duration_sec: int,
    ffmpeg_bin: str,
    fps: int = 24,
) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from e

    def _candidate_roots() -> list[pathlib.Path]:
        roots: list[pathlib.Path] = []
        env_root = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
        if env_root:
            roots.append(pathlib.Path(env_root))
        home = pathlib.Path.home()
        roots.extend(
            [
                home / ".cache" / "ms-playwright",
                home / "Library" / "Caches" / "ms-playwright",
            ]
        )
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            roots.append(pathlib.Path(local_app_data) / "ms-playwright")
        seen: set[str] = set()
        deduped: list[pathlib.Path] = []
        for r in roots:
            k = str(r)
            if k in seen:
                continue
            seen.add(k)
            deduped.append(r)
        return deduped

    def _find_browser_executable() -> str | None:
        names_by_platform = {
            "linux": ["chrome-headless-shell", "chrome"],
            "darwin": ["Chromium", "chrome", "chrome-headless-shell"],
            "win32": ["chrome.exe", "chrome-headless-shell.exe"],
        }
        names = names_by_platform.get(sys.platform, ["chrome", "chrome-headless-shell"])
        candidates: list[pathlib.Path] = []
        for root in _candidate_roots():
            if not root.exists():
                continue
            for name in names:
                candidates.extend(root.rglob(name))
        candidates = [p for p in candidates if p.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])

    def _install_playwright_browser_default_cache() -> None:
        env = dict(os.environ)
        # Ensure install goes to default per-user cache in dev fallback.
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )

    frames_dir = out_path.parent / f"frames_{out_path.stem}"
    frames_dir.mkdir(exist_ok=True)
    total_frames = duration_sec * fps

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as launch_err:
                err_txt = str(launch_err)
                if "Executable doesn't exist" not in err_txt:
                    raise
                pw_env = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
                logger.warning(
                    "story: playwright launch failed at PLAYWRIGHT_BROWSERS_PATH=%s; trying explicit executable fallback",
                    pw_env,
                )
                exe = _find_browser_executable()
                if exe:
                    logger.info("story: launching playwright with explicit executable %s", exe)
                    browser = pw.chromium.launch(executable_path=exe)
                else:
                    logger.warning("story: no local playwright browser found, installing chromium to default cache")
                    _install_playwright_browser_default_cache()
                    exe2 = _find_browser_executable()
                    if not exe2:
                        raise RuntimeError(
                            "Playwright browser executable missing after install. "
                            "Run: python -m playwright install chromium"
                        )
                    browser = pw.chromium.launch(executable_path=exe2)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(html, wait_until="domcontentloaded")
            page.wait_for_timeout(200)

            for i in range(total_frames):
                page.evaluate(f"window._frameTime = {(i / fps) * 1000}")
                screenshot = page.screenshot(type="png")
                (frames_dir / f"frame_{i:05d}.png").write_bytes(screenshot)
                page.wait_for_timeout(int(1000 / fps))

            browser.close()

        cmd = [
            ffmpeg_bin,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg frame encode failed: {proc.stderr[-600:]}")
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _format_vtt_ts(total_sec: float) -> str:
    ms = int((total_sec % 1) * 1000)
    sec = int(total_sec) % 60
    minute = (int(total_sec) // 60) % 60
    hour = int(total_sec) // 3600
    return f"{hour:02d}:{minute:02d}:{sec:02d}.{ms:03d}"


def _write_vtt(job_dir: pathlib.Path, scenes: list[dict[str, Any]], out_name: str) -> pathlib.Path:
    vtt_path = job_dir / out_name
    lines = ["WEBVTT", ""]
    t = 0.0
    for idx, scene in enumerate(scenes, start=1):
        dur = float(scene["duration_sec"])
        start = _format_vtt_ts(t)
        end = _format_vtt_ts(t + dur)
        lines.append(f"{start} --> {end}")
        caption = str(scene.get("caption") or scene.get("science_fact") or scene.get("lesson") or "").strip()
        lines.append(f"{scene['heading']}: {caption}")
        lines.append("")
        t += dur
    vtt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return vtt_path


def generate_story_video(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    story_options: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    from uuid import uuid4

    prov, key = _pick_provider_and_key(provider, provider_keys)
    options = story_options or {}
    host_character = str(options.get("host_character") or "").strip() or None
    theme = str(options.get("theme") or "").strip() or None
    raw = call_llm(
        provider=prov,
        api_key=key,
        model=model,
        system=ARTIFACT_SAFETY_INSTRUCTION,
        user=_story_prompt(prompt, host_character=host_character, theme=theme),
        temperature=0.45,
        max_tokens=3800,
    )
    plan = _normalize_story_plan(_extract_json(raw), prompt)
    host_payload = _resolve_host_payload(host_character)
    draw_js_by_scene, fallback_js_by_scene = _prepare_story_drawings(
        plan,
        provider=prov,
        api_key=key,
        model=model,
        host_character=host_character,
        theme=theme,
    )

    ffmpeg_bin = _find_ffmpeg()
    jid = job_id or str(uuid4())[:8]
    job_dir = STORAGE / "jobs" / jid
    out_dir = job_dir / "out"
    logs_dir = job_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    clips: list[pathlib.Path] = []
    for idx, scene in enumerate(plan["scenes"], start=1):
        clip = out_dir / f"scene_{idx:02d}.mp4"
        try:
            logger.info(
                "story: rendering template scene %d/%d — %s",
                idx,
                len(plan["scenes"]),
                scene["heading"],
            )
            scene_js = draw_js_by_scene[idx - 1]
            fallback_js = fallback_js_by_scene[idx - 1]
            scene_html = _build_scene_template_html(
                scene,
                host_payload=host_payload,
                scene_js=scene_js,
                fallback_js=fallback_js,
                theme=theme,
            )
        except Exception:
            logger.exception("story: scene template generation failed at index=%d heading=%s", idx, scene.get("heading"))
            raise
        _render_html_to_clip(
            html=scene_html,
            out_path=clip,
            duration_sec=int(scene["duration_sec"]),
            ffmpeg_bin=ffmpeg_bin,
        )
        clips.append(clip)

    concat_file = out_dir / "concat.txt"
    concat_file.write_text(
        "\n".join([f"file '{c.as_posix()}'" for c in clips]) + "\n", encoding="utf-8"
    )
    final_mp4 = out_dir / "final.mp4"
    concat_cmd = [
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
    proc = subprocess.run(concat_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Re-encode fallback if stream-copy concat fails.
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
            str(final_mp4),
        ]
        proc2 = subprocess.run(reencode_cmd, capture_output=True, text=True)
        if proc2.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {proc2.stderr[-800:]}")

    vtt_path = _write_vtt(out_dir, plan["scenes"], "final.vtt")
    (logs_dir / "story_plan.json").write_text(json.dumps(plan, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "job_id": jid,
        "video_url": to_static_url(final_mp4),
        "vtt_url": to_static_url(vtt_path),
        "story_plan": plan,
    }


def _build_story_slider_html(
    plan: dict[str, Any],
    *,
    host_payload: dict[str, str],
    draw_js_by_scene: list[str],
    fallback_js_by_scene: list[str],
    theme: str | None = None,
) -> str:
    scenes_payload: list[dict[str, Any]] = []
    for idx, scene in enumerate(plan.get("scenes", [])):
        scene_theme = THEME_PRESETS[_pick_theme(theme, str(scene.get("visual") or ""))]
        scenes_payload.append(
            {
                "heading": str(scene.get("heading") or f"Scene {idx + 1}"),
                "caption": str(scene.get("caption") or scene.get("science_fact") or scene.get("lesson") or ""),
                "lesson": str(scene.get("lesson") or ""),
                "science_fact": str(scene.get("science_fact") or ""),
                "vocabulary": list(scene.get("vocabulary") or []),
                "cause_effect": str(scene.get("cause_effect") or ""),
                "misconception_fix": str(scene.get("misconception_fix") or ""),
                "speech_bubble": str(scene.get("speech_bubble") or ""),
                "visual": str(scene.get("visual") or ""),
                "visual_strategy": str(scene.get("visual_strategy") or "diagram"),
                "host_role": str(scene.get("host_role") or "small_guide"),
                "essential_labels": list(scene.get("essential_labels") or []),
                "animation_goal": str(scene.get("animation_goal") or ""),
                "draw_status": str(scene.get("draw_status") or "custom"),
                "duration_sec": int(scene.get("duration_sec") or 10),
                "theme": scene_theme,
                "draw_js": draw_js_by_scene[idx] if idx < len(draw_js_by_scene) else "",
                "fallback_js": fallback_js_by_scene[idx] if idx < len(fallback_js_by_scene) else "",
            }
        )
    payload = {
        "title": str(plan.get("title") or "Story"),
        "moral": str(plan.get("moral") or ""),
        "conclusion": str(plan.get("conclusion") or ""),
        "host": host_payload,
        "scenes": scenes_payload,
    }
    payload_json = json.dumps(payload, ensure_ascii=True)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #050b1f; color: #fff; overflow: hidden; font-family: Arial, sans-serif; }}
    .wrap {{ display: grid; grid-template-rows: minmax(0, 1fr) auto; width: 100%; height: 100%; }}
    .viz {{ position: relative; min-width: 0; min-height: 0; }}
    #c {{ width: 100%; height: 100%; display: block; }}
    .panel {{ background: rgba(8, 14, 34, 0.94); border-top: 1px solid rgba(255,255,255,0.12); padding: 12px 14px; display: grid; grid-template-columns: 1.3fr 1fr auto; gap: 12px; align-items: start; }}
    .title {{ font-size: 24px; font-weight: 700; margin: 0 0 6px 0; }}
    .row {{ display: flex; align-items: center; gap: 8px; }}
    .meta {{ font-size: 13px; color: #bfdbfe; margin-bottom: 6px; }}
    .caption {{ font-size: 14px; line-height: 1.4; color: #e2e8f0; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 10px; }}
    .dots {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; background: rgba(255,255,255,0.28); border: 0; cursor: pointer; }}
    .dot.active {{ background: #7dd3fc; }}
    .controls {{ display: flex; gap: 8px; align-items: center; justify-content: flex-end; min-width: 130px; }}
    button {{ border: 1px solid rgba(255,255,255,0.25); background: rgba(255,255,255,0.08); color: #fff; padding: 8px 10px; border-radius: 8px; cursor: pointer; }}
    button:hover {{ background: rgba(255,255,255,0.14); }}
    input[type="range"] {{ width: 100%; margin-top: 4px; }}
    .footer {{ font-size: 12px; color: #cbd5e1; padding-top: 6px; }}
    .col-main {{ min-width: 0; }}
    .col-nav {{ min-width: 0; }}
    @media (max-width: 920px) {{
      .panel {{ grid-template-columns: 1fr; gap: 10px; }}
      .controls {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="viz" id="viz"><canvas id="c"></canvas></div>
    <aside class="panel">
      <div class="col-main">
        <h2 class="title" id="storyTitle">Story</h2>
        <div class="row meta">
          <strong id="sceneLabel">Scene 1</strong>
          <span>•</span>
          <span id="sceneHeading">Loading...</span>
        </div>
        <div class="caption" id="sceneCaption">...</div>
        <div class="footer" id="storyFooter"></div>
      </div>
      <div class="col-nav">
        <input id="sceneSlider" type="range" min="1" max="1" step="1" value="1" />
        <div class="dots" id="sceneDots"></div>
      </div>
      <div class="controls">
        <button id="prevBtn" type="button" aria-label="Previous scene">Prev</button>
        <button id="nextBtn" type="button" aria-label="Next scene">Next</button>
      </div>
    </aside>
  </div>
  <script>
    const P = {payload_json};
    const cv = document.getElementById('c');
    const ctx = cv.getContext('2d');
    const viz = document.getElementById('viz');
    const storyTitle = document.getElementById('storyTitle');
    const sceneLabel = document.getElementById('sceneLabel');
    const sceneHeading = document.getElementById('sceneHeading');
    const sceneCaption = document.getElementById('sceneCaption');
    const sceneSlider = document.getElementById('sceneSlider');
    const sceneDots = document.getElementById('sceneDots');
    const storyFooter = document.getElementById('storyFooter');
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
        const scenes = Array.isArray(P.scenes) ? P.scenes : [];
        function drawCharacter(ctx, cx, cy, scale, headColor, bodyColor, eyeColor, mouthUp, bobAmt) {{
            const s = scale || 1;
            const hy = cy;
            ctx.lineCap = 'round';
            // Legs
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 8*s;
            ctx.beginPath(); ctx.moveTo(cx - 8*s, hy - 42*s); ctx.lineTo(cx - 10*s, hy - 8*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 8*s, hy - 42*s); ctx.lineTo(cx + 10*s, hy - 8*s); ctx.stroke();
            // Shoes
            ctx.fillStyle = '#3a3a3a';
            ctx.beginPath(); ctx.ellipse(cx - 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Torso (rounded)
            ctx.fillStyle = bodyColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 66*s, 22*s, 28*s, 0, 0, Math.PI*2); ctx.fill();
            // Arms
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 7*s;
            ctx.beginPath(); ctx.moveTo(cx - 22*s, hy - 78*s); ctx.quadraticCurveTo(cx - 38*s, hy - 68*s, cx - 36*s, hy - 52*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 22*s, hy - 78*s); ctx.quadraticCurveTo(cx + 38*s, hy - 68*s, cx + 36*s, hy - 52*s); ctx.stroke();
            // Hands
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.arc(cx - 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            // Neck
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 96*s, 6*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Head
            ctx.beginPath(); ctx.arc(cx, hy - 112*s, 24*s, 0, Math.PI*2); ctx.fill();
            // Eyes (sclera + pupil)
            ctx.fillStyle = '#fff';
            ctx.beginPath(); ctx.ellipse(cx - 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.fillStyle = eyeColor || '#222';
            ctx.beginPath(); ctx.arc(cx - 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            // Mouth
            ctx.beginPath();
            if (mouthUp) {{
                // Smile
                ctx.arc(cx, hy - 108*s, 6*s, 0, Math.PI);
            }} else {{
                // Frown
                ctx.arc(cx, hy - 102*s, 6*s, Math.PI, 0);
            }}
            ctx.strokeStyle = '#555';
            ctx.lineWidth = 1.5*s;
            ctx.stroke();
        }}
        function drawCloud(ctx, cx, cy, cw) {{
            ctx.fillStyle = 'rgba(255,255,255,0.92)';
            ctx.beginPath(); ctx.arc(cx, cy, cw*0.28, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.22, cy + cw*0.04, cw*0.22, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.22, cy + cw*0.06, cw*0.2, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.08, cy + cw*0.15, cw*0.24, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.08, cy - cw*0.08, cw*0.18, 0, Math.PI*2); ctx.fill();
        }}
        function drawGround(ctx, w2, h2, groundY, grassColor, dirtColor) {{
            ctx.fillStyle = dirtColor || '#8B6543';
            ctx.fillRect(0, groundY, w2, h2 - groundY);
            ctx.fillStyle = grassColor || '#4a7c3f';
            ctx.fillRect(0, groundY, w2, 14);
        }}
        function drawSpeechBubble(ctx, cx, cy, text, fontSize) {{
            const fs = fontSize || 16;
            const maxW = Math.min(w * 0.5, 280);
            ctx.font = '600 ' + fs + 'px Arial';
            const words = String(text || '').split(/\\s+/).filter(Boolean);
            const lines = [];
            let line = '';
            for (const wd of words) {{
                const t = line ? line + ' ' + wd : wd;
                if (ctx.measureText(t).width > maxW && line) {{
                    lines.push(line);
                    line = wd;
                }} else line = t;
            }}
            if (line) lines.push(line);
            const safeLines = lines.slice(0, 3);
            const widths = safeLines.map((l) => ctx.measureText(l).width);
            const textW = widths.length ? Math.max(...widths) : 0;
            const pad = 16;
            const bw = Math.min(maxW, textW) + pad * 2;
            const lineH = fs + 6;
            const bh = safeLines.length * lineH + pad;
            const margin = 8;
            let bx = cx - bw / 2;
            let by = cy - bh - 14;
            if (by < margin) by = margin;
            if (bx < margin) bx = margin;
            if (bx + bw > w - margin) bx = w - margin - bw;
            const textCx = bx + bw / 2;
            const ptrCx = Math.max(bx + 12, Math.min(cx, bx + bw - 12));
            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,0.18)';
            ctx.shadowBlur = 8;
            ctx.shadowOffsetY = 3;
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.fill();
            ctx.restore();
            ctx.strokeStyle = 'rgba(0,0,0,0.08)'; ctx.lineWidth = 1;
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.stroke();
            ctx.fillStyle = '#1e293b';
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            safeLines.forEach((ln, i) => {{
                ctx.fillText(ln, textCx, by + pad / 2 + i * lineH);
            }});
            ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            ctx.moveTo(ptrCx - 8, by + bh);
            ctx.lineTo(ptrCx + 8, by + bh);
            ctx.lineTo(ptrCx, by + bh + 12);
            ctx.closePath(); ctx.fill();
        }}
        function drawStar(ctx, cx, cy, r, color) {{
            ctx.fillStyle = color || '#ffd700';
            ctx.beginPath();
            for (let i = 0; i < 10; i++) {{
                const a = (i * Math.PI / 5) - Math.PI/2;
                const rad = i % 2 === 0 ? r : r * 0.4;
                if (i === 0) ctx.moveTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
                else ctx.lineTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
            }}
            ctx.closePath(); ctx.fill();
        }}
        function drawLabel(ctx, cx, cy, text, fontSize, color) {{
            ctx.save();
            ctx.fillStyle = color || '#f8fafc';
            ctx.font = '600 ' + (fontSize || 16) + 'px Arial';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(String(text || '').slice(0, 40), cx, cy);
            ctx.restore();
        }}
        function drawEquation(ctx, cx, cy, text, fontSize, color) {{
            ctx.save();
            ctx.fillStyle = 'rgba(15,23,42,0.82)';
            const fs = fontSize || 26;
            ctx.font = '700 ' + fs + 'px Arial';
            const label = String(text || '').slice(0, 55);
            const width = Math.min(w * 0.72, ctx.measureText(label).width + 28);
            const height = fs + 24;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(cx - width/2, cy - height/2, width, height, 10);
            else ctx.rect(cx - width/2, cy - height/2, width, height);
            ctx.fill();
            ctx.fillStyle = color || '#f8fafc';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(label, cx, cy);
            ctx.restore();
        }}
        function drawArrow(ctx, x1, y1, x2, y2, color, lineWidth) {{
            const angle = Math.atan2(y2-y1, x2-x1);
            const head = 10 + (lineWidth || 3);
            ctx.save(); ctx.strokeStyle = color || '#f8fafc'; ctx.fillStyle = color || '#f8fafc';
            ctx.lineWidth = lineWidth || 3; ctx.lineCap = 'round';
            ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x2,y2);
            ctx.lineTo(x2-head*Math.cos(angle-Math.PI/6), y2-head*Math.sin(angle-Math.PI/6));
            ctx.lineTo(x2-head*Math.cos(angle+Math.PI/6), y2-head*Math.sin(angle+Math.PI/6));
            ctx.closePath(); ctx.fill(); ctx.restore();
        }}
        function drawPanel(ctx, px, py, pw, ph, fill, stroke) {{
            ctx.save(); ctx.fillStyle = fill || 'rgba(255,255,255,0.08)';
            ctx.strokeStyle = stroke || 'rgba(255,255,255,0.25)'; ctx.lineWidth = 2;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(px, py, pw, ph, 16); else ctx.rect(px, py, pw, ph);
            ctx.fill(); ctx.stroke(); ctx.restore();
        }}
        function drawRoute(ctx, points, color, lineWidth) {{
            if (!Array.isArray(points) || points.length < 2) return;
            ctx.save(); ctx.strokeStyle = color || '#fbbf24'; ctx.lineWidth = lineWidth || 4;
            ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.beginPath();
            ctx.moveTo(points[0][0], points[0][1]);
            for (let i=1;i<points.length;i++) ctx.lineTo(points[i][0], points[i][1]);
            ctx.stroke(); ctx.restore();
        }}
        function drawFractionCircle(ctx, cx, cy, radius, parts, active, activeColor, baseColor) {{
            const count = Math.max(2, Math.min(12, Number(parts || 4)));
            for (let i=0;i<count;i++) {{
                const a0 = -Math.PI/2 + i*Math.PI*2/count;
                const a1 = -Math.PI/2 + (i+1)*Math.PI*2/count;
                ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,radius,a0,a1); ctx.closePath();
                ctx.fillStyle = i === active ? (activeColor || '#fbbf24') : (baseColor || '#334155');
                ctx.fill(); ctx.strokeStyle = '#f8fafc'; ctx.lineWidth = 2; ctx.stroke();
            }}
        }}
        function drawBarChart(ctx, px, baseline, pw, ph, values, labels, color) {{
            const vals = Array.isArray(values) ? values : [];
            const gap = pw / Math.max(1, vals.length);
            vals.forEach((value, i) => {{
                const v = Math.max(0, Math.min(1, Number(value || 0)));
                const bh = ph * v;
                ctx.fillStyle = color || '#60a5fa';
                ctx.fillRect(px + i*gap + gap*0.18, baseline-bh, gap*0.64, bh);
                if (labels && labels[i]) drawLabel(ctx, px+i*gap+gap*0.5, baseline+18, labels[i], 12, '#e2e8f0');
            }});
            ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(px,baseline); ctx.lineTo(px+pw,baseline); ctx.stroke();
        }}
        function drawMeasurement(ctx, x1, y1, x2, y2, label, color) {{
            const c = color || '#67e8f9';
            ctx.save(); ctx.strokeStyle = c; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x1,y1-7); ctx.lineTo(x1,y1+7); ctx.moveTo(x2,y2-7); ctx.lineTo(x2,y2+7); ctx.stroke();
            drawLabel(ctx,(x1+x2)/2,(y1+y2)/2-14,label,13,c); ctx.restore();
        }}
        function drawCharacterTemplate(ctx, cx, cy, scale, variant, bobAmt) {{
            const v = String(variant || 'friendly_robot');
            const templates = {{
                scientist: {{ head: '#f2c9a2', body: '#f7fbff', eye: '#1f2937', accent: '#4f79ff' }},
                friendly_robot: {{ head: '#b0d4f1', body: '#e0efff', eye: '#0f172a', accent: '#6cf0ff' }},
                animal_guide: {{ head: '#e0caa8', body: '#6b5640', eye: '#1f2937', accent: '#8b6b43' }},
                explorer: {{ head: '#f2c9a2', body: '#2d3748', eye: '#111827', accent: '#f59e0b' }},
                artist: {{ head: '#f1c6a8', body: '#fdf2f8', eye: '#111827', accent: '#ec4899' }},
                athlete: {{ head: '#f0c7a0', body: '#1a202c', eye: '#111827', accent: '#22c55e' }},
            }};
            const t = templates[v] || templates.friendly_robot;
            drawCharacter(ctx, cx, cy, scale, t.head, t.body, t.eye, true, bobAmt);
            const s = scale || 1;
            if (v === 'scientist') {{
                ctx.strokeStyle = t.accent; ctx.lineWidth = 2 * s;
                ctx.beginPath(); ctx.arc(cx - 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.arc(cx + 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(cx - 1*s, cy - 116*s); ctx.lineTo(cx + 1*s, cy - 116*s); ctx.stroke();
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 94*s, 24*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'friendly_robot') {{
                ctx.strokeStyle = '#888'; ctx.lineWidth = 2*s;
                ctx.beginPath(); ctx.moveTo(cx, cy - 136*s); ctx.lineTo(cx, cy - 148*s); ctx.stroke();
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.arc(cx, cy - 150*s, 4*s, 0, Math.PI*2); ctx.fill();
                ctx.fillStyle = 'rgba(108,240,255,0.3)';
                ctx.beginPath(); ctx.ellipse(cx, cy - 116*s, 18*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'animal_guide') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 128*s, 8*s, 12*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 128*s, 8*s, 12*s, 0.3, 0, Math.PI*2); ctx.fill();
                ctx.fillStyle = '#f0c0a0';
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 126*s, 4*s, 7*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 126*s, 4*s, 7*s, 0.3, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'explorer') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 134*s, 28*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
                ctx.fillRect(cx - 14*s, cy - 146*s, 28*s, 14*s);
            }} else if (v === 'artist') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx + 2*s, cy - 132*s, 20*s, 10*s, 0.2, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.arc(cx + 2*s, cy - 142*s, 3*s, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'athlete') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 128*s, 26*s, 4*s, 0, 0, Math.PI*2); ctx.fill();
            }}
        }}
        const DRAW_ARGS = [
            'x', 'w', 'h', 'dt',
            'drawCharacter', 'drawCloud', 'drawGround', 'drawSpeechBubble', 'drawStar',
            'drawCharacterTemplate', 'drawLabel', 'drawEquation', 'drawArrow', 'drawPanel',
            'drawRoute', 'drawFractionCircle', 'drawBarChart', 'drawMeasurement'
        ];
        const drawFns = scenes.map((s) => {{
            try {{
                if (s.draw_js && String(s.draw_js).trim()) return new Function(...DRAW_ARGS, s.draw_js);
            }} catch (e) {{}}
            return null;
        }});
        const fallbackFns = scenes.map((s) => {{
            try {{
                if (s.fallback_js && String(s.fallback_js).trim()) return new Function(...DRAW_ARGS, s.fallback_js);
            }} catch (e) {{}}
            return null;
        }});
    storyTitle.textContent = P.title || "Story";
    storyFooter.textContent = "";
    storyFooter.style.display = "none";
    sceneCaption.textContent = P.moral || P.conclusion || "";
    let w = 0, h = 0;
    let current = 0;
    let sceneStart = performance.now();
    function fit() {{
      cv.width = Math.max(800, viz.clientWidth);
      cv.height = Math.max(450, viz.clientHeight);
      w = cv.width; h = cv.height;
    }}
    function setScene(idx) {{
      const n = scenes.length || 1;
      current = ((idx % n) + n) % n;
      sceneStart = performance.now();
      const s = scenes[current] || {{}};
      sceneLabel.textContent = `Scene ${{current + 1}}`;
      sceneHeading.textContent = String(s.heading || P.title || 'Story');
      sceneCaption.textContent = String(s.caption || s.science_fact || s.lesson || '');
      sceneSlider.value = String(current + 1);
      Array.from(sceneDots.children).forEach((el, i) => el.classList.toggle('active', i === current));
    }}
    function initUI() {{
      sceneDots.innerHTML = "";
      sceneSlider.max = String(Math.max(1, scenes.length));
      for (let i = 0; i < scenes.length; i++) {{
        const d = document.createElement('button');
        d.className = 'dot' + (i === 0 ? ' active' : '');
        d.type = 'button';
        d.addEventListener('click', () => setScene(i));
        sceneDots.appendChild(d);
      }}
      prevBtn.addEventListener('click', () => setScene(current - 1));
      nextBtn.addEventListener('click', () => setScene(current + 1));
      sceneSlider.addEventListener('input', () => setScene(Number(sceneSlider.value) - 1));
    }}
    function drawFallbackScene(s, dt) {{
      const pulse = 0.5 + 0.5 * Math.sin(dt * 1.8);
      const boxW = Math.min(w * 0.72, 640);
      const boxH = Math.min(h * 0.36, 280);
      const bx = (w - boxW) / 2;
      const by = (h - boxH) / 2 - 20;
      ctx.fillStyle = 'rgba(7, 12, 28, 0.82)';
      ctx.fillRect(bx, by, boxW, boxH);
      ctx.strokeStyle = 'rgba(125, 211, 252, 0.55)';
      ctx.lineWidth = 2 + pulse;
      ctx.strokeRect(bx, by, boxW, boxH);
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '700 24px Arial';
      ctx.fillText(String(s.heading || 'Scene'), bx + 18, by + 40);
      ctx.font = '500 17px Arial';
      const v = String(s.visual || s.lesson || '').slice(0, 220);
      const words = v.split(/\\s+/);
      let line = '';
      let y = by + 78;
      for (const word of words) {{
        const t = line ? line + ' ' + word : word;
        if (ctx.measureText(t).width > boxW - 36 && line) {{
          ctx.fillText(line, bx + 18, y);
          line = word;
          y += 24;
          if (y > by + boxH - 16) break;
        }} else {{
          line = t;
        }}
      }}
      if (line && y <= by + boxH - 16) ctx.fillText(line, bx + 18, y);
    }}
        function drawFallbackAnimated(dt, theme) {{
            const cx = w * 0.5;
            const cy = h * 0.48;
            const bob = Math.sin(dt * 2.2) * 6;
            const arm = Math.sin(dt * 3.1) * 8;
            const head = Math.sin(dt * 1.7) * 0.08;
            ctx.save();
            ctx.translate(cx, cy + bob);
            ctx.rotate(head);
            ctx.fillStyle = '#e2e8f0';
            ctx.fillRect(-26, -10, 52, 60);
            ctx.fillStyle = theme?.accent || '#60a5fa';
            ctx.fillRect(-18, 10, 36, 40);
            ctx.fillStyle = '#fcd34d';
            ctx.beginPath(); ctx.arc(0, -28, 22, 0, Math.PI * 2); ctx.fill();
            ctx.fillStyle = '#111827';
            ctx.beginPath(); ctx.arc(-7, -30, 2.2, 0, Math.PI * 2); ctx.arc(7, -30, 2.2, 0, Math.PI * 2); ctx.fill();
            ctx.strokeStyle = '#111827'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(0, -24, 7, 0.1, Math.PI - 0.1); ctx.stroke();
            ctx.strokeStyle = '#fcd34d'; ctx.lineWidth = 6;
            ctx.beginPath(); ctx.moveTo(-22, 0); ctx.lineTo(-40, 6 + arm); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(22, 0); ctx.lineTo(40, 6 - arm); ctx.stroke();
            ctx.fillStyle = '#334155';
            ctx.beginPath(); ctx.ellipse(-12, 54, 12, 5, 0, 0, Math.PI * 2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(12, 54, 12, 5, 0, 0, Math.PI * 2); ctx.fill();
            ctx.restore();

            const tableY = h * 0.62 + Math.sin(dt * 1.3) * 2;
            ctx.fillStyle = '#6b4f34';
            ctx.fillRect(cx - 140, tableY, 280, 18);
            ctx.fillStyle = '#5a3f28';
            ctx.fillRect(cx - 120, tableY + 18, 16, 32);
            ctx.fillRect(cx + 104, tableY + 18, 16, 32);
            ctx.fillStyle = theme?.glow || '#eab308';
            ctx.beginPath(); ctx.arc(cx - 40, tableY - 10, 12, 0, Math.PI * 2); ctx.fill();
            ctx.fillStyle = theme?.accent || '#f97316';
            ctx.beginPath(); ctx.arc(cx + 30, tableY - 12, 10, 0, Math.PI * 2); ctx.fill();
        }}
    function draw(t) {{
      const s = scenes[current] || {{}};
      const theme = s.theme || {{ bg0:'#070f25', bg1:'#1d345f', accent:'#7dd3fc', glow:'#60a5fa' }};
      const elapsed = (t - sceneStart) / 1000;
      const dur = Math.max(5, Number(s.duration_sec || 10));
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, theme.bg0); g.addColorStop(1, theme.bg1);
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
            ctx.globalAlpha = 1;
      const fn = drawFns[current];
    const fallbackFn = fallbackFns[current];
    if (fn) {{
            try {{
                fn(ctx, w, h, elapsed, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar,
                    drawCharacterTemplate, drawLabel, drawEquation, drawArrow, drawPanel, drawRoute,
                    drawFractionCircle, drawBarChart, drawMeasurement);
            }} catch (e) {{
                if (fallbackFn) fallbackFn(ctx, w, h, elapsed, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar,
                    drawCharacterTemplate, drawLabel, drawEquation, drawArrow, drawPanel, drawRoute,
                    drawFractionCircle, drawBarChart, drawMeasurement);
                else drawFallbackAnimated(elapsed, theme);
            }}
    }} else if (fallbackFn) {{
            fallbackFn(ctx, w, h, elapsed, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar,
                drawCharacterTemplate, drawLabel, drawEquation, drawArrow, drawPanel, drawRoute,
                drawFractionCircle, drawBarChart, drawMeasurement);
    }} else {{
            drawFallbackAnimated(elapsed, theme);
    }}
      // Bottom-of-canvas info bar
      const barH = 80;
      const barY = h - barH;
      ctx.fillStyle = theme.panel || 'rgba(0,0,0,0.55)';
      ctx.fillRect(0, barY, w, barH);
      ctx.fillStyle = '#ffffff';
      ctx.font = '700 20px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(String(s.heading || '').slice(0, 60), w / 2, barY + 12);
      ctx.font = '400 15px Arial';
      ctx.fillStyle = 'rgba(255,255,255,0.82)';
      ctx.fillText(String(s.caption || s.science_fact || s.lesson || '').slice(0, 140), w / 2, barY + 40);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      // Progress bar at top
      const p = Math.max(0, Math.min(1, elapsed / dur));
      ctx.fillStyle = 'rgba(255,255,255,0.22)';
      ctx.fillRect(16, 10, w - 32, 8);
      ctx.fillStyle = theme.accent || '#7dd3fc';
      ctx.fillRect(16, 10, (w - 32) * p, 8);
      if (elapsed >= dur && scenes.length > 1) setScene(current + 1);
      requestAnimationFrame(draw);
    }}
    window.addEventListener('resize', fit);
    fit();
    initUI();
    setScene(0);
    requestAnimationFrame(draw);
  </script>
</body>
</html>"""


def generate_story_slider(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    story_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prov, key = _pick_provider_and_key(provider, provider_keys)
    options = story_options or {}
    host_character = str(options.get("host_character") or "").strip() or None
    theme = str(options.get("theme") or "").strip() or None
    raw = call_llm(
        provider=prov,
        api_key=key,
        model=model,
        system=ARTIFACT_SAFETY_INSTRUCTION,
        user=_story_prompt(prompt, host_character=host_character, theme=theme),
        temperature=0.45,
        max_tokens=3800,
    )
    plan = _normalize_story_plan(_extract_json(raw), prompt)
    host_payload = _resolve_host_payload(host_character)
    draw_js_by_scene, fallback_js_by_scene = _prepare_story_drawings(
        plan,
        provider=prov,
        api_key=key,
        model=model,
        host_character=host_character,
        theme=theme,
    )

    html = _build_story_slider_html(
        plan,
        host_payload=host_payload,
        draw_js_by_scene=draw_js_by_scene,
        fallback_js_by_scene=fallback_js_by_scene,
        theme=theme,
    )
    return {
        "status": "ok",
        "widget_html": html,
        "story_plan": plan,
    }
