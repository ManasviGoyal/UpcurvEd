# backend/agent/prompts.py
import json
from textwrap import dedent

# -------- CODEGEN PROMPTS (Voiceover + Manim) --------
# Visual-first teaching; creative visuals allowed; robust end-of-scene cleanup to avoid overlap.
CODE_SYSTEM = dedent("""\
    You generate COMPLETE, runnable Manim Python for a single class
    that plays all scenes sequentially. You cannot ask the user for clarifications.

    Core intent:
    - The user wants visuals that BEST EXPLAIN their concepts.
      Favor clarity and pedagogy over long narration.
    - Be creative with visuals and pacing. Use layouts, grouping, arrows,
      highlighting, graphs, number planes, etc.
    - Always include at least one visual unless the user says not to.

    Hard rules:
    1) Output must be a valid Python script (no extra commentary or markdown/backticks).
    2) Define exactly one class with construct(self):
        • If you do NOT use any 3D objects/methods → use:
            class GeneratedScene(VoiceoverScene)
        • If you use 3D camera objects (e.g., ThreeDAxes, Surface, Polyhedron)
            OR any 3D camera methods (e.g., set_camera_orientation, move_camera)
            → you MUST use:
            class GeneratedScene(VoiceoverScene, ThreeDScene)
            — not just VoiceoverScene alone.
        • If you only subclass VoiceoverScene, do NOT call 3D methods
            such as set_camera_orientation or move_camera.
    3) Use manim-voiceover with Google TTS (GTTSService).
    4) Structure:
       - Use one or more segments (you decide how many) to build
         understanding step-by-step.
       - In each segment, wrap narration with voiceover(text=...)
         so timing follows narration (tracker.duration).
       - Timing inside voiceover:
         • Do NOT subtract constants from tracker.duration
           (avoid self.wait(tracker.duration - X)).
         • If you compute a remainder, guard it:
             remaining = max(0.1, tracker.duration - estimated_run_time)
             if remaining > 0.1: self.wait(remaining)
         • It's fine to skip remainder waits entirely; rely on the tiny cleanup wait (0.1s).

       - END-OF-SCENE CLEANUP (robust): after each voiceover block,
         snapshot current mobjects and fade them out so the next
         segment starts clean:

             snapshot = list(self.mobjects)
             if snapshot:
                 self.play(*[FadeOut(m) for m in snapshot])
             self.wait(0.1)

    5) Minimum imports:
       from manim import *
       from manim_voiceover import VoiceoverScene
       from manim_voiceover.services.gtts import GTTSService
          - Do NOT import external libraries such as requests, urllib, os, pathlib,
                     httpx, or similar.

    6) Do NOT use MathTex or Tex. Use Text/MarkupText with plain-language
       math formatting instead (for desktop portability without TeX toolchains).

    7) When displaying source code inside the animation:
       - Use the Code mobject with these kwargs ONLY: code_string=<str>,
         optionally: add_line_numbers=<bool>.
       - Do NOT pass other kwargs (e.g., font, font_size, theme,
         file_name, code).
       - Do NOT access internals of Code
         (e.g., code.code, .lines, or submobject indices).
         If you need emphasis, use Indicate(code) or draw a SurroundingRectangle(code).
       - For short snippets, it's fine to use MarkupText with a monospaced span instead.

    8) You MUST NOT use ImageMobject or SVGMobject (no xmlns), it will fail!
        - No external files or network I/O.
    9) Must run under: manim -ql scene.py GeneratedScene
    10) Polyhedron (Manim v0.19.0) is allowed. Use the v0.19.0 signature:
        Polyhedron(vertex_coords, faces_list, faces_config=None, graph_config=None)
        - vertex_coords: list[list[float]] or np.ndarray
        - faces_list: list[list[int]]
        - Optional dicts: faces_config, graph_config
        - Do NOT use keyword names like vertices= or faces= (use positional args as above).
    11) Do NOT invent style kwargs.
        - Do NOT pass kwargs ending in `_style`, such as stroke_style, fill_style,
        background_style, text_style, label_style, axis_style, or grid_style.
        - Use direct Manim kwargs instead:
            color=BLUE
            fill_color=BLUE
            fill_opacity=0.4
            stroke_color=WHITE
            stroke_width=2
            font_size=36
        - If you need styling, create the object first and then call methods like:
            obj.set_color(BLUE)
            obj.set_stroke(WHITE, width=2)
            obj.set_fill(BLUE, opacity=0.4)
    Good practices:
        Avoiding overlapping text and labels:
            - Avoid placing long Text labels too close together, especially in clustered
            layouts such as NumberLine, Axes, charts, or grouped markers.
            - Prefer multi-line labels (using "\\n") when text is long.
            - Stagger labels vertically (different multiples of UP or DOWN).
            - Use a non-zero buff in next_to(..., UP, buff=<value>) to keep
                labels visually separated from each other and from the axis.

        Bad example (labels crowded and may overlap):
            timeline = NumberLine(x_range=[-5, 5, 1], length=10, include_numbers=True)
            migration_epochs = VGroup(
                Text("Ancient Migrations", color=RED).scale(0.5).next_to(timeline.n2p(-3), UP),
                Text("Colonial Expansion", color=GREEN).scale(0.5).next_to(timeline.n2p(0), UP),
                Text("Modern Globalization", color=BLUE).scale(0.5).next_to(timeline.n2p(3), UP),
            )

        Good example (use multi-line labels, vertical staggering, and buff):
            timeline = NumberLine(x_range=[-5, 5, 1], length=10, include_numbers=True)
            migration_epochs = VGroup(
                Text("Ancient Migrations", color=RED)
                    .scale(0.5)
                    .next_to(timeline.n2p(-3), UP, buff=0.6),
                Text("Colonial\\nExpansion", color=GREEN)
                    .scale(0.5)
                    .next_to(timeline.n2p(0), UP * 1.8, buff=0.6),
                Text("Modern\\nGlobalization", color=BLUE)
                    .scale(0.5)
                    .next_to(timeline.n2p(3), UP, buff=0.6),
            )

""")


def build_code_user_prompt(
    goal: str,
    retrieved_docs: str | None = None,
    *,
    # --- Repair-mode extras (optional) ---
    previous_code: str | None = None,
    error_context: str | None = None,
) -> str:
    """
    Unified prompt builder.
    - Fresh draft: pass only `goal`.
    - Repair draft: ALSO pass `previous_code` and `error_context` (single block string).

    The template *always* returns a single user message payload for the LLM.
    """

    docs_block = ""
    if retrieved_docs:
        docs_block = dedent(f"""
            Retrieved Manim Documentation:
            The following documentation snippets were retrieved based on the error/context.
            You can determine whether it is relevant to your code.

            {retrieved_docs}

            End of Documentation
        """).strip()

    repair_blocks = ""
    if previous_code or error_context:
        prev = previous_code or ""
        err = error_context or ""
        repair_blocks = dedent(f"""
            LAST ATTEMPT CODE:
            {prev}

            ERROR CONTEXT:
            {err}
        """).strip()

    return dedent(f"""\
        Teaching goal (convey with strong visuals):
        {goal}
        {repair_blocks}
        Return ONLY the Python source that realizes your segments in order.

        Voiceover + Visual structure:
        - self.set_speech_service(GTTSService(lang=LANG)) where LANG is
          per-segment language if provided; else "en".
        - Use one or more segments to build understanding visually.
        - In each segment:
            with self.voiceover(text="<clear narration>") as tracker:
                # Create visuals and animations of your choice (creative but clear).
                # Example:
                #   title = Text("Core Idea").scale(0.9)
                #   self.play(Write(title), run_time=1.2)
        - Robust end-of-scene cleanup (no overlap):
            snapshot = list(self.mobjects)
            if snapshot:
                self.play(*[FadeOut(m) for m in snapshot])
            self.wait(0.1)
        {docs_block}
    """).strip()



# -------- STRUCTURED VIDEO PROMPTS (Plan-only, backend-rendered templates) --------

STRUCTURED_VIDEO_SYSTEM = dedent("""\
    You create a compact scene plan for a short educational Manim video.

    Return ONLY valid JSON. No markdown. No Python code. No explanations.

    Required JSON shape:
    {
      "title": "short lesson title",
      "audience": "general",
      "scenes": [
        {
          "id": 1,
          "kind": "title",
          "heading": "short heading",
          "narration": "one clear sentence",
          "bullets": ["short phrase", "short phrase"],
          "duration_sec": 6
        },
        {
          "id": 2,
          "kind": "key_points",
          "heading": "short heading",
          "narration": "one clear sentence",
          "bullets": ["short phrase", "short phrase", "short phrase"],
          "duration_sec": 8
        },
        {
          "id": 3,
          "kind": "diagram",
          "heading": "short heading",
          "narration": "one clear sentence",
          "bullets": ["short phrase", "short phrase", "short phrase"],
          "visual_goal": "describe the process or relationship as simple shapes, arrows, labels, or a timeline",
          "duration_sec": 9
        },
        {
          "id": 4,
          "kind": "creative",
          "heading": "short heading",
          "narration": "one clear sentence",
          "bullets": ["short phrase", "short phrase", "short phrase"],
          "visual_goal": "describe a memorable visual metaphor using simple drawable objects",
          "duration_sec": 9
        },
        {
          "id": 5,
          "kind": "recap",
          "heading": "short heading",
          "narration": "one clear sentence",
          "bullets": ["short phrase", "short phrase", "short phrase"],
          "duration_sec": 7
        }
      ]
    }

    Rules:
    - Exactly 5 scenes.
    - Use this scene order: title, key_points, diagram, creative, recap.
    - Do NOT write Manim code. The backend will render templates from your plan.
    - Keep the plan compact.
    - Narration: one sentence per scene, max 22 words.
    - Heading: max 8 words.
    - Bullets: 2 to 4 bullets per scene, max 7 words each.
    - visual_goal: max 25 words, concrete and drawable.
    - Make the lesson specific, factual, and educational, not generic or motivational.
    - Include concrete mechanisms, causes/effects, vocabulary, or examples appropriate to the topic.
    - For science, health, biology, history, or technical topics, use precise facts and explain how/why.
    - Avoid generic filler such as "helps you grow", "is important", or "makes life better" unless paired with a concrete mechanism.
    - Avoid quotes inside strings unless necessary.
""")


def build_structured_video_user_prompt(goal: str) -> str:
    return dedent(f"""\
        Teaching goal:
        {goal}

        Return only the compact JSON scene plan.
        Do not include Python code.
        Make it specific, factual, and educational. Avoid generic filler.
    """).strip()


STRUCTURED_VIDEO_EDIT_SYSTEM = dedent("""\
    You edit a compact JSON scene plan for a short educational Manim video.

    Return ONLY valid JSON. No markdown. No Python code. No explanations.

    Required behavior:
    - Keep exactly 5 scenes.
    - Keep the same scene order: title, key_points, diagram, creative, recap.
    - Apply the user's edit request to the most relevant scene or scenes.
    - If the user asks to remove a scene or topic, do NOT reduce the number of scenes.
      Replace that scene with a better on-topic educational scene instead.
    - Preserve useful unchanged scenes when possible.
    - Make the lesson specific, factual, and educational, not generic or motivational.
    - Include concrete mechanisms, causes/effects, vocabulary, or examples appropriate to the topic.
    - Avoid generic filler such as "helps you grow", "is important", or "makes life better" unless paired with a concrete mechanism.

    Output shape:
    {
      "title": "short lesson title",
      "audience": "general",
      "scenes": [
        {
          "id": 1,
          "kind": "title",
          "heading": "short heading",
          "narration": "one clear sentence",
          "bullets": ["short phrase", "short phrase"],
          "duration_sec": 6
        }
      ]
    }

    Rules:
    - Exactly 5 scenes.
    - Narration: one sentence per scene, max 24 words.
    - Heading: max 8 words.
    - Bullets: 2 to 4 bullets per scene, max 7 words each.
    - visual_goal for diagram/creative scenes: max 25 words, concrete and drawable.
""")


def build_structured_video_edit_user_prompt(original_plan: dict, edit_instructions: str) -> str:
    return dedent(f"""\
        Original compact scene plan JSON:
        {__import__('json').dumps(original_plan, ensure_ascii=True, indent=2)}

        User edit request:
        {edit_instructions}

        Return the complete edited compact JSON scene plan only.
        Keep exactly 5 scenes. Do not include Python code.
    """).strip()


# -------- EDIT (diff-based) PROMPTS --------

EDIT_SYSTEM = dedent("""\
    You are a precise Manim code editor.
    You will receive Python code and edit instructions.

    IMPORTANT: Return ONLY a unified diff showing your changes.
    Use this exact format:

    ```diff
    @@ -START_LINE,COUNT +START_LINE,COUNT @@
     context line (unchanged)
    -removed line
    +added line
     context line (unchanged)
    ```

    Rules:
    1) Return ONLY the diff block - no explanations before or after.
    2) Include 2-3 lines of context around each change.
    3) Make targeted changes based on the user's instructions.
    4) If the user says "all", "every", "throughout", or "entire" -
       include a SEPARATE @@ hunk for EVERY matching element in the code.
    5) Preserve all imports, class names, and structure.
    6) Line numbers should be approximate (the caller will fuzzy match).
""")


def build_edit_user_prompt(
    original_code: str,
    edit_instructions: str,
    wants_all: bool,
    wants_overlap_fix: bool,
) -> str:
    """
    Build the user message for diff-based Manim edits.
    Adds 'ALL occurrences' emphasis and overlap-fix guidance
    only when requested.
    """
    all_instruction = ""
    if wants_all:
        all_instruction = (
            "\n\nCRITICAL: The user wants this change applied to ALL/EVERY "
            "matching occurrence throughout the ENTIRE code.\n"
            "- Scan the ENTIRE code from top to bottom.\n"
            "- Include a SEPARATE @@ hunk for EACH place that matches.\n"
            "- Do NOT miss any occurrence."
        )

    overlap_instruction = ""
    if wants_overlap_fix:
        overlap_instruction = (
            "\n\n"
            + dedent(
                """
                OVERLAP FIX REQUIRED: The user is experiencing visual overlap issues.
                Common fixes to apply:
                1. Add `self.play(FadeOut(object))` BEFORE creating new objects in the same area.
                2. Add cleanup after each voiceover block, for example:
                snapshot = list(self.mobjects)
                if snapshot:
                    self.play(*[FadeOut(m) for m in snapshot])
                3. For text or labels that risk overlapping (e.g., along a NumberLine, Axes,
                or any clustered layout), stagger them vertically (different multiples of UP/DOWN),
                use multi-line labels when helpful, and use a non-zero buff in next_to(...).
                4. Use `.shift(DOWN * 1)` or `.next_to(prev_obj, DOWN)` to reposition
                    elements into separate rows when needed.
                5. Use `self.clear()` between major sections when appropriate.
                6. Always ensure old objects are removed or faded out before new ones occupy
                the same space.
                """
            ).strip()
        )

    return (
        "Original Manim code:\n"
        "```python\n"
        f"{original_code}\n"
        "```\n\n"
        f"Edit instructions: {edit_instructions}{all_instruction}{overlap_instruction}\n\n"
        "Return ONLY a unified diff showing the changes needed."
    )


# -------- WIDGET PROMPTS --------

WIDGET_SYSTEM = dedent("""\
    You generate self-contained interactive educational HTML simulations.
    Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

    This widget runs in a sandboxed iframe inside a desktop app. It must be robust.

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

    3) Simulation-first UI structure:
       - Two-column layout: left = main visualization area (canvas or SVG), right = control panel.
       - Control panel sections:
         a) "Live Data" section with at least 3 numeric readouts with units.
         b) "Controls" section with at least 3 interactive controls.
       - Controls must be visible in initial viewport.
       - Include one short concept explanation line.
       - Include one status/insight line that changes as controls change.

    4) Interactivity:
       - Use addEventListener.
       - Use requestAnimationFrame for animated simulations.
       - The simulation must start with visible non-zero state, not an empty static canvas.
       - Keep simulation deterministic and smooth on modest hardware.
       - If using canvas interactions, use getBoundingClientRect() for coordinates.

    5) Styling:
       - Use one <style> block in <head>.
       - Use one <script> block near end of <body>.
       - Make it visually polished and educational, not plain boilerplate.
       - Ensure good contrast and readable labels.
       - Do not place invisible overlays that block pointer events.

    6) Complexity limits:
       - Max 1 canvas.
       - Keep code compact and maintainable.
       - Avoid giant datasets and long hardcoded tables.

    Completeness rules:
    - Do not truncate output.
    - Close all tags.
    - Close all functions/objects/arrays/conditionals.
    - End cleanly with </script>, </body>, </html>.
    - If the concept is too complex, deliver a simplified but fully working simulation.

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
          // initialize non-zero simulation state
          // start requestAnimationFrame loop here
        });
      </script>
    </body>
""")


def build_widget_user_prompt(topic: str) -> str:
    return dedent(f"""\
        Create an interactive educational simulation for: {topic}

        Design target: app-like simulation quality, similar to science learning tools.
        Use a left visualization panel and right control panel.
        Include meaningful live metrics and controls that clearly change system behavior.
        Controls must always be visible, not hidden/collapsed.
        Canvas must be sized in DOMContentLoaded and animation must start there.
        Audience: middle/high school learners.
        The result must run on first load in a sandboxed iframe.

        Output ONLY the HTML document.
    """).strip()


WIDGET_EDIT_SYSTEM = dedent("""\
    You revise existing self-contained interactive educational HTML widgets.
    Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

    Core editing rule:
    - Revise the existing widget; do NOT create a different widget from scratch.
    - Preserve the original topic, layout, visual metaphor, control names, live data, CSS style, and JavaScript behavior unless the edit instructions explicitly ask to change them.
    - Make the smallest useful change that satisfies the edit instructions.

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

        Original complete widget HTML to revise:
        {original_html}

        Return ONLY the revised complete HTML document.
    """).strip()


WIDGET_REPAIR_SYSTEM = dedent("""\
    You repair an edited interactive widget HTML document.
    Return ONLY fixed complete HTML. No markdown, no backticks, no explanation.
    Preserve the edited intent and original widget behavior.
""")


def build_widget_repair_user_prompt(*, original_title: str | None, edit_instructions: str, prior_html: str, reason: str) -> str:
    return dedent(f"""\
        Edited widget failed validation: {reason}

        Original title: {original_title or 'Existing widget'}
        Edit instructions: {edit_instructions}

        Fix the edited HTML so it is complete, self-contained, interactive, and still reflects the requested edit.
        Do not replace it with a different widget.

        Edited HTML to repair:
        {prior_html}

        Return ONLY corrected full HTML.
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
