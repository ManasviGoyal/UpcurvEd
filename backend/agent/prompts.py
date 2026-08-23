# backend/agent/prompts.py
from __future__ import annotations

import html
import json
from textwrap import dedent
from typing import Any


ARTIFACT_SAFETY_INSTRUCTION = dedent("""\
    Do not generate content that meaningfully facilitates serious harm, sexual exploitation,
    abuse, or illegal wrongdoing. Legitimate educational, historical, scientific, preventive,
    and safety-focused treatment is allowed. When needed, preserve the required output format
    and redirect to a safe educational treatment instead of providing harmful instructions.
""").strip()


def _with_artifact_safety(prompt: str) -> str:
    """Prefix an artifact system prompt with the shared safety instruction."""
    return f"{ARTIFACT_SAFETY_INSTRUCTION}\n\n{dedent(prompt).strip()}"



# -------- STRUCTURED VIDEO PROMPTS --------


def _scene_script_ref(scene: dict[str, Any], index: int) -> str:
    existing = str(
        scene.get("manim_script_ref")
        or scene.get("manim_body_ref")
        or ""
    ).strip()
    if existing:
        return existing
    scene_id = str(scene.get("id") or index).strip()
    return f"scene_{scene_id}"


def _split_plan_and_code(
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str]], list[tuple[str, str]]]:
    """Prepare a normalized plan for prompts without embedding Python inside fields.

    New generations use complete MANIM_SCRIPT blocks. MANIM_BODY blocks are retained only
    so existing saved bundles can still be edited without losing their legacy code.
    """
    cloned = json.loads(json.dumps(plan or {}, ensure_ascii=False))
    scripts: list[tuple[str, str]] = []
    legacy_bodies: list[tuple[str, str]] = []
    scenes = cloned.get("scenes")
    if not isinstance(scenes, list):
        return cloned, scripts, legacy_bodies

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        script = str(scene.pop("manim_script", "") or "").strip()
        body = str(scene.pop("manim_body", "") or "").strip()
        custom_like = (
            scene.get("type") == "custom_manim_scene"
            or bool(script)
            or bool(body)
            or bool(scene.get("manim_script_ref"))
            or bool(scene.get("manim_body_ref"))
        )
        if not custom_like:
            continue
        ref = _scene_script_ref(scene, index)
        scene["manim_script_ref"] = ref
        scene.pop("manim_body_ref", None)
        if script:
            scripts.append((ref, script))
        elif body:
            legacy_bodies.append((ref, body))
    return cloned, scripts, legacy_bodies


def _tag_value(value: Any) -> str:
    return html.escape(str(value or "").strip(), quote=False)


def _tag(tag: str, value: Any) -> str:
    return f"<{tag}>{_tag_value(value)}</{tag}>"


def _format_structured_plan(plan: dict[str, Any]) -> str:
    transport_plan, _scripts, _legacy_bodies = _split_plan_and_code(plan)
    lines = [
        "<VIDEO_META>",
        _tag("TITLE", transport_plan.get("title") or "Educational video"),
    ]
    if transport_plan.get("subtitle"):
        lines.append(_tag("SUBTITLE", transport_plan.get("subtitle")))
    if transport_plan.get("audience"):
        lines.append(_tag("AUDIENCE", transport_plan.get("audience")))
    lines.append("</VIDEO_META>")

    scenes = transport_plan.get("scenes")
    if not isinstance(scenes, list):
        return "\n".join(lines)

    scalar_fields = (
        ("TYPE", "type"),
        ("LEARNING_ROLE", "learning_role"),
        ("LEARNER_QUESTION", "learner_question"),
        ("VISUAL_MODE", "visual_mode"),
        ("TITLE", "title"),
        ("SUBTITLE", "subtitle"),
        ("NARRATION", "narration"),
        ("VISUAL", "visual"),
        ("FORMULA", "formula"),
        ("DURATION_SEC", "duration_sec"),
        ("ESSENTIAL_VISUAL", "essential_visual"),
        ("REQUIRES_3D", "requires_3d"),
        ("CODE_GOAL", "code_goal"),
        ("CODE_SNIPPET", "code_snippet"),
        ("MANIM_SCRIPT_REF", "manim_script_ref"),
    )
    list_fields = (
        ("REQUIRED_VISUAL_ELEMENT", "required_visual_elements"),
        ("LABEL", "labels"),
        ("KEY_POINT", "key_points"),
    )

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        scene_id = html.escape(str(scene.get("id") or index), quote=True)
        lines.extend(["", f'<SCENE_PLAN id="{scene_id}">'])
        for tag_name, key in scalar_fields:
            value = scene.get(key)
            if value not in (None, "", []):
                lines.append(_tag(tag_name, value))
        for tag_name, key in list_fields:
            values = scene.get(key)
            if isinstance(values, list):
                for value in values:
                    if value not in (None, ""):
                        lines.append(_tag(tag_name, value))

        steps = scene.get("steps") or scene.get("calculation_steps") or []
        step_narrations = scene.get("step_narrations") or []
        if isinstance(steps, list):
            for step_index, step in enumerate(steps):
                if step in (None, ""):
                    continue
                lines.append(_tag("STEP_TEXT", step))
                if isinstance(step_narrations, list) and step_index < len(step_narrations):
                    narration = step_narrations[step_index]
                    if narration not in (None, ""):
                        lines.append(_tag("STEP_NARRATION", narration))
        lines.append("</SCENE_PLAN>")
    return "\n".join(lines)


def _format_code_blocks(
    blocks: list[tuple[str, str]],
    *,
    tag: str,
) -> str:
    if not blocks:
        return "(none)"
    return "\n\n".join(
        f'<{tag} id="{html.escape(ref, quote=True)}">\n{source}\n</{tag}>'
        for ref, source in blocks
    )


_COMPLETE_SCRIPT_CONTRACT = """\
For each custom_manim_scene, return one complete runnable MANIM_SCRIPT with the matching id.

Use only these executable imports:
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService
import numpy as np

Use numpy only when needed. Import nothing else. Executable scripts may not use files, images,
SVG, external assets, network/browser APIs, subprocesses, environment access, eval, exec, open,
or __import__. Learner-facing CODE_SNIPPET text is data and may contain ordinary source code.

Each script must:
- Define exactly one GeneratedScene class and one construct(self).
- Use GeneratedScene(VoiceoverScene) for 2D, or GeneratedScene(VoiceoverScene, ThreeDScene)
  whenever 3D objects or 3D camera methods are used.
- Call self.set_speech_service(GTTSService(lang="en")) inside construct().
- Include voiceover. Prefer one voiceover block for the scene, never more than two, and never
  place voiceover calls inside loops.
- Use stable Manim 0.19 APIs. Do not use Tex or MathTex; use Text and plain-text formulas.
- Keep important objects comfortably inside the frame. Preserve complete learner questions;
  wrap or scale them rather than truncating them.
- Use conservative 3D framing and self.wait(max(0.1, ...)) for computed waits.

Build the visual to explain the narration, not transcribe it. Prefer stable primitives and
simple, topic-specific motion or structure. If ordered steps are shown, reveal/highlight them
in the same order they are discussed.

For code scenes, visibly preserve the exact CODE_SNIPPET. If using Code, use only:
Code(code_string=<str>, language="python", add_line_numbers=True)
Do not use other Code kwargs or depend on Code internals. A short snippet may instead use a
VGroup of Text lines.

Before returning a script, silently check imports, GeneratedScene structure, voiceover,
syntax, frame fit, and absence of blocked external operations.
"""


_VIDEO_TEACHING_GUIDANCE = """\
Teach one clear learning thread rather than surveying everything related to the topic. Before
planning scenes, silently decide the central question the video will answer and the concrete
understanding the learner should have by the end. Include only the ideas needed to build that
understanding. Prefer one idea explained well over many terms mentioned quickly.

Assume the learner does not already know the vocabulary. Introduce an unfamiliar term only when
it becomes useful, define it immediately in plain language, and connect it to something concrete
the learner can see or imagine. Avoid definitions that depend on other undefined technical terms.
When two terms are being distinguished, make the difference explicit and observable.

Keep narration and the screen in lockstep. Whatever is visible should be what the narration is
explaining at that moment. Do not place extra facts, terminology, or takeaway cards on screen
while the audio is discussing something else. LABEL and KEY_POINT text should annotate or
summarize the current explanation, not run as a second independent lesson. If several visible
points need to be discussed one after another, use STEP_TEXT with matching STEP_NARRATION or a
custom animation so the timing can follow the explanation.

Teach like an animator, not a slide deck. Ask what the learner could watch change, connect, move,
compare, build, or behave that would make the idea clearer. Prefer explanatory objects, motion,
spatial relationships, diagrams, processes, timelines, measurements, graphs, networks,
simulations, code, or 3D over writing the narration on screen. A title followed by animated
boxes of sentences is still a text slide.

Use text selectively for questions, short labels, essential numbers, formulas, code, brief
definitions, and steps. Avoid paragraphs, transcript-like text, long bullet lists, and repeated
card layouts. Do not create KEY_POINT values merely to restate NARRATION.

Choose the scene type that can actually deliver the intended visual. A standard concept_scene is
best for a concise definition, formula, or small amount of text/labels; it does not create a real
diagram merely because VISUAL_MODE says diagram. Use custom_manim_scene when the teaching depends
on a diagram, meaningful motion, a changing relationship, graph, simulation, network, code view,
or 3D representation. Standard process_scene and comparison_scene are useful when their simple
deterministic layouts genuinely fit the idea. There is no quota on custom scenes.

A strong video often starts with a concrete question, phenomenon, or example, builds the key idea
step by step, shows it working, and ends by resolving the opening question or demonstrating what
the learner can now understand. The final scene should consolidate the central idea rather than
introduce a fresh list of related concepts.

Choose examples with cultural awareness. If the user's topic, language, location, or audience
provides relevant context, adapt naturally to it. Otherwise prefer broadly understandable
examples rather than assuming a particular country's food, weather, currency, holidays, sports,
school system, or everyday routines.

Start teaching immediately; do not open with a greeting, agenda, or learning-goal list. For
uncertain or future-facing topics, distinguish likely trends, plausible scenarios, risks, and
aspirations instead of presenting uncertain outcomes as inevitable.
"""


STRUCTURED_VIDEO_SYSTEM = _with_artifact_safety(f"""\
    Create one concise educational Manim video. Return only the tagged transport; no JSON,
    markdown fences, commentary, or prose outside tags.

    Scene choices:
    - Standard structured scenes: title_scene, question_scene, concept_scene, process_scene,
      comparison_scene.
    - custom_manim_scene: use when a complete Manim animation materially improves learning.

    Return, in order:
    1. One VIDEO_META block.
    2. Four to seven SCENE_PLAN blocks.
    3. One complete MANIM_SCRIPT for each custom_manim_scene.

    Core teaching direction:
    {_VIDEO_TEACHING_GUIDANCE}

    Planning fields:
    - LEARNING_ROLE: intuition, definition, problem, formula, example, interpretation.
    - VISUAL_MODE: diagram, graph, code, motion, comparison, process, text. It is descriptive,
      not a command to use a particular Manim object.
    - VISUAL and CODE_GOAL are internal production directions, never learner-facing.
    - Use REQUIRED_VISUAL_ELEMENT only for concrete visual elements that truly matter.
    - Use LABEL, KEY_POINT, FORMULA, STEP_TEXT, or STEP_NARRATION only when they genuinely
      belong on screen. Every visible field must correspond directly to what NARRATION is
      explaining in that scene. Use STEP_TEXT/STEP_NARRATION when multiple visible ideas are
      discussed sequentially; omit optional fields rather than filling them with redundant text.
    - For a visible opening question, use question_scene and put the full wording in
      LEARNER_QUESTION. NARRATION contains the explanation after the question; the backend speaks
      the question first.
    - For ordered steps, keep the introduction brief and align each STEP_NARRATION with its
      STEP_TEXT. Worked math should show substitution, simplification, and the final answer.
    - For comparison_scene, the first two LABEL values name the compared items. Add only the
      short KEY_POINT criteria/takeaways that help the learner see the comparison.
    - A source-code scene must be custom_manim_scene with VISUAL_MODE code, ESSENTIAL_VISUAL true,
      one exact CODE_SNIPPET, and a matching MANIM_SCRIPT_REF.
    - Set REQUIRES_3D true only when the script actually uses 3D objects or camera methods.

    Transport shape:
    <VIDEO_META>
    <TITLE>Short video title</TITLE>
    <SUBTITLE>Optional short subtitle</SUBTITLE>
    <AUDIENCE>general learners</AUDIENCE>
    </VIDEO_META>

    <SCENE_PLAN id="1">
    <TYPE>question_scene</TYPE>
    <LEARNING_ROLE>problem</LEARNING_ROLE>
    <LEARNER_QUESTION>Complete learner question</LEARNER_QUESTION>
    <VISUAL_MODE>diagram</VISUAL_MODE>
    <TITLE>Short hook title</TITLE>
    <NARRATION>Concise explanation that follows the spoken question.</NARRATION>
    <VISUAL>Concrete internal direction for what the learner sees.</VISUAL>
    <DURATION_SEC>8</DURATION_SEC>
    </SCENE_PLAN>

    <SCENE_PLAN id="2">
    <TYPE>custom_manim_scene</TYPE>
    <LEARNING_ROLE>intuition</LEARNING_ROLE>
    <VISUAL_MODE>motion</VISUAL_MODE>
    <TITLE>Short scene title</TITLE>
    <NARRATION>Natural learner-facing explanation.</NARRATION>
    <VISUAL>Show the idea through a concrete transformation or relationship.</VISUAL>
    <REQUIRED_VISUAL_ELEMENT>one essential visual element</REQUIRED_VISUAL_ELEMENT>
    <ESSENTIAL_VISUAL>true</ESSENTIAL_VISUAL>
    <REQUIRES_3D>false</REQUIRES_3D>
    <CODE_GOAL>What the animation must make understandable.</CODE_GOAL>
    <MANIM_SCRIPT_REF>scene_2</MANIM_SCRIPT_REF>
    </SCENE_PLAN>

    <MANIM_SCRIPT id="scene_2">
    complete runnable Python file
    </MANIM_SCRIPT>

    Transport rules:
    - Put each field in its own opening/closing tag and close every SCENE_PLAN.
    - Repeat LABEL, KEY_POINT, REQUIRED_VISUAL_ELEMENT, STEP_TEXT, and STEP_NARRATION only as
      needed.
    - A SCENE_PLAN may contain at most one CODE_SNIPPET. Preserve its indentation and line breaks.
    - Output all SCENE_PLAN blocks before all MANIM_SCRIPT blocks.
    - Omit empty optional tags.

    {_COMPLETE_SCRIPT_CONTRACT}

    Minimal valid custom script:
    <MANIM_SCRIPT id="scene_example">
    from manim import *
    from manim_voiceover import VoiceoverScene
    from manim_voiceover.services.gtts import GTTSService

    class GeneratedScene(VoiceoverScene):
        def construct(self):
            self.set_speech_service(GTTSService(lang="en"))
            start = Circle(radius=0.7, color=BLUE_C).shift(LEFT * 2)
            end = Square(side_length=1.2, color=GREEN_C).shift(RIGHT * 2)
            arrow = Arrow(start.get_right(), end.get_left(), buff=0.2)
            with self.voiceover(text="The starting state changes into the result.") as tracker:
                self.play(GrowFromCenter(start), run_time=0.6)
                self.play(GrowArrow(arrow), GrowFromCenter(end), run_time=0.9)
                self.wait(max(0.1, tracker.duration - 1.5))
    </MANIM_SCRIPT>
""")


def build_structured_video_user_prompt(goal: str) -> str:
    return dedent(f"""\
        Create a concise educational video about:
        {goal}

        Return VIDEO_META, complete SCENE_PLAN blocks, and one complete MANIM_SCRIPT for every
        custom_manim_scene. Do not return JSON or body fragments.
    """).strip()


STRUCTURED_VIDEO_PLAN_REPAIR_SYSTEM = _with_artifact_safety(f"""\
    Repair one educational-video plan. Do not use markdown fences or JSON. Return one complete
    VIDEO_META block, complete SCENE_PLAN blocks, and complete MANIM_SCRIPT blocks only for
    custom scenes that are new or changed. Omitted existing scripts are preserved.

    Keep good material and make the smallest changes needed. Preserve a strong opening hook,
    KEY_POINT values, STEP_TEXT/STEP_NARRATION pairs, and every scene-level CODE_SNIPPET.
    Do not turn the opening into an agenda or learning-goal statement. A code scene must continue
    to display its exact CODE_SNIPPET. Fix only the listed structural problem; do not add axes,
    plot objects, or other visual machinery unless the actual concept benefits from them.

    {_COMPLETE_SCRIPT_CONTRACT}
""")


def build_structured_video_plan_repair_prompt(*, plan: dict, errors: list[str]) -> str:
    _transport_plan, scripts, legacy_bodies = _split_plan_and_code(plan)
    error_lines = "\n".join(f"- {error}" for error in errors) or "- Improve the plan."
    return dedent(f"""\
        Current plan:
        <ORIGINAL_PLAN>
        {_format_structured_plan(plan)}
        </ORIGINAL_PLAN>

        Current complete scripts:
        {_format_code_blocks(scripts, tag="ORIGINAL_MANIM_SCRIPT")}

        Legacy body-only code from older saved videos, when present:
        {_format_code_blocks(legacy_bodies, tag="LEGACY_MANIM_BODY")}

        Required corrections:
        {error_lines}

        Return the complete repaired tagged plan and only changed or new MANIM_SCRIPT blocks.
    """).strip()


STRUCTURED_VIDEO_EDIT_SYSTEM = _with_artifact_safety(f"""\
    Edit one structured educational video. Do not use markdown fences or JSON. Return one
    complete VIDEO_META block, complete SCENE_PLAN blocks, and complete MANIM_SCRIPT blocks
    only for custom scenes that are new or changed. Omitted existing scripts are preserved.

    Keep the edited video focused and visual-first. Preserve one clear learning thread instead of
    expanding into loosely related terminology. Narration carries the detailed explanation while
    the screen demonstrates it through purposeful visuals. Define unfamiliar terms when first
    needed, avoid paragraphs or repeated text cards, and use custom Manim freely when it materially
    improves understanding. Use culturally appropriate examples when context is known and broadly
    understandable examples otherwise.

    You may add, remove, combine, split, or reorder scenes. Keep or improve the opening hook;
    do not replace it with a greeting, agenda, or learning-goal list. Preserve useful material
    and every existing scene-level CODE_SNIPPET. Improve learning
    roles, questions, visible points, steps, formulas, diagrams, graphs, networks, grids, code
    views, simulations, or 3D visuals as the
    edit request requires. Prefer standard scenes for reliable text-based teaching and custom
    scenes only when actual Manim visualization adds educational value.

    {_COMPLETE_SCRIPT_CONTRACT}
""")


def build_structured_video_edit_user_prompt(original_plan: dict, edit_instructions: str) -> str:
    _transport_plan, scripts, legacy_bodies = _split_plan_and_code(original_plan)
    return dedent(f"""\
        Original plan:
        <ORIGINAL_PLAN>
        {_format_structured_plan(original_plan)}
        </ORIGINAL_PLAN>

        Original complete scripts:
        {_format_code_blocks(scripts, tag="ORIGINAL_MANIM_SCRIPT")}

        Legacy body-only code from older saved videos, when present:
        {_format_code_blocks(legacy_bodies, tag="LEGACY_MANIM_BODY")}

        Edit request:
        {edit_instructions}

        Return the complete edited tagged plan and only changed or new MANIM_SCRIPT blocks.
    """).strip()


STRUCTURED_VIDEO_BATCH_SANITIZER_REPAIR_SYSTEM = _with_artifact_safety(f"""\
    Repair every listed complete Manim script that failed sanitizer or Python preflight.
    Inspect all scripts before editing because multiple scenes may share the same compatibility
    mistake. Return only one complete MANIM_SCRIPT block for every requested id, in the same
    order. Do not return JSON, markdown, commentary, or unchanged scene ids.

    Preserve the intended visual ambition. Correct only the deterministic problem reported:
    imports, class structure, 2D/3D inheritance, Python syntax, unresolved executable references,
    blocked executable operations, or a known incompatible Manim call. Do not redesign a scene
    to satisfy a stylistic heuristic. When SCENE_DATA contains code_snippet, the repaired
    MANIM_SCRIPT must display that exact snippet. Return complete runnable files, never fragments.

    {_COMPLETE_SCRIPT_CONTRACT}
""")


def build_structured_video_batch_sanitizer_repair_prompt(
    *,
    failures: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for failure in failures:
        ref = str(failure.get("ref") or "scene").strip()
        scene = failure.get("scene") if isinstance(failure.get("scene"), dict) else {}
        errors = failure.get("errors") if isinstance(failure.get("errors"), list) else []
        changes = failure.get("changes") if isinstance(failure.get("changes"), list) else []
        removed = failure.get("removed_imports") if isinstance(failure.get("removed_imports"), list) else []
        original = str(failure.get("original_script") or "").strip()
        sanitized = str(failure.get("sanitized_script") or "").strip()
        blocks.extend([
            f'<SANITIZER_REPAIR_REQUEST id="{html.escape(ref, quote=True)}">',
            f'<SCENE_DATA>{html.escape(json.dumps(scene, ensure_ascii=True, separators=(",", ":")), quote=False)}</SCENE_DATA>',
            f'<SANITIZER_ERRORS>{html.escape("; ".join(str(x) for x in errors), quote=False)}</SANITIZER_ERRORS>',
            f'<SANITIZER_CHANGES>{html.escape("; ".join(str(x) for x in changes), quote=False)}</SANITIZER_CHANGES>',
            f'<REMOVED_IMPORTS>{html.escape("; ".join(str(x) for x in removed), quote=False)}</REMOVED_IMPORTS>',
            '<ORIGINAL_SCRIPT>',
            original or '(empty)',
            '</ORIGINAL_SCRIPT>',
            '<SANITIZED_SCRIPT>',
            sanitized or '(empty)',
            '</SANITIZED_SCRIPT>',
            '</SANITIZER_REPAIR_REQUEST>',
            '',
        ])
    return "\n".join(blocks).strip()


STRUCTURED_VIDEO_BATCH_RENDER_REPAIR_SYSTEM = _with_artifact_safety(f"""\
    Repair every listed complete Manim scene that failed during actual Manim execution.
    Inspect all scripts and tracebacks before correcting them because failures may share a root
    cause. Return only one complete MANIM_SCRIPT block for every requested id, in the same order.
    Do not return JSON, markdown, commentary, or scripts for scenes that already rendered.

    Preserve each scene's teaching purpose and original visual ambition. Fix the actual runtime
    or compatibility errors shown in the tracebacks. When SCENE_DATA contains code_snippet,
    preserve and visibly display that exact snippet. Return complete replacement files, never
    fragments.

    {_COMPLETE_SCRIPT_CONTRACT}
""")


def build_structured_video_batch_render_repair_prompt(
    *,
    failures: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for failure in failures:
        ref = str(failure.get("ref") or "scene").strip()
        scene = failure.get("scene") if isinstance(failure.get("scene"), dict) else {}
        original = str(failure.get("original_script") or "").strip()
        executed = str(failure.get("executed_script") or "").strip()
        traceback = str(failure.get("traceback") or "").strip()
        stage = str(failure.get("render_stage") or "initial_render")
        command = str(failure.get("render_command") or "").strip()
        blocks.extend([
            f'<RENDER_REPAIR_REQUEST id="{html.escape(ref, quote=True)}">',
            f'<SCENE_DATA>{html.escape(json.dumps(scene, ensure_ascii=True, separators=(",", ":")), quote=False)}</SCENE_DATA>',
            f'<RENDER_STAGE>{html.escape(stage, quote=False)}</RENDER_STAGE>',
            f'<RENDER_COMMAND>{html.escape(command, quote=False)}</RENDER_COMMAND>',
            '<ORIGINAL_SCRIPT>',
            original or '(empty)',
            '</ORIGINAL_SCRIPT>',
            '<EXECUTED_SCRIPT>',
            executed or '(empty)',
            '</EXECUTED_SCRIPT>',
            '<MANIM_TRACEBACK>',
            traceback or '(no traceback returned)',
            '</MANIM_TRACEBACK>',
            '</RENDER_REPAIR_REQUEST>',
            '',
        ])
    return "\n".join(blocks).strip()


STRUCTURED_VIDEO_BATCH_SIMPLIFY_SYSTEM = _with_artifact_safety(f"""\
    The listed scenes failed during actual execution or could not pass a deterministic
    syntax/safety preflight. Create simpler, more reliable implementations of the same scenes.
    Return only one complete MANIM_SCRIPT block for every requested id, in the same order.
    Do not return JSON, markdown, commentary, or scripts for scenes that already rendered.

    Preserve narration, core concept, and meaningful visual explanation. Simplifying a scene
    should reduce technical fragility, not replace an explanatory visual with a transcript or
    paragraph of text. Deliberately reduce
    technical fragility: use stable Manim primitives, fewer objects, simpler transformations,
    and fewer delicate APIs. Preserve the educational representation that matters, but do not
    add axes, plots, or extra structures merely to satisfy VISUAL_MODE metadata. A code scene
    must still visibly display its exact CODE_SNIPPET, even if the animation becomes simpler.

    {_COMPLETE_SCRIPT_CONTRACT}
""")


def build_structured_video_batch_simplify_prompt(
    *,
    failures: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for failure in failures:
        ref = str(failure.get("ref") or "scene").strip()
        scene = failure.get("scene") if isinstance(failure.get("scene"), dict) else {}
        history = failure.get("history") if isinstance(failure.get("history"), list) else []
        original = str(failure.get("original_script") or "").strip()
        latest = str(failure.get("latest_script") or "").strip()
        blocks.extend([
            f'<SIMPLIFY_REQUEST id="{html.escape(ref, quote=True)}">',
            f'<SCENE_DATA>{html.escape(json.dumps(scene, ensure_ascii=True, separators=(",", ":")), quote=False)}</SCENE_DATA>',
            f'<FAILURE_HISTORY>{html.escape(json.dumps(history, ensure_ascii=True, separators=(",", ":")), quote=False)}</FAILURE_HISTORY>',
            '<ORIGINAL_SCRIPT>',
            original or '(empty)',
            '</ORIGINAL_SCRIPT>',
            '<LATEST_SCRIPT>',
            latest or '(empty)',
            '</LATEST_SCRIPT>',
            '</SIMPLIFY_REQUEST>',
            '',
        ])
    return "\n".join(blocks).strip()


# Backward-compatible aliases for imports in older tests or modules. New structured-video code
# uses the batch complete-script prompts above.
STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM = STRUCTURED_VIDEO_BATCH_RENDER_REPAIR_SYSTEM
STRUCTURED_VIDEO_BATCH_CREATIVE_REPAIR_SYSTEM = STRUCTURED_VIDEO_BATCH_SANITIZER_REPAIR_SYSTEM


def build_structured_video_creative_repair_prompt(
    *,
    scene: dict,
    original_body: str,
    failure_stage: str,
    error_detail: str,
) -> str:
    return build_structured_video_batch_render_repair_prompt(
        failures=[{
            "ref": str(scene.get("manim_script_ref") or scene.get("manim_body_ref") or "scene"),
            "scene": scene,
            "original_script": original_body,
            "executed_script": original_body,
            "traceback": error_detail,
            "render_stage": failure_stage,
        }]
    )


def build_structured_video_batch_creative_repair_prompt(
    *,
    failures: list[dict[str, Any]],
) -> str:
    converted = []
    for failure in failures:
        converted.append({
            "ref": failure.get("ref"),
            "scene": failure.get("scene"),
            "errors": failure.get("errors"),
            "changes": [],
            "removed_imports": [],
            "original_script": failure.get("original_body"),
            "sanitized_script": failure.get("original_body"),
        })
    return build_structured_video_batch_sanitizer_repair_prompt(failures=converted)


# -------- WIDGET PROMPTS --------

WIDGET_SYSTEM = _with_artifact_safety("""\
    Create one self-contained interactive educational HTML worksheet/activity.
    Return ONLY a complete HTML document. No markdown or explanation.

    Core rule: build the smallest working interaction that teaches one important idea.
    Complexity is a failure unless the concept truly requires it.

    Teaching design:
    - Identify one clear learning objective and one obvious learner action.
    - Make the interactive worksheet visibly specific to the requested topic; never make a generic concept lab.
    - Give a short instruction, immediate meaningful feedback, and one brief "Try this" or
      "What to notice" prompt.
    - Silently choose the simplest fitting pattern: manipulate, test, classify, sequence,
      compare, graph, or puzzle. Use one pattern unless a second is essential.
    - The learner should do or test the concept, not merely watch an animation.
    - Helper buttons such as Hint, Step, Play, or Solve may support the main interaction,
      but must not replace it.

    Simplicity rules:
    - Do not build a dashboard by default.
    - Do not add decorative metrics, extra sliders, tabs, legends, or animations.
    - Prefer ordinary DOM elements for choices, inputs, cards, sequencing, and feedback.
    - Use a small SVG for diagrams or graphs. Use canvas only when drawing, motion, or
      direct manipulation truly benefits from it.
    - Use at most two primary controls unless a rule-based puzzle genuinely needs more.
    - Use requestAnimationFrame only for continuous animation; ordinary interactions should
      update only when the learner acts.

    Technical requirements:
    - Full HTML document beginning with <!DOCTYPE html> and ending with </html>.
    - Vanilla HTML, CSS, and JavaScript only.
    - One inline <style> block and one inline <script> block.
    - No external scripts, styles, fonts, images, CDNs, fetch, storage, cookies, network,
      window.parent, or window.top.
    - Use addEventListener for the primary learner action.
    - The action must visibly update the activity, result, feedback, or visualization.
    - Start with useful visible content; never show an empty canvas or blank activity.
    - For canvas pointer coordinates, use getBoundingClientRect().
    - Declare all const/let state before the first draw, render, update, or animation call.
    - Keep code compact, close every tag/function/object, and avoid large datasets.
    - If the requested concept is broad, teach one foundational part well rather than making
      a large but confusing simulation.
""")


def build_widget_user_prompt(topic: str) -> str:
    return dedent(f"""\
        Topic: {topic}
        Audience: middle/high school learners.

        Create a simple, teacher-ready interactive worksheet with one learning objective, one main learner
        action, immediate topic-specific feedback, and one short thing to try or notice.
        Choose the least complex interaction that makes the idea clearer than text alone.

        Output ONLY the complete HTML document.
    """).strip()


WIDGET_SIMPLE_FALLBACK_SYSTEM = _with_artifact_safety("""\
    Create a very small, reliable interactive educational HTML worksheet from scratch.
    Return ONLY a complete standalone HTML document. No markdown or explanation.

    This is a fallback after a more ambitious interactive worksheet failed. Do not repair or imitate the
    failed implementation. Make a simpler version of the same teaching idea.

    Requirements:
    - Teach one foundational idea with one obvious learner action.
    - Use one visual/activity area, one short instruction, and one feedback message.
    - Use at most two controls.
    - Prefer buttons, choices, text/number input, movable DOM cards, or a small SVG.
    - Use canvas only if drawing is essential. Do not use requestAnimationFrame unless
      continuous motion is essential.
    - No dashboard, decorative metrics, multiple panels, large datasets, or extra features.
    - Use vanilla HTML/CSS/JS, inline style/script, addEventListener, and no external assets,
      network, storage, or parent-window access.
    - Start in a useful visible state and close all HTML and JavaScript cleanly.
""")


def build_widget_simple_fallback_user_prompt(*, topic: str, reason: str | None = None) -> str:
    reason_line = f"Earlier attempt failed: {reason[:300]}\n" if reason else ""
    return dedent(f"""\
        Topic: {topic}
        {reason_line}
        Build the smallest useful interactive explanation of this topic.
        Return ONLY the complete HTML document.
    """).strip()


WIDGET_EDIT_SYSTEM = _with_artifact_safety("""\
    Revise an existing self-contained interactive educational HTML worksheet.
    Return ONLY the complete revised HTML document. No markdown or explanation.

    Preserve the topic, useful visual metaphor, main learner action, style, and working code
    unless the edit request requires a change. Make the smallest useful revision.
    Keep one clear learning objective and immediate feedback. Do not add a dashboard,
    decorative metrics, extra controls, or continuous animation unless requested or necessary.

    Keep it self-contained vanilla HTML/CSS/JS with no external assets, network, storage,
    or parent-window access. Use addEventListener and ensure the primary action still visibly
    changes the activity or feedback. Close all tags and scripts.
""")


def build_widget_edit_user_prompt(*, original_html: str, edit_instructions: str, original_title: str | None) -> str:
    return dedent(f"""\
        Existing interactive worksheet: {original_title or 'Interactive worksheet'}
        Edit request: {edit_instructions.strip()}

        Revise the existing source below. Preserve unaffected behavior and keep the result
        simple, pedagogically coherent, and fully interactive.

        Original HTML:
        {original_html}

        Return ONLY the revised complete HTML document.
    """).strip()


WIDGET_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair one self-contained interactive educational HTML worksheet.
    Return ONLY the fixed complete HTML document. No markdown or explanation.

    Fix the reported defect with the smallest useful change. Preserve the topic, learning
    objective, main interaction, and visual approach when possible. Do not expand the interactive worksheet
    into a dashboard or add controls, metrics, canvas, or animation merely to satisfy repair.

    The repaired interactive worksheet must use vanilla HTML/CSS/JS, addEventListener, visible feedback or
    state change after the learner acts, no external assets/network/storage, safe initialization
    order, and complete closing tags.
""")


def build_widget_repair_user_prompt(*, original_title: str | None, edit_instructions: str, prior_html: str, reason: str) -> str:
    return dedent(f"""\
        Interactive worksheet/topic: {original_title or 'Interactive worksheet'}
        Intended change or context: {edit_instructions}
        Validation failure: {reason}

        Repair the HTML below. Keep the same educational activity and fix only what is needed.
        If the design is too complex to repair safely, simplify it while preserving the central
        learner action and topic-specific feedback.

        HTML to repair:
        {prior_html}

        Return ONLY corrected complete HTML.
    """).strip()


# Final emergency fallback spec. The normal fallback is a fresh simple HTML call above.
WIDGET_FALLBACK_SPEC_SYSTEM = _with_artifact_safety("""\
    Create compact JSON for a last-resort topic-specific interactive worksheet.
    Return ONLY valid JSON. No markdown, code fences, or comments.

    The backend renders the HTML. Use real topic variables and avoid generic concept-lab labels.

    JSON schema:
    {
      "title": "short topic-specific title",
      "concept_line": "one sentence explaining what the learner explores",
      "visual_items": ["3 to 5 short topic-specific labels"],
      "controls": [
        {"label": "meaningful variable", "min": 0, "max": 100, "step": 1, "value": 50, "low_label": "low meaning", "high_label": "high meaning"}
      ],
      "metrics": [
        {"label": "topic-specific result", "unit": "short unit or blank"}
      ],
      "try_this": "one concrete learner task",
      "notice": "one short observation",
      "low_insight": "feedback when settings are low",
      "high_insight": "feedback when settings are high"
    }

    Return exactly 3 controls and 3 metrics because the emergency renderer requires them.
    Keep each sentence under 24 words.
""")


def build_widget_fallback_spec_user_prompt(*, topic: str, reason: str | None = None) -> str:
    reason_line = f"Earlier HTML fallbacks failed: {reason}\n" if reason else ""
    return dedent(f"""\
        Topic: {topic}
        {reason_line}
        Create the small emergency JSON spec only.
    """).strip()


# -------- STATIC WORKSHEET PROMPTS --------

STATIC_WORKSHEET_SYSTEM = _with_artifact_safety("""\
    Create one teacher-ready STATIC educational worksheet as a complete standalone HTML document.
    Return ONLY the complete HTML document. No markdown, commentary, or text outside the HTML.

    Purpose:
    - This is a document learners fill in, write on, select within, label, organize, calculate on,
      or reflect in. It is not a simulation, game, dashboard, multiple-choice quiz, or generic app.
    - Infer the most useful worksheet structure from the learner request: guided notes, practice,
      short answer, labeling, matching, sorting, calculation/worked practice, reflection,
      graphic organizer, vocabulary, reading response, or a sensible combination.
    - If the user explicitly asks for a particular worksheet format, follow it.
    - Keep enough detail to make the worksheet genuinely useful; do not simplify merely to reduce
      text when the content remains readable and relevant.

    Learner-response design:
    - Include meaningful response spaces using native HTML form controls such as input, textarea,
      select, checkbox, or radio controls. Use visible labels for every response area.
    - Give each learner-response control a stable name attribute. Radio choices in one question
      may intentionally share a name.
    - Prefer textareas for multi-sentence responses and adequately sized inputs for short answers.
    - Do not reveal an answer key unless the user explicitly requests one.
    - Do not score, grade, auto-check, reveal correctness, or provide dynamic feedback. Those
      behaviors belong to Multiple Choice Quiz or Interactive Worksheet.

    Document and print design:
    - Make the worksheet immediately readable on a white, print-friendly page with clear hierarchy.
    - Use normal document flow. Avoid fixed-position content, huge blank regions, clipped sections,
      tiny text, or decorative layouts that waste printable space.
    - Use a clear title and concise instructions, followed by logically grouped learner tasks.
    - Use tables, inline SVG diagrams, lines, boxes, columns, or labeled regions when they improve
      the worksheet. Keep all labels legible and non-overlapping.
    - Include @media print CSS so the learning content prints cleanly. Do not add your own Save,
      Print, PDF, or progress toolbar; UpcurvEd adds trusted controls after validation.
    - Prefer system fonts. Keep body text generally at 14px or larger on screen and print.

    Technical requirements:
    - Full HTML document beginning with <!DOCTYPE html> and ending with </html>.
    - One inline <style> block is allowed. No JavaScript of any kind.
    - No <script>, event-handler attributes, external scripts/styles/fonts/images, links, iframes,
      object/embed, audio/video, fetch, storage, cookies, form submission, network access, or URLs.
    - Forms, if used, must not have action or method attributes that submit anywhere.
    - Inline SVG is allowed for static educational diagrams, but it must contain no scripts,
      external references, links, images, animation, or foreignObject.
    - Do not depend on resources outside the HTML file.

    Before returning, silently inspect the complete worksheet for incomplete HTML, missing response
    spaces, clipped or overlapping content, unusably small fields, unreadable print layout, and
    accidental interactive/app behavior. Correct those issues before output.
""")


def build_static_worksheet_user_prompt(topic: str) -> str:
    return dedent(f"""\
        Learner/teacher request:
        {topic}

        Create the most useful static fillable worksheet for this request. Infer the appropriate
        worksheet structure from the learning task. Return ONLY the complete standalone HTML.
    """).strip()


STATIC_WORKSHEET_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair one static educational HTML worksheet. Return ONLY the complete corrected HTML document.
    Preserve the topic, useful questions/tasks, response spaces, and visual organization while
    fixing the listed validation problem with the smallest useful change.

    It must remain a static fillable document: no JavaScript, scoring, dynamic feedback, external
    assets, network access, storage, links, iframe/object/embed, audio/video, or form submission.
    Keep visible labels with learner-response fields, maintain a clean print-friendly layout, and
    close every HTML element correctly. Do not add Save/Print/PDF controls; UpcurvEd injects those.
""")


def build_static_worksheet_repair_user_prompt(*, original_html: str, problem: str) -> str:
    return dedent(f"""\
        Validation problem:
        {problem}

        Worksheet HTML to repair:
        {original_html}

        Return ONLY the corrected complete standalone HTML.
    """).strip()


STATIC_WORKSHEET_EDIT_SYSTEM = _with_artifact_safety("""\
    Edit an existing static educational HTML worksheet. Return ONLY the complete revised HTML
    document. No markdown or explanation.

    Preserve useful worksheet content, response fields, print-friendly structure, and style unless
    the edit request requires a change. Make the smallest useful revision while keeping the result
    a static fillable document rather than a quiz, simulation, dashboard, or generic interactive app.

    No JavaScript, scoring, dynamic feedback, external assets, network/storage, links,
    iframe/object/embed, audio/video, or form submission. Every learner response space should remain
    clearly labeled and usable. Do not add Save/Print/PDF controls; UpcurvEd adds trusted controls.
""")


def build_static_worksheet_edit_user_prompt(*, original_html: str, edit_instructions: str) -> str:
    return dedent(f"""\
        Edit request:
        {edit_instructions.strip()}

        Original static worksheet HTML:
        {original_html}

        Return ONLY the complete revised standalone HTML worksheet.
    """).strip()


# -------- STATIC DIAGRAM PROMPTS --------

DIAGRAM_SYSTEM = _with_artifact_safety("""\
    Create one static educational visual diagram as a standalone SVG image.
    Return ONLY the complete <svg>...</svg> document. No markdown, HTML wrapper, JavaScript,
    commentary, or text outside the SVG.

    Choose the visual structure that best fits the learner request rather than forcing every
    topic into a flowchart. Good options include a process/flow, comparison, hierarchy/tree,
    concept map, timeline, cycle, cause-and-effect diagram, or simple labeled schematic.

    Teaching design:
    - Communicate one clear learning idea visually.
    - Use concise labels and short supporting phrases rather than paragraphs.
    - Match the structure to the meaning: arrows for real sequence/process, distinct groups for
      comparisons, and clear parent/child or conceptual relationships for maps and hierarchies.
    - Use color, grouping, position, and connectors to clarify meaning rather than decorate.
    - Keep the result useful as a standalone image for documents or slides.

    SVG/layout requirements:
    - Use a viewBox and make the artwork self-contained. Prefer roughly 1200 x 800 landscape
      unless another aspect ratio materially fits the content better.
    - Include a short <title> and useful <desc> for accessibility.
    - Keep all important content comfortably inside the canvas with visible outer margins.
      Never place captions or footnotes against the canvas edge.
    - Keep major content groups visually separate with comfortable spacing between neighboring
      boxes/cards. Use explicit x/y positions for major groups when practical.
    - Keep text inside its own group and wrap long labels with multiple <tspan> rows.
    - Use readable document-scale text: generally at least 20 px for body labels and 26 px for
      primary node titles on a 1200-wide canvas.
    - Avoid large unused blank areas. Prefer 3-6 major visual groups unless the topic genuinely
      requires more. Use simple system fonts such as Arial, Helvetica, or sans-serif.

    Static/safety requirements:
    - No interaction, animation, hover states, buttons, forms, or dynamic explanation panels.
    - No <script>, <foreignObject>, <iframe>, <image>, <use>, <a>, audio/video, animation tags,
      event-handler attributes, external URLs, external fonts/assets, data URLs, CSS imports,
      network access, or embedded HTML.
    - Allowed drawing primitives are ordinary SVG shapes/text/groups/paths plus safe defs such as
      markers, gradients, and clip paths. Do not depend on resources outside the SVG.

    Before returning, silently inspect the full SVG for clipped text, overlapping major groups,
    crossing labels, connectors through text, captions too close to edges, and excessive
    whitespace. Correct obvious layout problems before output.
""")


def build_diagram_user_prompt(topic: str) -> str:
    return dedent(f"""\
        Learner request:
        {topic}

        Create the most useful static educational diagram for this request. Choose the appropriate
        diagram structure based on the meaning of the request. Return ONLY the standalone SVG.
    """).strip()


DIAGRAM_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair one static educational SVG diagram. Return ONLY the complete corrected <svg>...</svg>.
    Preserve the topic and useful visual structure while fixing the listed validation problem.

    The repaired SVG must remain fully static and standalone: no JavaScript, interaction,
    foreignObject, embedded HTML, external resources, links, images, use elements, or animation.
    Keep all major boxes non-overlapping, wrap text inside its own box, keep content inside the
    viewBox, maintain readable font sizes, and use the canvas efficiently.
""")


def build_diagram_repair_user_prompt(*, original_svg: str, problem: str) -> str:
    return dedent(f"""\
        Validation problem:
        {problem}

        SVG to repair:
        {original_svg}

        Return ONLY the corrected standalone SVG.
    """).strip()


DIAGRAM_EDIT_SYSTEM = _with_artifact_safety("""\
    Edit an existing static educational SVG diagram. Return ONLY the complete revised
    <svg>...</svg> document. No markdown, HTML wrapper, JavaScript, or explanation.

    Preserve useful content and style unless the edit request requires a change. The result must
    remain a static portable image suitable for documents and slides. You may change the visual
    structure when that makes the requested idea clearer. Keep all major boxes non-overlapping,
    wrap text inside nodes, preserve generous spacing, and use the viewBox efficiently.

    No interaction, scripts, foreignObject, external assets/URLs, links, images, use elements, or
    animation are allowed.
""")


def build_diagram_edit_user_prompt(*, original_svg: str, edit_instructions: str) -> str:
    return dedent(f"""\
        Edit request:
        {edit_instructions.strip()}

        Original SVG:
        {original_svg}

        Return ONLY the complete revised standalone SVG.
    """).strip()


# -------- QUIZ PROMPTS --------

QUIZ_GENERATE_SYSTEM = _with_artifact_safety("""\
    You are a JSON generator. Always return a single valid JSON object.
    Never include markdown code fences, explanations, or comments.
""")


def build_quiz_user_prompt(prompt: str, num_questions: int, difficulty: str, context: str | None) -> str:
    context_block = (
        f"\nAdditional context (SRT/script, use only for content; DO NOT include it in the JSON):\n{context}\n"
        if context
        else ""
    )
    return dedent(f"""\
        You are an expert quiz maker. Produce a multiple-choice quiz as a single JSON object only, strictly following this schema and rules.

        SCHEMA (keys and types):
        {{
          "title": string,
          "description": string,
          "questions": [
            {{ "type": "multiple_choice", "prompt": string, "options": [string, ...], "correctIndex": integer }}
          ]
        }}

        HARD RULES:
        1) Output MUST be valid RFC 8259 JSON. No markdown, no code fences, no comments, no explanations.
        2) Use double quotes for ALL keys and ALL string values.
        3) NO trailing commas anywhere.
        4) The array questions MUST contain exactly {num_questions} items.
        5) Each question MUST have type="multiple_choice", a non-empty prompt, and 3-5 unique options.
        6) correctIndex MUST be a 0-based integer within the options array, and the option at that index is the ONLY correct answer.
        7) Do NOT include null/undefined/NaN, and do NOT include additional fields beyond the schema.
        8) The JSON MUST start with '{{' and end with '}}' with no leading or trailing text.

        CONTENT REQUIREMENTS:
        - Use exactly {num_questions} questions.
        - Topic/context from the user prompt: "{prompt}"
        - Difficulty: {difficulty}
        - Title and description should be short and informative.
        - Use context only to craft questions; DO NOT embed the context text into the JSON.
        {context_block}
    """).strip()


QUIZ_EDIT_SYSTEM = _with_artifact_safety("""\
    You are a JSON-only quiz editor. Always return a single valid JSON object.
    Never include markdown code fences, explanations, or comments.
""")


def build_quiz_edit_user_prompt(*, original_quiz: dict, edit_instructions: str, num_questions: int, difficulty: str) -> str:
    original_json = json.dumps(original_quiz or {}, ensure_ascii=False, indent=2)
    return dedent(f"""\
        You are editing an existing multiple-choice quiz. Produce a revised quiz JSON object only.

        SCHEMA (exact keys and types):
        {{
          "title": string,
          "description": string,
          "questions": [
            {{ "type": "multiple_choice", "prompt": string, "options": [string, ...], "correctIndex": integer }}
          ]
        }}

        EDITING RULES:
        1) Revise the existing quiz; do not create an unrelated new quiz.
        2) Preserve the topic, level, and good questions unless the edit instructions require changing them.
        3) Make the smallest useful change that satisfies the edit instructions.
        4) Use exactly {num_questions} questions unless the instructions explicitly say otherwise.
        5) Difficulty target: {difficulty}.
        6) Each question must have 3-5 unique options and exactly one correct answer.
        7) correctIndex must be a 0-based integer inside the options array.
        8) Output MUST be valid JSON only: no markdown, no code fences, no explanations.

        Original quiz JSON:
        {original_json}

        Edit instructions:
        {edit_instructions.strip()}

        Return ONLY the revised quiz JSON.
    """).strip()


# -------- STORY EDIT PROMPTS --------

STORY_EDIT_PATCH_SYSTEM = _with_artifact_safety("""\
    You edit the source JSON for an existing educational story slider.
    Return ONLY valid JSON. No markdown, no code fences, no explanation.

    Your output is a PATCH, not a full HTML document.

    Output shape:
    {
      "title": "optional revised title",
      "moral": "optional revised moral",
      "conclusion": "optional revised conclusion",
      "updates": [
        {
          "scene_number": 1,
          "heading": "optional revised heading",
          "caption": "optional revised caption",
          "lesson": "optional revised lesson",
          "science_fact": "optional revised science fact",
          "vocabulary": ["optional", "revised", "terms"],
          "cause_effect": "optional revised cause/effect",
          "misconception_fix": "optional revised misconception fix",
          "speech_bubble": "optional short bubble text",
          "visual": "optional concrete visual plan",
          "draw_js": "optional executable JavaScript drawing statements"
        }
      ]
    }

    Story draw_js rules:
    - draw_js must be executable JavaScript statements only, not prose or planning notes.
    - The runtime provides x, w, h, dt and these helper functions:
      drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar, drawCharacterTemplate,
      drawLabel, drawEquation, drawArrow, drawPanel, drawRoute, drawFractionCircle,
      drawBarChart, and drawMeasurement.
    - Use x as the CanvasRenderingContext2D. Use relative positions based on w and h.
    - A guide character and speech bubble are optional. Let the topic visual dominate.
    - Prefer distinct diagrams, maps, object simulations, equation transformations, charts,
      cycles, timelines, probability trees, measurements, and before/after compositions.
    - Use drawLabel and drawEquation for essential text. Do not call fillText or strokeText directly.
    - Return body statements only. Do not wrap draw_js in function(...) or an arrow function,
      and do not define nested functions.
    - Do not rely on external images, fonts, libraries, fetch, DOM access, window, document,
      localStorage, requestAnimationFrame, timers, or network calls.
    - Do not use markdown, comments-only output, or natural language explanation inside draw_js.
    - If a scene currently falls back to a generic visual, replace its draw_js with a concrete
      topic-related visualization and choose a visual_strategy distinct from neighboring scenes.
    - Keep each draw_js concise enough to fit in JSON, but complete enough to run.

    Editing behavior:
    - Preserve the existing story topic and useful scenes.
    - Apply the user edit to the relevant scene(s).
    - If the user asks to improve generic/unhelpful visual scenes, update every scene identified as invalid, generic, or weak.
    - Do not delete scenes unless explicitly asked. Usually replace weak scenes with better visualizations.
""")


def build_story_edit_patch_user_prompt(*, original_title: str | None, scene_summaries: list[dict], edit_instructions: str) -> str:
    return dedent(f"""\
        Original story title: {original_title or 'Existing story'}

        User edit request:
        {edit_instructions.strip()}

        Scene summaries. scene_number is 1-based. draw_js_status tells you if the scene likely falls back to a generic character/table animation.
        {json.dumps(scene_summaries, ensure_ascii=False, indent=2)}

        Return ONLY the JSON patch. Include an updates array.
    """).strip()


STORY_EDIT_FULL_HTML_SYSTEM = _with_artifact_safety("""\
    You revise existing self-contained educational story slider HTML.
    Return ONLY a complete HTML document. No markdown, no backticks, no explanation.
    Preserve the existing story slider structure, CSS style, navigation behavior, and JavaScript unless the user explicitly asks to change them.
    Make the smallest useful change that satisfies the edit instructions.
    Keep it self-contained: no external scripts, no external stylesheets, no fetch, no images/CDNs.
    Do not replace the artifact with a completely different story unless explicitly requested.
    Close all tags and end with </html>.
""")


def build_story_edit_full_html_user_prompt(*, original_html: str, edit_instructions: str, original_title: str | None) -> str:
    return dedent(f"""\
        Original title: {original_title or 'Existing story slider'}

        Edit instructions:
        {edit_instructions.strip()}

        Original complete HTML to revise:
        {original_html}

        Return ONLY the revised complete HTML document.
    """).strip()
