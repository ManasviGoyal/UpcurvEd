# backend/agent/prompts.py
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
