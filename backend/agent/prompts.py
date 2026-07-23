# backend/agent/prompts.py
from __future__ import annotations

import json
from textwrap import dedent


# -------- STRUCTURED VIDEO PROMPTS --------

STRUCTURED_VIDEO_SYSTEM = dedent("""\
    Create one valid JSON object for a short educational Manim video.
    Return JSON only. Choose the scene count needed for the topic.

    Shape:
    {
      "title": "short title",
      "subtitle": "short subtitle",
      "audience": "general or specific audience",
      "scenes": [
        {
          "id": 1,
          "type": "title_scene | question_scene | concept_scene | process_scene | comparison_scene | custom_manim_scene",
          "learning_role": "intuition | definition | problem | formula | example | interpretation",
          "learner_question": "what the learner should understand here",
          "visual_mode": "diagram | graph | motion | comparison | process | text",
          "title": "short scene title",
          "subtitle": "optional",
          "narration": "student-facing explanation",
          "visual": "specific visible action or relationship",
          "required_visual_elements": ["optional concrete element"],
          "labels": ["optional labels for standard components only"],
          "formula": "optional plain-text formula shown on screen",
          "calculation_steps": ["optional explicit substitution", "simplification", "final answer"],
          "duration_sec": 12,
          "code_goal": "custom scene only",
          "manim_body": "custom scene only: escaped Python construct-body code"
        }
      ]
    }

    Teaching rules:
    - Scene 1 is title_scene. Use the fewest scenes that teach the topic clearly.
    - Teach meaning before notation. Define unfamiliar ideas and the problem a formula solves
      before presenting or deriving it. Do not begin with derivation unless requested.
    - Graph-related ideas must first show and explain the relevant graph feature, then connect it
      to algebra. Every visual_mode="graph" scene must be custom_manim_scene.
    - Example: for "explain quadratic formula," graph a quadratic and define roots as x-intercepts;
      then introduce the formula, work one example, and mark the answers back on the graph.
    - A worked math example must visibly show actual substitution, simplification, and final answer
      in calculation_steps. Never use instructions such as "compute the roots" as a substitute.
    - If narration uses a formula, include formula and show it. Use portable plain text such as
      x = (-b +/- sqrt(b^2 - 4ac)) / (2a), not LaTeX or special math glyphs.
    - labels are optional. Use them only when a standard component needs named parts. Never use
      generic labels such as Concept, Equation, Step, Input, Output, Result, or Example.
    - Use custom_manim_scene for graphs, geometric constructions, changing systems, or
      topic-specific motion. Normally use no more than two custom scenes.
    - Do not display internal names such as CONCEPT SCENE or PROCESS SCENE.

    Every custom_manim_scene must include manim_body in this response.
    The wrapper provides: scene, title, narration, labels, visual, formula, calculation_steps,
    learning_role, learner_question, visual_mode, required_visual_elements, bg, label(...),
    formula_label(...), calculation_step_label(...), and wait_for_voiceover(...).

    Custom-body rules:
    - Body statements only. No imports, class, def, files, images, SVG, Tex, MathTex, network,
      random, external libraries, eval, exec, or system access. Use mn. prefixes.
    - Simple Manim objects are allowed, including Text, Circle, Rectangle, RoundedRectangle,
      Dot, Line, DashedLine, Arrow, Arc, VGroup, NumberLine, Axes, and NumberPlane.
    - Include at least 2 voiceover blocks, 4 self.play calls, and meaningful movement.
    - For visual_mode="graph", create Axes or NumberPlane, draw/plot the relationship, and mark
      the graph features named in required_visual_elements.
    - For learning_role="example", visibly animate calculation_steps and emphasize the answer.
    - If formula is present, display it with formula_label(formula) or mn.Text(formula).
    - Keep strings on one line and close every quote, bracket, and parenthesis.

    The JSON must be complete and not truncated.
""")


def build_structured_video_user_prompt(goal: str) -> str:
    return dedent(f"""\
        Create a concise educational video about:
        {goal}

        Return the complete JSON object, including manim_body in every custom scene.
    """).strip()


STRUCTURED_VIDEO_PLAN_REPAIR_SYSTEM = dedent("""\
    Repair one educational-video JSON plan. Return complete valid JSON only.
    Keep good material and make the smallest changes needed to satisfy the listed errors.
    A graph scene must be custom Manim with real axes/number plane, a plotted or coordinate-based
    relationship, and marked features. A worked math example must contain explicit
    calculation_steps for substitution, simplification, and final answer. Keep meaning before
    notation and preserve visible formulas. Include complete manim_body in every custom scene.
""")


def build_structured_video_plan_repair_prompt(*, plan: dict, errors: list[str]) -> str:
    return dedent(f"""\
        Plan:
        {json.dumps(plan, ensure_ascii=True, separators=(",", ":"))}

        Errors:
        {json.dumps(errors, ensure_ascii=True)}

        Return the complete repaired JSON object only.
    """).strip()


STRUCTURED_VIDEO_EDIT_SYSTEM = dedent("""\
    Edit one structured educational-video JSON object. Return complete valid JSON only.
    You may add, remove, combine, split, or reorder scenes; do not force a scene count.

    Preserve useful material and unaffected manim_body code. Keep scene 1 as title_scene.
    Preserve or improve learning_role, learner_question, visual_mode, required_visual_elements,
    formula, calculation_steps, and optional labels. Teach meaning before notation.
    Every graph scene must be custom Manim and show the graph feature before algebra.
    Every worked math example must visibly show substitution, simplification, and final answer.

    Revised custom code follows the generation rules: body statements only, mn. prefixes,
    simple primitives, no external access, at least 2 voiceovers and 4 plays, meaningful motion,
    visible formulas, visible calculation steps, and a real graph when visual_mode is graph.
""")


def build_structured_video_edit_user_prompt(original_plan: dict, edit_instructions: str) -> str:
    return dedent(f"""\
        Original video object:
        {json.dumps(original_plan, ensure_ascii=True, separators=(",", ":"))}

        Edit request:
        {edit_instructions}

        Return the complete edited JSON object only.
    """).strip()


STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM = dedent("""\
    Repair one Manim construct-body. Return corrected Python body statements only.
    Preserve the teaching goal and make the smallest useful correction.

    The wrapper provides: scene, title, narration, labels, visual, formula, calculation_steps,
    learning_role, learner_question, visual_mode, required_visual_elements, bg, label(...),
    formula_label(...), calculation_step_label(...), and wait_for_voiceover(...).

    Use mn. prefixes and simple primitives. No imports, class, def, files, images, SVG, Tex,
    MathTex, network, random, external libraries, eval, exec, or system access. Include at least
    2 voiceover blocks, 4 self.play calls, and meaningful movement. For a graph scene, create
    Axes or NumberPlane, draw/plot the relationship, and visibly mark the required features.
    For a worked example, visibly animate calculation_steps and emphasize the final answer.
    Display formula when present. Close every quote, bracket, and parenthesis.
""")


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

WIDGET_SYSTEM = dedent("""\
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


WIDGET_SIMPLE_FALLBACK_SYSTEM = dedent("""\
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


WIDGET_EDIT_SYSTEM = dedent("""\
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


WIDGET_REPAIR_SYSTEM = dedent("""\
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
WIDGET_FALLBACK_SPEC_SYSTEM = dedent("""\
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

QUIZ_GENERATE_SYSTEM = dedent("""\
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


QUIZ_EDIT_SYSTEM = dedent("""\
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

STORY_EDIT_PATCH_SYSTEM = dedent("""\
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
      drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar, drawCharacterTemplate.
    - Use x as the CanvasRenderingContext2D. Use relative positions based on w and h.
    - Prefer diagrams, arrows, flows, labeled-looking shapes, cycles, timelines, graphs, particles, before/after panels, or cause/effect visuals.
    - Do not rely on external images, fonts, libraries, fetch, DOM access, window, document, localStorage, or network calls.
    - Do not use markdown, comments-only output, or natural language explanation inside draw_js.
    - If a scene currently falls back to the generic character/table animation, replace its draw_js with a concrete topic-related visualization.
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


STORY_EDIT_FULL_HTML_SYSTEM = dedent("""\
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
