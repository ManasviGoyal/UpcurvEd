# backend/agent/prompts.py
import json
from textwrap import dedent

# -------- STRUCTURED VIDEO SCENE-OBJECT PROMPTS --------

STRUCTURED_VIDEO_SYSTEM = dedent("""\
    You create one complete JSON video object for a short educational Manim video.
    Return ONLY valid JSON. No markdown, no commentary, and no Python outside JSON strings.

    You decide how many scenes the lesson needs. Do not target a fixed scene count.
    Use the fewest scenes that explain the topic clearly, with a sensible total duration.

    JSON shape:
    {
      "title": "short lesson title",
      "subtitle": "short subtitle",
      "audience": "general or a more specific audience",
      "scenes": [
        {
          "id": 1,
          "type": "title_scene | question_scene | concept_scene | process_scene | comparison_scene | custom_manim_scene",
          "title": "short scene title",
          "subtitle": "optional short subtitle",
          "narration": "student-facing narration only",
          "visual": "specific thing that should appear or change on screen",
          "labels": ["2 to 5 short topic-specific labels"],
          "duration_sec": 12,
          "formula": "optional plain-text formula or equation that must appear on screen",
          "code_goal": "custom_manim_scene only: concrete animation goal",
          "manim_body": "custom_manim_scene only: escaped Python construct-body code"
        }
      ]
    }

    Planning rules:
    - Scene 1 must be title_scene.
    - Choose the number and order of scenes based on the requested topic and scope.
    - Standard scenes should use question_scene, concept_scene, process_scene, or comparison_scene.
    - Use custom_manim_scene only when custom movement materially improves understanding.
    - Normally use no more than two custom_manim_scene entries.
    - Narration must sound like a teacher explaining the exact topic to students.
    - Use topic-specific facts, labels, relationships, and examples. Avoid generic filler.
    - If narration mentions a formula, equation, mathematical law, ratio, proportionality,
      numerical relationship, or symbolic rule, include it in the scene's formula field.
    - Never mention a formula only in narration. The formula must be visible on screen.
    - Write formulas as readable plain Unicode text, for example F = G × (m₁ × m₂) / r².
      Do not use LaTeX, Tex, or MathTex syntax.
    - Labels must communicate actual subject content. Do not use generic labels such as
      Equation, Formula, Concept, Process, Input, Output, Step, Result, or Example.
    - Keep titles, subtitles, formulas, and labels short enough to fit on screen.

    For every custom_manim_scene, include manim_body in this same JSON response.
    manim_body is pasted inside GeneratedScene.construct(). The wrapper already provides:
        scene, title, narration, labels, visual, formula, bg
        label(text, size=26, color=mn.WHITE)
        formula_label(text, size=30, color=mn.YELLOW)
        wait_for_voiceover(tracker, used_time)

    Custom-body reliability rules:
    - Return body statements only inside the JSON string. No imports, class, or def.
    - Use mn. prefixes, for example mn.Circle, mn.Text, mn.LEFT.
    - Use only simple primitives: mn.Text, mn.Circle, mn.Rectangle, mn.RoundedRectangle,
      mn.Dot, mn.Line, mn.Arrow, mn.Arc, mn.VGroup, mn.NumberLine, and mn.Axes.
    - No files, images, SVG, Tex, MathTex, network, random, external libraries, or system access.
    - Include at least 2 with self.voiceover(text="...") blocks.
    - Include at least 4 self.play calls total.
    - Include real movement or change such as .animate, mn.Transform,
      mn.ReplacementTransform, mn.MoveAlongPath, mn.GrowArrow, mn.Rotate, or mn.Create.
    - If formula is non-empty, display it visibly with formula_label(formula) or mn.Text(formula).
      Keep it on screen while the narration explains the relationship.
    - Keep strings on one line and make every parenthesis and quote complete.
    - Do not fade out every object at the end; the wrapper performs cleanup.

    The complete response must be valid JSON and must not be truncated.
""")


def build_structured_video_user_prompt(goal: str) -> str:
    return dedent(f"""\
        Create a short educational video about:
        {goal}

        Decide the appropriate number of scenes and return the complete JSON video object.
        Include manim_body inside any custom_manim_scene in this same response.
        Whenever the explanation uses math or a formula, include a visible formula field.
    """).strip()


STRUCTURED_VIDEO_EDIT_SYSTEM = dedent("""\
    You edit one complete JSON video object for an educational Manim video.
    Return ONLY valid JSON. No markdown, no commentary, and no Python outside JSON strings.

    Keep the same schema used by the original object. You may add, remove, combine, split,
    or reorder scenes when the user's edit requires it. Do not force a fixed scene count.

    Editing rules:
    - Apply the user's request while preserving useful existing material.
    - Scene 1 must remain title_scene.
    - Preserve an existing custom scene's manim_body when that scene is not affected.
    - When a custom scene changes, return its complete revised manim_body in the same JSON.
    - Preserve existing formula fields unless the edit changes the underlying math.
    - Add or correct formula whenever edited narration mentions an equation, mathematical law,
      ratio, proportionality, numerical relationship, or symbolic rule.
    - Keep formula, narration, labels, and custom manim_body synchronized.
    - Never mention a formula only in narration; it must remain visible on screen.
    - Use custom_manim_scene only where custom motion materially improves the explanation.
    - Keep narration student-facing, factual, topic-specific, and concise.

    Custom manim_body uses the same provided wrapper and restrictions as generation:
    body statements only; mn. prefixes; simple primitives; no imports, files, images,
    SVG, Tex, MathTex, network, random, or system access; at least 2 voiceover blocks;
    at least 4 self.play calls; meaningful movement; and visible formula text whenever
    the scene's formula field is non-empty.
""")


def build_structured_video_edit_user_prompt(original_plan: dict, edit_instructions: str) -> str:
    return dedent(f"""\
        Original JSON video object:
        {json.dumps(original_plan, ensure_ascii=True, indent=2)}

        User edit request:
        {edit_instructions}

        Return the complete edited JSON video object only.
        Preserve unaffected manim_body code and revise affected custom code in this same response.
    """).strip()


STRUCTURED_VIDEO_CREATIVE_REPAIR_SYSTEM = dedent("""\
    You repair one Manim construct-body for an existing educational scene.
    Return ONLY corrected Python body statements. No markdown, imports, class, def, or explanation.

    The body is pasted inside GeneratedScene.construct(). The wrapper already provides:
        scene, title, narration, labels, visual, formula, bg
        label(text, size=26, color=mn.WHITE)
        formula_label(text, size=30, color=mn.YELLOW)
        wait_for_voiceover(tracker, used_time)

    Make the smallest useful correction that preserves the scene's educational goal and visual idea.

    Hard rules:
    - Use mn. prefixes.
    - Use only mn.Text, mn.Circle, mn.Rectangle, mn.RoundedRectangle, mn.Dot,
      mn.Line, mn.Arrow, mn.Arc, mn.VGroup, mn.NumberLine, and mn.Axes.
    - No imports, files, images, SVG, Tex, MathTex, network, random, external libraries,
      eval, exec, subprocess, os, pathlib, or system access.
    - Include at least 2 with self.voiceover(text="...") blocks.
    - Include at least 4 self.play calls total.
    - Include meaningful movement or transformation.
    - If formula is non-empty, display it using formula_label(formula) or mn.Text(formula).
      Do not use Tex or MathTex.
    - Keep strings on one line. Close every quote, bracket, and parenthesis.
    - Do not fade out everything at the end; the wrapper performs cleanup.
""")


def build_structured_video_creative_repair_prompt(
    *,
    scene: dict,
    original_body: str,
    failure_stage: str,
    error_detail: str,
) -> str:
    return dedent(f"""\
        Scene object:
        {json.dumps(scene, ensure_ascii=True, indent=2)}

        Failure stage: {failure_stage}

        Validation or Manim error:
        {error_detail}

        Original construct-body:
        {original_body}

        Repair this one body so it satisfies all rules and renders in the provided wrapper.
        Return body statements only.
    """).strip()


# -------- WIDGET PROMPTS --------

WIDGET_SYSTEM = dedent("""\
    You generate self-contained interactive educational HTML widgets.
    Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

    This widget runs in a sandboxed iframe inside a desktop app. It must be robust.

    Primary teaching goal:
    - Make the learner DO the concept, not just watch an animation.
    - The widget must be visibly about the exact requested topic. Do not return a generic "concept lab" or abstract motion demo.
    - Every widget must have ONE obvious primary student action.
    - If the concept involves moving, sorting, stacking, comparing, choosing, balancing, graphing, testing, or solving a puzzle,
      the learner must directly manipulate the main visual objects by clicking, dragging, selecting, or changing a meaningful input.
    - Step, Hint, Auto, Play, Animate, and Solve buttons are allowed only as helpers. They must not be the only interaction.

    Hard requirements:
    1) Return a complete HTML document:
       - Starts with <!DOCTYPE html>
       - Contains <html>, <head>, <body>, and closing </html>

    2) Technology constraints:
       - Vanilla HTML/CSS/JS only (no React, no build tools, no TypeScript).
       - No external scripts/styles/fonts/images/CDNs.
       - No external stylesheet links (<link rel="stylesheet" href="...">) and no CSS @import.
       - No fetch/XMLHttpRequest/WebSocket.
       - No localStorage/sessionStorage/cookies/indexedDB.
       - No window.top/window.parent assumptions.

    3) Teaching-first UI structure:
       - Two-column layout: left = main visualization area (canvas or SVG), right = control panel.
       - Control panel sections:
         a) "Goal" or one short concept explanation line.
         b) "Live Data" section with 2-3 relevant readouts.
         c) "Controls" section with 2-4 visible controls.
         d) "Try this" or "What to notice" prompt.
         e) One status/insight line that changes after learner actions.
       - Keep the layout simple. Fewer controls are better when the primary interaction is clear.
       - Controls must be visible in the initial viewport.

    4) Functional interactivity:
       - Use addEventListener.
       - The primary learner action must update the model state AND redraw the visualization.
       - The learner must be able to make a choice, test a move, or manipulate the concept manually.
       - Provide feedback after actions, especially illegal/wrong moves.
       - If using canvas interactions, attach click/pointer/mouse events to the canvas and use getBoundingClientRect() for coordinates.
       - Use requestAnimationFrame for animation/redrawing when using canvas.
       - The simulation must start with visible non-zero state, not an empty static canvas.
       - Declare all const/let state variables before calling any function that draws, renders, updates, or animates.
       - resizeCanvas()/fit() may size the canvas early only if it does NOT call draw/render/update before state initialization.
       - Avoid temporal-dead-zone bugs such as calling drawPenguin() before const penguin/let penguin exists.

    5) Puzzle/direct-manipulation examples:
       - Towers of Hanoi: learner must click/drag a top disk, then click a target peg; reject illegal moves; count moves; compare to 2^n - 1.
       - Sorting: learner must drag/swap items or step through comparisons, not only watch an animation.
       - Physics/biology systems: learner must change meaningful variables and see cause/effect.
       - Math/concepts: learner must test examples and receive feedback, not just read text.

    6) Styling:
       - Use one <style> block in <head>.
       - Use one <script> block near end of <body>.
       - Make it polished but calm: readable labels, good contrast, clear affordances.
       - Do not place invisible overlays that block pointer events.

    7) Complexity limits:
       - Max 1 canvas.
       - Keep code compact and maintainable.
       - Avoid giant datasets and long hardcoded tables.
       - Prefer one strong interaction over many weak controls.

    Completeness rules:
    - Do not truncate output.
    - Close all tags.
    - Close all functions/objects/arrays/conditionals.
    - End cleanly with </script>, </body>, </html>.
    - If the concept is too complex, deliver a simplified but fully working manipulable version.

    Required HTML skeleton:
    <body>
      <div class="wrapper">
        <div class="viz-col" id="viz-col">
          <canvas id="sim-canvas"></canvas>
        </div>
        <div class="panel-col">
          <h2 class="panel-title">...</h2>
          <p class="concept-line">...</p>
          <div class="section-label">LIVE DATA</div>
          ...
          <div class="section-label">CONTROLS</div>
          ...
          <div class="insight-box" id="insight">...</div>
        </div>
      </div>
      <script>
        window.addEventListener('DOMContentLoaded', () => {
          const vizCol = document.getElementById('viz-col');
          const canvas = document.getElementById('sim-canvas');
          canvas.width = vizCol.clientWidth;
          canvas.height = vizCol.clientHeight;
          canvas.addEventListener('click', (event) => {
            const rect = canvas.getBoundingClientRect();
            // map pointer to concept action; update state; redraw
          });
          // initialize non-zero simulation state
          // start requestAnimationFrame loop here
        });
      </script>
    </body>
""")


def build_widget_user_prompt(topic: str) -> str:
    return dedent(f"""\
        Create an interactive educational widget for: {topic}

        Design target: simple, teacher-ready, hands-on learning widget.
        Audience: middle/high school learners.

        Requirements:
        - Make the topic visible in the title, visual labels, live data, and feedback.
        - Never use generic labels like Primary factor, Secondary factor, Response, Stability, or Concept Lab unless the topic explicitly asks for generic systems.
        - Identify the ONE main thing the learner should understand.
        - Build ONE primary student action that directly manipulates the visual concept.
        - Do not rely only on Auto, Step, Play, Animate, or Solve buttons.
        - Include a short "Try this" task and a "What to notice" explanation.
        - Include live data/readouts that are directly meaningful.
        - Include feedback after learner actions, especially mistakes or illegal moves.
        - Use a left visualization panel and right control panel.
        - Canvas must be sized in DOMContentLoaded and redraw/update after interaction.
        - Declare state first, then call initial draw/render/update. Do not call resizeCanvas() early if it triggers draw before state exists.
        - The result must run on first load in a sandboxed iframe.

        If the topic is Towers of Hanoi:
        - The learner must manually move disks by clicking a source peg/disk and then a target peg.
        - Only top disks may move.
        - Illegal larger-on-smaller moves must be rejected with feedback.
        - Show moves made, optimal minimum moves = 2^n - 1, and selected disk/peg.
        - Hint/Step/Auto Solve may be included, but manual play must be the primary interaction.

        Output ONLY the HTML document.
    """).strip()


WIDGET_EDIT_SYSTEM = dedent("""\
    You revise existing self-contained interactive educational HTML widgets.
    Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

    Core editing rule:
    - Revise the existing widget; do NOT create a different widget from scratch.
    - Preserve the original topic, layout, visual metaphor, control names, live data, CSS style, and JavaScript behavior unless the edit instructions explicitly ask to change them.
    - Make the smallest useful change that satisfies the edit instructions.

    Functional preservation rules:
    - The main student action must still work after editing.
    - If the widget is a puzzle/game/manipulation, preserve or add direct object manipulation with click/pointer/drag events on the canvas/SVG.
    - Do not replace direct interaction with only Auto, Step, Play, Animate, or Solve buttons.
    - Keep feedback after learner actions, including invalid choices.
    - Keep or improve the "Try this" / "What to notice" teaching guidance.

    Hard requirements:
    1) Return a complete HTML document with <!DOCTYPE html>, <html>, <head>, <body>, and closing </html>.
    2) Vanilla HTML/CSS/JS only; no React, no TypeScript, no external scripts/styles/fonts/images/CDNs.
    3) No fetch/XMLHttpRequest/WebSocket and no localStorage/sessionStorage/cookies/indexedDB.
    4) Keep it runnable inside a sandboxed iframe.
    5) Keep the existing interactive controls working. Use addEventListener.
    6) Preserve or improve the existing canvas/SVG visualization. Do not remove the visualization.
    7) Preserve or improve live metrics/readouts. Do not remove them.
    8) Close all tags, functions, objects, arrays, and scripts.
""")


def build_widget_edit_user_prompt(*, original_html: str, edit_instructions: str, original_title: str | None) -> str:
    title = original_title or "Existing widget"
    return dedent(f"""\
        Original widget title: {title}

        Edit instructions:
        {edit_instructions.strip()}

        Revise the existing widget source below.
        Keep the same widget unless the instructions explicitly ask for a different concept.
        Preserve the working interaction model.
        If the widget involves moving, stacking, sorting, choosing, graphing, testing, or solving, the learner must still be able to manipulate the main visual objects manually.

        Original complete widget HTML to revise:
        {original_html}

        Return ONLY the revised complete HTML document.
    """).strip()


WIDGET_REPAIR_SYSTEM = dedent("""\
    You repair an interactive educational widget HTML document.
    Return ONLY fixed complete HTML. No markdown, no backticks, no explanation.
    Preserve the original topic, edited intent, visual metaphor, and behavior.
    Do not replace it with a different widget.
    Ensure the primary learner action is functional, not just an Auto/Step animation.
""")


def build_widget_repair_user_prompt(*, original_title: str | None, edit_instructions: str, prior_html: str, reason: str) -> str:
    return dedent(f"""\
        Widget failed validation: {reason}

        Original title: {original_title or 'Existing widget'}
        Instructions/context: {edit_instructions}

        Fix the HTML so it is complete, self-contained, interactive, and teacher-ready.
        Do not replace it with a different widget.

        Functional requirements:
        - Preserve or add the main manual student interaction.
        - If this is a puzzle/game/direct manipulation widget, learner must click/pointer/drag the visual objects themselves.
        - Step/Hint/Auto buttons are allowed only as helpers.
        - Add clear feedback for illegal or incorrect actions.
        - Include a short Try this / What to notice teaching prompt.
        - Fix JavaScript initialization order: declare all const/let state objects before any initial draw/render/update call.
        - resizeCanvas()/fit() must not trigger draw before state variables exist.

        HTML to repair:
        {prior_html}

        Return ONLY corrected full HTML.
    """).strip()


WIDGET_FALLBACK_SPEC_SYSTEM = dedent("""\
    You create compact JSON specs for a simple topic-specific teaching widget.
    Return ONLY valid JSON. No markdown, no code fences, no comments.

    The backend will render the HTML. Do not write HTML or JavaScript.
    Make the fallback visibly about the requested topic, not a generic concept lab.

    JSON schema:
    {
      "title": "short topic-specific title",
      "concept_line": "one sentence explaining what the learner explores",
      "visual_items": ["3 to 5 short labels for objects shown in the canvas"],
      "controls": [
        {"label": "meaningful variable", "min": 0, "max": 100, "step": 1, "value": 50, "low_label": "low meaning", "high_label": "high meaning"}
      ],
      "metrics": [
        {"label": "topic-specific result", "unit": "short unit or blank"}
      ],
      "try_this": "one concrete student task",
      "notice": "one short what-to-notice explanation",
      "low_insight": "feedback when controls are low",
      "high_insight": "feedback when controls are high"
    }

    Rules:
    - Exactly 3 controls and exactly 3 metrics.
    - Labels must name the topic's real variables or features.
    - Avoid generic labels like Primary factor, Secondary factor, Response, Stability, or Concept Lab.
    - Keep the JSON small: each sentence under 24 words.
""")


def build_widget_fallback_spec_user_prompt(*, topic: str, reason: str | None = None) -> str:
    reason_line = f"Previous custom HTML failed: {reason}\n" if reason else ""
    return dedent(f"""\
        Topic: {topic}
        {reason_line}
        Create the compact JSON widget spec only.
        The fallback should be simpler than a custom widget but still useful for teachers and students.
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
