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


def _scene_body_ref(scene: dict[str, Any], index: int) -> str:
    existing = str(scene.get("manim_body_ref") or "").strip()
    if existing:
        return existing
    scene_id = str(scene.get("id") or index).strip()
    return f"scene_{scene_id}"


def _split_plan_and_bodies(plan: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Prepare a normalized plan for an LLM prompt without embedding Python in fields."""
    cloned = json.loads(json.dumps(plan or {}, ensure_ascii=False))
    bodies: list[tuple[str, str]] = []
    scenes = cloned.get("scenes")
    if not isinstance(scenes, list):
        return cloned, bodies

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        body = str(scene.pop("manim_body", "") or "").strip()
        if scene.get("type") == "custom_manim_scene" or body:
            ref = _scene_body_ref(scene, index)
            scene["manim_body_ref"] = ref
            if body:
                bodies.append((ref, body))
    return cloned, bodies


def _tag_value(value: Any) -> str:
    """Escape only transport-significant characters in prompt examples/current plans."""
    return html.escape(str(value or "").strip(), quote=False)


def _tag(tag: str, value: Any) -> str:
    return f"<{tag}>{_tag_value(value)}</{tag}>"


def _format_structured_plan(plan: dict[str, Any]) -> str:
    """Serialize a plan into the same low-fragility tagged format requested from the model."""
    transport_plan, _bodies = _split_plan_and_bodies(plan)
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
        ("CODE_GOAL", "code_goal"),
        ("MANIM_BODY_REF", "manim_body_ref"),
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


def _format_body_blocks(bodies: list[tuple[str, str]], tag: str = "MANIM_BODY") -> str:
    if not bodies:
        return "(none)"
    return "\n\n".join(
        f'<{tag} id="{html.escape(ref, quote=True)}">\n{body}\n</{tag}>'
        for ref, body in bodies
    )


STRUCTURED_VIDEO_SYSTEM = _with_artifact_safety("""\
    Create one concise educational Manim video in one response. Do not use markdown fences,
    JSON, or commentary. Use only the tagged transport below.

    Output order:
    1. One VIDEO_META block.
    2. Four to seven complete SCENE_PLAN blocks.
    3. One MANIM_BODY block for each custom_manim_scene.

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
    <VISUAL>Internal production direction describing the visible action.</VISUAL>
    <DURATION_SEC>8</DURATION_SEC>
    </SCENE_PLAN>

    <SCENE_PLAN id="2">
    <TYPE>process_scene</TYPE>
    <LEARNING_ROLE>example</LEARNING_ROLE>
    <LEARNER_QUESTION>What should the learner understand here?</LEARNER_QUESTION>
    <VISUAL_MODE>process</VISUAL_MODE>
    <TITLE>Short scene title</TITLE>
    <NARRATION>Brief introduction to the sequence.</NARRATION>
    <VISUAL>Internal production direction for the supporting visual.</VISUAL>
    <FORMULA>portable plain-text formula when needed</FORMULA>
    <STEP_TEXT>First visible instructional step</STEP_TEXT>
    <STEP_NARRATION>Natural spoken explanation of that first step.</STEP_NARRATION>
    <STEP_TEXT>Second visible instructional step</STEP_TEXT>
    <STEP_NARRATION>Natural spoken explanation of that second step.</STEP_NARRATION>
    <STEP_TEXT>Final visible step or conclusion</STEP_TEXT>
    <STEP_NARRATION>Natural spoken explanation of the final step.</STEP_NARRATION>
    <DURATION_SEC>18</DURATION_SEC>
    </SCENE_PLAN>

    For a custom scene only:
    <SCENE_PLAN id="3">
    <TYPE>custom_manim_scene</TYPE>
    <LEARNING_ROLE>interpretation</LEARNING_ROLE>
    <VISUAL_MODE>motion</VISUAL_MODE>
    <TITLE>Topic-specific motion</TITLE>
    <NARRATION>Student-facing explanation.</NARRATION>
    <VISUAL>Internal production direction for the animation.</VISUAL>
    <REQUIRED_VISUAL_ELEMENT>first concrete element</REQUIRED_VISUAL_ELEMENT>
    <REQUIRED_VISUAL_ELEMENT>second concrete element</REQUIRED_VISUAL_ELEMENT>
    <ESSENTIAL_VISUAL>false</ESSENTIAL_VISUAL>
    <CODE_GOAL>Internal instruction describing what the code must demonstrate.</CODE_GOAL>
    <MANIM_BODY_REF>scene_3</MANIM_BODY_REF>
    </SCENE_PLAN>

    <MANIM_BODY id="scene_3">
    body statements only
    </MANIM_BODY>

    Transport rules:
    - Never output JSON, Python dictionaries, markdown fences, or prose outside the tags.
    - Put each field in its own opening and closing tag. Close each SCENE_PLAN before starting
      the next one. Omit optional fields rather than returning empty tags.
    - Repeat REQUIRED_VISUAL_ELEMENT, LABEL, and KEY_POINT tags for multiple values.
    - For a sequence, repeat STEP_TEXT and immediately follow each one with its matching
      STEP_NARRATION. CALCULATION_STEP may be read for legacy compatibility, but new output
      must use STEP_TEXT.
    - Keep each field compact. Do not place structural closing tags inside field values.
    - Output all SCENE_PLAN blocks before any MANIM_BODY blocks.

    Field visibility rules:
    - Learner-facing fields are TITLE, SUBTITLE, LEARNER_QUESTION, NARRATION, LABEL, KEY_POINT,
      FORMULA, STEP_TEXT, and STEP_NARRATION. Write only educational content in these fields.
    - VISUAL, ESSENTIAL_VISUAL, CODE_GOAL, MANIM_BODY_REF, and MANIM_BODY are internal production fields. They
      may describe fades, movement, layout, camera behavior, or implementation, but they are
      never shown to learners.
    - Never place production directions such as how text enters, exits, moves, or transitions
      inside learner-facing fields.

    Allowed values:
    - TYPE: title_scene, question_scene, concept_scene, process_scene, comparison_scene,
      custom_manim_scene.
    - LEARNING_ROLE: intuition, definition, problem, formula, example, interpretation.
    - VISUAL_MODE: diagram, graph, motion, comparison, process, text.

    Teaching rules:
    - Scene 1 must be title_scene. Use only the scenes needed to teach clearly.
    - Every non-title scene must show meaningful learner-facing visual content throughout the
      narration. Never create a long scene that displays only its heading.
    - Every non-title scene must include at least one of these: two or more KEY_POINT or LABEL
      values, one or more STEP_TEXT values, a displayed FORMULA, or a topic-specific custom
      Manim visual that visibly explains the idea.
    - KEY_POINT is for concise learner-facing bullets or cards when a scene does not need an
      ordered sequence. Use two to five topic-specific points rather than generic filler.
    - Teach meaning before notation. Define unfamiliar ideas and the problem a formula solves.
    - Graph ideas must show the relevant graph feature before algebra. Every graph scene must
      be custom_manim_scene and must name concrete REQUIRED_VISUAL_ELEMENT fields.
    - Use STEP_TEXT and STEP_NARRATION for any ordered instructional sequence: calculations,
      scientific processes, historical developments, procedures, comparisons, coding logic,
      cause-and-effect chains, or other staged explanations.
    - Every STEP_TEXT must describe a visible learner-facing state, action, relationship, or
      conclusion. Every matching STEP_NARRATION must explain that step naturally and clearly.
    - For worked mathematics, steps must contain completed substitution, simplification, and
      final answer. Never return instructions such as "compute the roots" as step text.
    - Prefer a standard process_scene or concept_scene for text-based sequences so the stable
      renderer can preserve every step and synchronize narration. Do not use a custom scene
      merely to animate a list of steps.
    - If narration uses a formula, include FORMULA and show it. Use portable text such as
      x = (-b +/- sqrt(b^2 - 4ac)) / (2a), not LaTeX or special math glyphs.
    - LABEL is optional and topic-specific. Do not use Concept, Equation, Step, Input, Output,
      Result, or Example as filler labels.
    - Use custom scenes whenever moving objects, changing quantities, spatial relationships,
      measurements, transformations, concrete everyday examples, diagrams, timelines, graphs,
      or simulations would make the explanation clearer.
    - A broad four-to-seven-scene educational video should normally contain two or three simple
      custom_manim_scene visuals. Other scenes may use stable components with KEY_POINT, LABEL,
      FORMULA, or STEP_TEXT content. Do not spend the response budget on custom code where a
      stable component already teaches the idea clearly.
    - Keep each custom visual focused and reliable: use roughly two to five main visual objects,
      animate the central relationship, and keep important objects visible while narrated.
      A small clear animation is better than a complex fragile one.
    - Set ESSENTIAL_VISUAL to true only for a graph or a geometric/construction visual that is
      explicitly required by the user. Otherwise use false or omit it.
    - Do not display internal scene-type names.

    Every custom scene needs a unique MANIM_BODY_REF and matching MANIM_BODY block. The body is
    inserted directly inside GeneratedScene.construct(). The runtime contract is exact:
    - self is the active VoiceoverScene. Use self.play(...), self.add(...), self.wait(...), and
      with self.voiceover(text=...) as tracker.
    - scene is only a Python metadata dictionary. Never call scene.play(...), scene.add(...),
      scene.wait(...), or scene.voiceover(...).
    - Manim is already imported as mn. VoiceoverScene and GTTSService are already configured.
      Do not write import statements. Use mn.Circle(...), mn.FadeIn(...), and other mn-prefixed
      constructors and animations.
    - The wrapper already provides: title, narration, labels, visual, formula, steps,
      step_narrations, calculation_steps as a legacy alias, key_points, learning_role,
      learner_question, visual_mode, required_visual_elements, essential_visual, bg, label(...),
      formula_label(...), instruction_step_label(...), calculation_step_label(...),
      add_instruction_step(...), next_calculation_step(...), and wait_for_voiceover(...).

    Canonical valid MANIM_BODY pattern. Follow this structure with topic-specific objects:
    <MANIM_BODY id="scene_example">
    title_mob = label(title, size=34).to_edge(mn.UP)
    left_object = mn.Circle(radius=0.8, color=mn.BLUE_C).shift(mn.LEFT * 2)
    right_object = mn.Square(side_length=1.5, color=mn.GREEN_C).shift(mn.RIGHT * 2)
    relationship = mn.Arrow(left_object.get_right(), right_object.get_left(), buff=0.2)
    with self.voiceover(text=narration) as tracker:
        self.play(mn.FadeIn(title_mob), run_time=0.5)
        self.play(mn.GrowFromCenter(left_object), run_time=0.7)
        self.play(mn.GrowArrow(relationship), mn.GrowFromCenter(right_object), run_time=0.9)
        wait_for_voiceover(tracker, 2.1)
    self.wait(1.0)
    </MANIM_BODY>

    Custom-body rules:
    - Body statements only. No imports, class, def, construct method, files, images, SVG, Tex,
      MathTex, network, random, external libraries, eval, exec, or system access.
    - Begin every MANIM_BODY at column 1. Indent only statements nested inside with, if, for,
      or while. Return executable Python statements, never pseudocode or planning notes.
    - Use simple mn-prefixed primitives such as mn.Text, mn.Circle, mn.Square, mn.Rectangle,
      mn.RoundedRectangle, mn.Dot, mn.Line, mn.DashedLine, mn.Arrow, mn.Arc, mn.VGroup,
      mn.NumberLine, mn.Axes, and mn.NumberPlane.
    - Create at least two visible topic-specific objects, or one substantial explanatory
      structure such as axes, a number line, a geometric construction, or a graph. A title or
      heading does not count as a topic-specific object.
    - Include at least one self.voiceover block and at least three self.play calls. Animate
      every important object with self.play(...) or add it with self.add(...).
    - Include meaningful topic-specific motion. Graph bodies must create mn.Axes or
      mn.NumberPlane, draw the relationship, and mark the listed visual features.
    - Do not animate decorative motion alone. Movement must show the relationship described by
      the narration. Keep two to five main objects visible while they are discussed.
    - When a custom scene truly needs instructional steps, keep earlier steps visible, add each
      new step beneath the previous ones, narrate each step, and hold the completed sequence for
      at least 2.5 seconds. Prefer add_instruction_step(...).
    - Display FORMULA when present. Keep strings on one line and close every quote, bracket,
      and parenthesis.

    Before emitting each MANIM_BODY, silently verify all seven checks:
    1. No import, class, def, or construct wrapper.
    2. self is used for scene methods; scene is never used as the active scene.
    3. All Manim constructors and animations use the mn. prefix.
    4. At least one self.voiceover block exists.
    5. At least two topic-specific objects or one substantial structure exists.
    6. At least three self.play calls exist, and every important object is added or animated.
    7. The body is complete executable Python, not pseudocode.

""")


def build_structured_video_user_prompt(goal: str) -> str:
    return dedent(f"""\
        Create a concise educational video about:
        {goal}

        Return VIDEO_META, complete SCENE_PLAN blocks, and matching raw MANIM_BODY blocks.
        Do not return JSON.
    """).strip()


STRUCTURED_VIDEO_PLAN_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair one educational-video plan. Do not use markdown fences or JSON. Return one complete
    VIDEO_META block, complete SCENE_PLAN blocks, and MANIM_BODY blocks only for custom scenes
    that are new or changed. Omitted existing bodies will be preserved.

    Use the exact field tags from the supplied current plan. Keep good material and make the
    smallest changes needed. Close every field and SCENE_PLAN tag. A graph scene must use real
    axes or a number plane, draw a coordinate-based relationship, and mark the required
    features. Preserve KEY_POINT values and STEP_TEXT/STEP_NARRATION pairs. Every non-title
    scene must retain visible learner-facing content beyond its heading. A worked mathematics
    example must show completed substitution, simplification, and final
    answer. Keep earlier steps visible and hold the completed sequence. Every MANIM_BODY is
    inserted inside GeneratedScene.construct(): self is the active VoiceoverScene, scene is
    metadata only, Manim is already imported as mn, and no imports/classes/functions are
    allowed. Use self.voiceover plus at least three self.play calls and at least two
    topic-specific visual objects. Begin each body at column 1 and indent only nested statements.
""")


def build_structured_video_plan_repair_prompt(*, plan: dict, errors: list[str]) -> str:
    _transport_plan, bodies = _split_plan_and_bodies(plan)
    error_lines = "\n".join(f"- {error}" for error in errors) or "- Improve the plan."
    return dedent(f"""\
        Current plan:
        <ORIGINAL_PLAN>
        {_format_structured_plan(plan)}
        </ORIGINAL_PLAN>

        Current custom bodies:
        {_format_body_blocks(bodies, tag="ORIGINAL_MANIM_BODY")}

        Required corrections:
        {error_lines}

        Return the complete repaired tagged plan and only changed or new MANIM_BODY blocks.
        Do not return JSON.
    """).strip()


STRUCTURED_VIDEO_EDIT_SYSTEM = _with_artifact_safety("""\
    Edit one structured educational video. Do not use markdown fences or JSON. Return one
    complete VIDEO_META block, complete SCENE_PLAN blocks, and MANIM_BODY blocks only for
    custom scenes that are new or changed. Omitted existing bodies will be preserved.

    You may add, remove, combine, split, or reorder scenes. Keep scene 1 as title_scene.
    Preserve useful material and improve learning_role, learner_question, visual_mode,
    required_visual_elements, essential_visual, formula, key_points, steps, step_narrations,
    and optional labels as needed.
    Teach meaning before notation. Graph explanations show the graph feature before algebra.
    Use KEY_POINT for concise bullets/cards and STEP_TEXT with STEP_NARRATION for ordered
    explanations in any subject. Every non-title scene must show meaningful visible content;
    never leave a long narration over a heading-only slide. Worked math examples show completed
    substitution, simplification, and final answer.

    Use the exact field tags shown in the original plan. Close every field and SCENE_PLAN tag.
    Custom code follows the generation rules. In every MANIM_BODY, self is the active
    VoiceoverScene, scene is metadata only, and Manim is already imported as mn. Do not add
    imports/classes/functions. Use self.voiceover, at least three self.play calls, and at least
    two topic-specific visual objects. Keep earlier instructional steps visible, narrate each
    step, and hold the completed sequence. Prefer a standard scene for step-based teaching.
""")


def build_structured_video_edit_user_prompt(original_plan: dict, edit_instructions: str) -> str:
    _transport_plan, bodies = _split_plan_and_bodies(original_plan)
    return dedent(f"""\
        Original plan:
        <ORIGINAL_PLAN>
        {_format_structured_plan(original_plan)}
        </ORIGINAL_PLAN>

        Original custom bodies:
        {_format_body_blocks(bodies, tag="ORIGINAL_MANIM_BODY")}

        Edit request:
        {edit_instructions}

        Return the complete edited tagged plan and only changed or new MANIM_BODY blocks.
        Do not return JSON.
    """).strip()


STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair one Manim construct-body. Return corrected Python body statements only.
    Preserve the teaching goal and make the smallest useful correction.

    Runtime contract:
    - The body is inserted inside GeneratedScene.construct().
    - self is the active VoiceoverScene. scene is only a metadata dictionary.
    - Use self.play, self.add, self.wait, and self.voiceover. Never use scene.play or similar.
    - Manim is already imported as mn. Do not include imports. Use mn. prefixes everywhere.
    - The wrapper provides title, narration, labels, visual, formula, steps, step_narrations,
      calculation_steps, key_points, learning_role, learner_question, visual_mode,
      required_visual_elements, essential_visual, bg, label(...), formula_label(...),
      instruction_step_label(...), calculation_step_label(...), add_instruction_step(...),
      next_calculation_step(...), and wait_for_voiceover(...).

    Minimum valid shape:
    title_mob = label(title, size=34).to_edge(mn.UP)
    left_object = mn.Circle(radius=0.8, color=mn.BLUE_C).shift(mn.LEFT * 2)
    right_object = mn.Square(side_length=1.5, color=mn.GREEN_C).shift(mn.RIGHT * 2)
    arrow = mn.Arrow(left_object.get_right(), right_object.get_left(), buff=0.2)
    with self.voiceover(text=narration) as tracker:
        self.play(mn.FadeIn(title_mob), run_time=0.5)
        self.play(mn.GrowFromCenter(left_object), run_time=0.7)
        self.play(mn.GrowArrow(arrow), mn.GrowFromCenter(right_object), run_time=0.9)
        wait_for_voiceover(tracker, 2.1)
    self.wait(1.0)

    Return body statements only: no imports, class, def, construct wrapper, files, images, SVG,
    Tex, MathTex, network, random, external libraries, eval, exec, or system access. Begin at
    column 1 and indent only nested statements. Create at least two topic-specific visible
    objects or one substantial graph/construction, use at least one self.voiceover block and
    three self.play calls, and animate every important object. A graph must create mn.Axes or
    mn.NumberPlane, draw the relationship, and mark the required features. Keep important
    objects visible during narration. Display formula when present and close every quote,
    bracket, and parenthesis.
""")


STRUCTURED_VIDEO_BATCH_CREATIVE_REPAIR_SYSTEM = _with_artifact_safety("""\
    Repair several invalid Manim construct-bodies in one response. Return only one complete
    MANIM_BODY block for every requested id, in the same order. Do not return JSON, markdown,
    commentary, imports, classes, functions, or prose outside the blocks.

    Each body is inserted inside GeneratedScene.construct(). self is the active
    VoiceoverScene; scene is only metadata. Use self.play, self.add, self.wait, and
    self.voiceover. Manim is already imported as mn, so every Manim constructor and animation
    must use the mn. prefix and no imports are allowed.

    Each repaired body must create at least two topic-specific visible objects or one
    substantial explanatory structure, contain at least one self.voiceover block and three
    self.play calls, animate or add every important object, and keep the educational objects
    visible while narrated. Return executable body statements, not pseudocode.

    Canonical shape:
    <MANIM_BODY id="requested_id">
    title_mob = label(title, size=34).to_edge(mn.UP)
    left_object = mn.Circle(radius=0.8, color=mn.BLUE_C).shift(mn.LEFT * 2)
    right_object = mn.Square(side_length=1.5, color=mn.GREEN_C).shift(mn.RIGHT * 2)
    arrow = mn.Arrow(left_object.get_right(), right_object.get_left(), buff=0.2)
    with self.voiceover(text=narration) as tracker:
        self.play(mn.FadeIn(title_mob), run_time=0.5)
        self.play(mn.GrowFromCenter(left_object), run_time=0.7)
        self.play(mn.GrowArrow(arrow), mn.GrowFromCenter(right_object), run_time=0.9)
        wait_for_voiceover(tracker, 2.1)
    self.wait(1.0)
    </MANIM_BODY>
""")


def build_structured_video_batch_creative_repair_prompt(
    *,
    failures: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for failure in failures:
        ref = str(failure.get("ref") or "scene").strip()
        scene = failure.get("scene") if isinstance(failure.get("scene"), dict) else {}
        errors = failure.get("errors") if isinstance(failure.get("errors"), list) else []
        original_body = str(failure.get("original_body") or "").strip()
        blocks.extend([
            f'<REPAIR_REQUEST id="{html.escape(ref, quote=True)}">',
            f'<SCENE_DATA>{html.escape(json.dumps(scene, ensure_ascii=True, separators=(",", ":")), quote=False)}</SCENE_DATA>',
            f'<VALIDATION_ERRORS>{html.escape("; ".join(str(error) for error in errors), quote=False)}</VALIDATION_ERRORS>',
            '<ORIGINAL_BODY>',
            original_body or '(empty)',
            '</ORIGINAL_BODY>',
            '</REPAIR_REQUEST>',
            '',
        ])
    return "\n".join(blocks).strip()


def build_structured_video_creative_repair_prompt(
    *,
    scene: dict,
    original_body: str,
    failure_stage: str,
    error_detail: str,
) -> str:
    return dedent(f"""\
        Scene: {json.dumps(scene, ensure_ascii=True, separators=(",", ":"))}
        Failure stage: {failure_stage}
        Error: {error_detail}

        Original body:
        {original_body}

        Return the repaired body statements only.
    """).strip()


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
