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
For every custom_manim_scene, return exactly one matching complete MANIM_SCRIPT.
A MANIM_SCRIPT is a complete runnable Python file, not a fragment.

Allowed imports only:
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService
import numpy as np

Import numpy as np only when it is actually needed. Import nothing else. Do not use files,
images, SVG, network calls, browser APIs, subprocesses, environment access, eval, exec, open,
__import__, external libraries, or external assets.

Script structure:
- Define exactly one class named GeneratedScene.
- Use class GeneratedScene(VoiceoverScene) for ordinary 2D scenes.
- Use class GeneratedScene(VoiceoverScene, ThreeDScene) whenever the script uses 3D objects,
  ThreeDAxes, Surface, Polyhedron, Cube, Sphere, Prism, Cone, Cylinder, Dot3D, Line3D,
  Arrow3D, or 3D camera methods.
- Define exactly one construct(self) method.
- Inside construct(), call self.set_speech_service(GTTSService(lang="en")).
- Include at least one with self.voiceover(text=...) as tracker block.
- Use stable Manim 0.19 APIs and complete executable Python.
- Do not use Tex or MathTex. Use Text and portable plain-text formulas instead.
- Keep every important object inside the frame and remove or transform old objects before
  introducing a new dense layout.
- Use self.wait(max(0.1, ...)) when waiting on computed durations.

Creative quality:
- A custom scene must visibly teach the specific concept, not just display a heading or cards.
- Use meaningful spatial relationships, motion, measurements, axes, paths, state changes,
  diagrams, grids, networks, code panels, or 3D geometry when they improve understanding.
- Graph scenes must use real axes or a number plane, draw the relationship, and mark the
  feature discussed in narration.
- Network scenes should use simple Circle/Dot nodes, Line/Arrow edges, and labels rather than
  external graph libraries.
- Grid-world scenes should build the grid from Rectangles/Squares and visibly animate values,
  actions, transitions, or policy updates.
- Code scenes should use Code(code_string=..., language="python", add_line_numbers=True) or
  plain Text/VGroup when a Code object is unnecessary. Do not inspect Code internals.
- Prefer two or three focused creative scenes in a normal video, and never more than three.

Before returning each script, silently verify:
1. Only the allowed imports appear.
2. Exactly one GeneratedScene class exists with correct 2D or 3D inheritance.
3. construct() configures GTTSService and contains voiceover.
4. The script is complete and syntactically valid.
5. The visual is topic-specific and materially explains the narration.
6. No external assets, filesystem, network, subprocess, Tex, or MathTex are used.
"""


STRUCTURED_VIDEO_SYSTEM = _with_artifact_safety(f"""\
    Create one concise educational Manim video in one response. Do not use markdown fences,
    JSON, or commentary. Use only the tagged transport below.

    The model has exactly two scene choices:
    1. A standard structured scene rendered by reliable backend components.
    2. custom_manim_scene with one complete runnable MANIM_SCRIPT.

    Output order:
    1. One VIDEO_META block.
    2. Four to seven complete SCENE_PLAN blocks.
    3. One MANIM_SCRIPT block for every custom_manim_scene.

    Exact transport pattern:
    <VIDEO_META>
    <TITLE>Short video title</TITLE>
    <SUBTITLE>Optional learner-facing subtitle</SUBTITLE>
    <AUDIENCE>general learners</AUDIENCE>
    </VIDEO_META>

    <SCENE_PLAN id="1">
    <TYPE>title_scene</TYPE>
    <LEARNING_ROLE>intuition</LEARNING_ROLE>
    <VISUAL_MODE>text</VISUAL_MODE>
    <TITLE>Short scene title</TITLE>
    <SUBTITLE>Optional educational subtitle</SUBTITLE>
    <NARRATION>Student-facing narration.</NARRATION>
    <VISUAL>Internal production direction.</VISUAL>
    <DURATION_SEC>8</DURATION_SEC>
    </SCENE_PLAN>

    <SCENE_PLAN id="2">
    <TYPE>process_scene</TYPE>
    <LEARNING_ROLE>example</LEARNING_ROLE>
    <LEARNER_QUESTION>What should the learner understand here?</LEARNER_QUESTION>
    <VISUAL_MODE>process</VISUAL_MODE>
    <TITLE>Short scene title</TITLE>
    <NARRATION>Brief introduction to the sequence.</NARRATION>
    <FORMULA>portable plain-text formula when needed</FORMULA>
    <STEP_TEXT>First visible instructional step</STEP_TEXT>
    <STEP_NARRATION>Natural spoken explanation of that step.</STEP_NARRATION>
    <STEP_TEXT>Second visible instructional step</STEP_TEXT>
    <STEP_NARRATION>Natural spoken explanation of that step.</STEP_NARRATION>
    <DURATION_SEC>18</DURATION_SEC>
    </SCENE_PLAN>

    For a creative scene:
    <SCENE_PLAN id="3">
    <TYPE>custom_manim_scene</TYPE>
    <LEARNING_ROLE>interpretation</LEARNING_ROLE>
    <VISUAL_MODE>graph</VISUAL_MODE>
    <TITLE>Topic-specific visual explanation</TITLE>
    <NARRATION>Student-facing explanation.</NARRATION>
    <VISUAL>Internal production direction for the animation.</VISUAL>
    <REQUIRED_VISUAL_ELEMENT>first concrete element</REQUIRED_VISUAL_ELEMENT>
    <REQUIRED_VISUAL_ELEMENT>second concrete element</REQUIRED_VISUAL_ELEMENT>
    <ESSENTIAL_VISUAL>true</ESSENTIAL_VISUAL>
    <REQUIRES_3D>false</REQUIRES_3D>
    <CODE_GOAL>What the script must visibly demonstrate.</CODE_GOAL>
    <MANIM_SCRIPT_REF>scene_3</MANIM_SCRIPT_REF>
    </SCENE_PLAN>

    <MANIM_SCRIPT id="scene_3">
    complete runnable Python file
    </MANIM_SCRIPT>

    Transport rules:
    - Never output JSON, dictionaries, markdown fences, or prose outside tags.
    - Put each field in its own opening and closing tag. Close every SCENE_PLAN.
    - Repeat REQUIRED_VISUAL_ELEMENT, LABEL, KEY_POINT, STEP_TEXT, and STEP_NARRATION as needed.
    - Output all SCENE_PLAN blocks before all MANIM_SCRIPT blocks.
    - Omit optional fields rather than returning empty tags.

    Allowed TYPE values: title_scene, question_scene, concept_scene, process_scene,
    comparison_scene, custom_manim_scene.
    Allowed LEARNING_ROLE values: intuition, definition, problem, formula, example,
    interpretation.
    Allowed VISUAL_MODE values: diagram, graph, motion, comparison, process, text.

    Teaching rules:
    - Scene 1 must be title_scene.
    - Every non-title scene must show meaningful learner-facing content throughout narration.
    - Standard scenes should use KEY_POINT, LABEL, FORMULA, or STEP_TEXT content.
    - Use STEP_TEXT immediately followed by matching STEP_NARRATION for ordered explanations.
    - Worked mathematics must show completed substitution, simplification, and final answer.
    - Teach meaning before notation and show graph meaning before algebra.
    - Every graph scene must be custom_manim_scene with concrete REQUIRED_VISUAL_ELEMENT values.
    - Use custom_manim_scene only when a concept benefits from actual spatial, graphical,
      simulated, networked, coded, or 3D explanation. Standard scenes remain preferable for
      titles, concise definitions, comparisons, formulas, and cumulative instructional steps.
    - A normal four-to-seven-scene video should contain two or three creative scenes when the
      topic benefits from them, never more than three.
    - Set ESSENTIAL_VISUAL true only when the requested graph, construction, simulation, code
      view, network, grid, or 3D visual is central to the user request.
    - Set REQUIRES_3D true only when the complete script genuinely uses 3D objects or camera.
    - Internal fields VISUAL, CODE_GOAL, ESSENTIAL_VISUAL, REQUIRES_3D, and MANIM_SCRIPT_REF
      are never learner-facing.

    {_COMPLETE_SCRIPT_CONTRACT}

    Minimal valid 2D example:
    <MANIM_SCRIPT id="scene_example_2d">
    from manim import *
    from manim_voiceover import VoiceoverScene
    from manim_voiceover.services.gtts import GTTSService

    class GeneratedScene(VoiceoverScene):
        def construct(self):
            self.set_speech_service(GTTSService(lang="en"))
            left = Circle(radius=0.8, color=BLUE_C).shift(LEFT * 2)
            right = Square(side_length=1.4, color=GREEN_C).shift(RIGHT * 2)
            arrow = Arrow(left.get_right(), right.get_left(), buff=0.2)
            with self.voiceover(text="A transformation connects the starting state to the result.") as tracker:
                self.play(GrowFromCenter(left), run_time=0.7)
                self.play(GrowArrow(arrow), GrowFromCenter(right), run_time=0.9)
                self.wait(max(0.1, tracker.duration - 1.6))
            self.wait(1.0)
    </MANIM_SCRIPT>

    Minimal valid 3D inheritance example:
    <MANIM_SCRIPT id="scene_example_3d">
    from manim import *
    from manim_voiceover import VoiceoverScene
    from manim_voiceover.services.gtts import GTTSService
    import numpy as np

    class GeneratedScene(VoiceoverScene, ThreeDScene):
        def construct(self):
            self.set_speech_service(GTTSService(lang="en"))
            self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)
            axes = ThreeDAxes()
            surface = Surface(lambda u, v: axes.c2p(u, v, 0.18 * (u*u + v*v)),
                              u_range=[-2, 2], v_range=[-2, 2], resolution=(16, 16))
            with self.voiceover(text="The bowl shape has one lowest region.") as tracker:
                self.play(Create(axes), FadeIn(surface), run_time=1.5)
                self.wait(max(0.1, tracker.duration - 1.5))
            self.wait(1.0)
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

    Keep good material and make the smallest changes needed. Scene 1 must remain title_scene.
    Preserve KEY_POINT values and STEP_TEXT/STEP_NARRATION pairs. Every non-title scene must
    retain meaningful learner-facing visual content. A graph scene must use custom_manim_scene,
    real axes or a number plane, and marked graph features. A worked math example must contain
    completed substitution, simplification, and final answer.

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

    You may add, remove, combine, split, or reorder scenes. Keep scene 1 as title_scene.
    Preserve useful material and improve learning roles, questions, visible points, steps,
    formulas, diagrams, graphs, networks, grids, code views, simulations, or 3D visuals as the
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

    Use the original teaching goal and preserve the intended visual ambition. Correct imports,
    class structure, 2D/3D inheritance, syntax, unresolved references, blocked operations, and
    static Manim compatibility issues. Return complete runnable files, never fragments.

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
    or compatibility errors shown in the tracebacks. Return complete replacement files, never
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
    The listed scenes failed initially and after focused correction, or could not pass static
    preflight. Create simpler, more reliable implementations of the same educational scenes.
    Return only one complete MANIM_SCRIPT block for every requested id, in the same order.
    Do not return JSON, markdown, commentary, or scripts for scenes that already rendered.

    Preserve narration, core concept, and meaningful visual explanation. Deliberately reduce
    technical fragility: use stable Manim primitives, fewer objects, simpler transformations,
    and fewer delicate APIs. Do not replace a scene with only headings, bullet points, or
    decorative motion. A graph must remain a real graph; a network must remain a visible state
    network; a grid-world must remain a meaningful grid-world explanation.

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
    Create one self-contained interactive educational HTML widget.
    Return ONLY a complete HTML document. No markdown or explanation.

    Core rule: build the smallest working interaction that teaches one important idea.
    Complexity is a failure unless the concept truly requires it.

    Teaching design:
    - Identify one clear learning objective and one obvious learner action.
    - Make the widget visibly specific to the requested topic; never make a generic concept lab.
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

        Create a simple, teacher-ready widget with one learning objective, one main learner
        action, immediate topic-specific feedback, and one short thing to try or notice.
        Choose the least complex interaction that makes the idea clearer than text alone.

        Output ONLY the complete HTML document.
    """).strip()


WIDGET_SIMPLE_FALLBACK_SYSTEM = _with_artifact_safety("""\
    Create a very small, reliable educational HTML widget from scratch.
    Return ONLY a complete standalone HTML document. No markdown or explanation.

    This is a fallback after a more ambitious widget failed. Do not repair or imitate the
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
    Revise an existing self-contained educational HTML widget.
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
        Existing widget: {original_title or 'Interactive widget'}
        Edit request: {edit_instructions.strip()}

        Revise the existing source below. Preserve unaffected behavior and keep the result
        simple, pedagogically coherent, and fully interactive.

        Original HTML:
        {original_html}

        Return ONLY the revised complete HTML document.
    """).strip()


WIDGET_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair one self-contained educational HTML widget.
    Return ONLY the fixed complete HTML document. No markdown or explanation.

    Fix the reported defect with the smallest useful change. Preserve the topic, learning
    objective, main interaction, and visual approach when possible. Do not expand the widget
    into a dashboard or add controls, metrics, canvas, or animation merely to satisfy repair.

    The repaired widget must use vanilla HTML/CSS/JS, addEventListener, visible feedback or
    state change after the learner acts, no external assets/network/storage, safe initialization
    order, and complete closing tags.
""")


def build_widget_repair_user_prompt(*, original_title: str | None, edit_instructions: str, prior_html: str, reason: str) -> str:
    return dedent(f"""\
        Widget/topic: {original_title or 'Interactive widget'}
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
    Create compact JSON for a last-resort topic-specific teaching widget.
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
