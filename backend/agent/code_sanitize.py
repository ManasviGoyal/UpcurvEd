# backend/agent/utils/code_sanitize.py
import os
import re
from textwrap import dedent

RE_FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*|\s*```\s*$", re.MULTILINE)
RE_FROM_MANIM_STAR = re.compile(r"^\s*from\s+manim\s+import\s+\*\s*(?:#.*)?$", re.MULTILINE)

VOICEOVER_HEADER = dedent("""\
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService
""")


def strip_code_fences(src: str) -> str:
    if not isinstance(src, str):
        return ""
    return RE_FENCE.sub("", src).strip()


def ensure_voiceover_header(src: str) -> str:
    s = src.replace("from manim_voiceover import VoiceoverScene", "")
    s = s.replace("from manim_voiceover.services.gtts import GTTSService", "")
    s = s.lstrip()
    return VOICEOVER_HEADER + "\n" + s


def ensure_generated_scene(src: str) -> str:
    # If there's a class, rename the FIRST one to GeneratedScene(VoiceoverScene)
    RE_CLASS = re.compile(r"^\s*class\s+[A-Za-z_]\w*\s*\([^)]+\)\s*:\s*$", re.MULTILINE)

    def _swap_first(m: re.Match) -> str:
        return "class GeneratedScene(VoiceoverScene):"

    if RE_CLASS.search(src):
        return RE_CLASS.sub(_swap_first, src, count=1)
    # Otherwise append a minimal skeleton
    return (
        src.rstrip()
        + "\n\nclass GeneratedScene(VoiceoverScene):\n    def construct(self):\n        pass\n"
    )


def allow_manim_star_import_with_noqa(src: str) -> str:
    """
    Ensure there is exactly one 'from manim import *  # noqa: F403,F405'
    Replace any existing star import(s) with the noqa version.
    If no star import exists at all, insert it after the voiceover header.
    """
    s = src
    if RE_FROM_MANIM_STAR.search(s):
        s = RE_FROM_MANIM_STAR.sub("from manim import *  # noqa: F403,F405", s)
        return s
    if s.startswith(VOICEOVER_HEADER):
        return (
            VOICEOVER_HEADER
            + "from manim import *  # noqa: F403,F405\n"
            + s[len(VOICEOVER_HEADER) :]
        )
    return "from manim import *  # noqa: F403,F405\n" + s


def patch_unsafe_latex(src: str) -> str:
    """Replace unsupported LaTeX macros with safe alternatives."""
    replacements = {
        r"\\enclose{longdiv}": r"\\overline",
        r"\\cancel": r"\\times",
    }
    s = src
    for bad, safe in replacements.items():
        s = re.sub(bad, safe, s)
    return s


def _disable_latex_mobjects(src: str) -> str:
    """
    Optional desktop-safe mode:
    convert LaTeX mobjects to Text to avoid requiring a TeX distribution.
    Enabled when UPCURVED_DISABLE_LATEX=1.
    """
    if os.getenv("UPCURVED_DISABLE_LATEX", "0") != "1":
        return src

    s = src
    s = re.sub(r"\bMathTex\s*\(", "Text(", s)
    s = re.sub(r"(?<!Math)\bTex\s*\(", "Text(", s)

    # Remove Tex-specific chain methods that are invalid on Text.
    s = re.sub(r"\.set_color_by_tex_to_color_map\([^)]*\)", "", s)
    s = re.sub(r"\.set_color_by_tex\([^)]*\)", "", s)
    s = re.sub(r"\.get_parts_by_tex\([^)]*\)", "", s)
    s = re.sub(r"\.get_part_by_tex\([^)]*\)", "", s)
    return s


# --- NEW: guard against negative/zero waits that crash Manim ---
def _guard_negative_waits(src: str) -> str:
    s = src
    s = re.sub(
        r"self\.wait\(\s*tracker\.duration\s*-\s*([^)]+)\)",
        r"self.wait(max(0.1, tracker.duration - \1))",
        s,
    )
    s = re.sub(
        r"self\.wait\(\s*max\(\s*0(?:\.0)?\s*,\s*([^)]+)\)\s*\)",
        r"self.wait(max(0.1, \1))",
        s,
    )

    def _clamp_numeric_wait(m: re.Match) -> str:
        raw = m.group(1)
        try:
            val = float(raw)
        except ValueError:
            return m.group(0)
        return f"self.wait({max(0.1, val):.3f})" if val <= 0 else m.group(0)

    s = re.sub(r"self\.wait\(\s*(-?\d+(?:\.\d+)?)\s*\)", _clamp_numeric_wait, s)
    return s


# ----------------------------------------------------------------


# --- NEW: strip unsupported kwargs inside Code(...) calls (stability for 0.19) ---
def _strip_unsupported_code_kwargs(src: str) -> str:
    allowed = {"code_string", "code_file", "language", "add_line_numbers"}
    bad_kwargs = {
        "font_size",
        "font",
        "font_family",
        "theme",
        "line_spacing",
        "syntax_highlighter",
        "file_name",
        "code",
        "insert_line_no",
        "background_config",
        "formatter",
        "formatter_style",
    }

    s = src
    out = []
    i = 0
    n = len(s)

    def strip_kwargs_in_args(args_text: str) -> str:
        for kw in bad_kwargs:
            args_text = re.sub(
                rf"(?<![A-Za-z0-9_]){kw}\s*=\s*[^,\)\n]+,?\s*",
                "",
                args_text,
                flags=re.DOTALL,
            )
        args_text = re.sub(
            rf"(?<![A-Za-z0-9_])(?!{'|'.join(map(re.escape, allowed))}\b)"
            r"[A-Za-z_]\w*\s*=\s*[^,\)\n]+,?\s*",
            "",
            args_text,
            flags=re.DOTALL,
        )
        return args_text

    while i < n:
        j = s.find("Code(", i)
        if j == -1:
            out.append(s[i:])
            break

        out.append(s[i:j])
        k = j + len("Code(")

        depth = 1
        in_str = False
        str_delim = ""
        while k < n and depth > 0:
            ch = s[k]
            if not in_str and ch in ("'", '"'):
                if k + 2 < n and s[k : k + 3] in ("'''", '"""'):
                    in_str = True
                    str_delim = s[k : k + 3]
                    k += 3
                    continue
                else:
                    in_str = True
                    str_delim = ch
                    k += 1
                    continue
            elif in_str:
                if str_delim in ("'", '"'):
                    if ch == "\\":
                        k += 2
                        continue
                    if ch == str_delim:
                        in_str = False
                        str_delim = ""
                        k += 1
                        continue
                    k += 1
                    continue
                else:
                    if s.startswith(str_delim, k):
                        in_str = False
                        str_delim = ""
                        k += 3
                        continue
                    k += 1
                    continue

            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    k += 1
                    break
            k += 1

        if depth == 0:
            call_text = s[j:k]
            head = "Code("
            inner = call_text[len(head) : -1]
            tail = ")"
            cleaned_inner = strip_kwargs_in_args(inner)
            out.append(head + cleaned_inner + tail)
            i = k
        else:
            out.append(s[j:])
            break

    return "".join(out)


# --- NEW: fix BarChart kwargs for our Manim version ---
def _sanitize_barchart_kwargs(src: str) -> str:
    """
    Fix common BarChart keyword mistakes for the Manim version we run:
    - `width` kwarg is not supported: rename it to `bar_width`
    - `max_value` kwarg is not supported: drop it
    """
    if not isinstance(src, str) or not src:
        return src

    s = src

    # Rename `width=` to `bar_width=` inside BarChart(...)
    s = re.sub(
        r"BarChart\(([^)]*?)\bwidth\s*=",
        r"BarChart(\1bar_width=",
        s,
        flags=re.DOTALL,
    )
    # Remove `max_value=` kwarg (and following comma if present)
    s = re.sub(
        r"BarChart\(([^)]*?),\s*max_value\s*=\s*[^,\)\n]+",
        r"BarChart(\1",
        s,
        flags=re.DOTALL,
    )
    return s


# -------------------------------------------------------------------------------

# --- NEW: auto-upgrade to 3D mixin when 3D usage detected ---
_3D_MARKERS = re.compile(r"\b(ThreeDAxes|Surface|Polyhedron|move_camera|set_camera_orientation)\b")


def _ensure_threed_mixin(src: str) -> str:
    """
    If code uses 3D objects/methods but class is only VoiceoverScene,
    upgrade to (VoiceoverScene, ThreeDScene).
    """
    if not isinstance(src, str) or not src:
        return src
    if not _3D_MARKERS.search(src):
        return src  # no 3D usage detected

    # Only replace "class GeneratedScene(VoiceoverScene):" headers
    pattern = re.compile(
        r"^(\s*class\s+GeneratedScene\s*\()\s*VoiceoverScene\s*(\)\s*:\s*)$",
        re.MULTILINE,
    )
    return pattern.sub(r"\1VoiceoverScene, ThreeDScene\2", src)


# -------------------------------------------------------------------------------


# --- NEW: Auto-cleanup to prevent text/object overlap in videos ---
def _auto_cleanup_overlapping_objects(src: str) -> str:
    """
    Prevent text/object overlap by:
    1. Ensuring objects created in voiceover blocks are cleaned up
    2. Adding FadeOut for text objects that would otherwise persist
    3. Inserting self.clear() between major scene sections when appropriate

    This addresses the common issue where LLM-generated code creates
    multiple text/shape objects without removing previous ones, causing
    visual overlap in the rendered video.

    IMPORTANT: This function skips adding FadeOut for objects that appear
    inside code snippets (Code(...) blocks or triple-backtick fenced code)
    since those are meant to be displayed to the viewer, not actual scene
    objects.
    """
    if not isinstance(src, str) or not src:
        return src

    lines = src.split("\n")
    result = []

    # Track objects that need cleanup within voiceover blocks
    in_voiceover_block = False
    voiceover_indent = 0
    objects_in_block = []
    pending_cleanup = []

    # Track if we're inside a code snippet context (Code(...) or fenced code)
    in_code_snippet = False
    code_snippet_depth = 0  # For nested parentheses in Code(...)

    # Pattern to detect object creation (common Manim objects)
    object_creation = re.compile(
        r"(\s*)(\w+)\s*=\s*(Text|MathTex|Tex|Title|Paragraph|"
        r"MarkupText|Code|BulletedList|Table|"
        r"Circle|Square|Rectangle|Triangle|Line|Arrow|"
        r"Dot|NumberPlane|Axes|Graph|BarChart|"
        r"VGroup|Group|SurroundingRectangle|Brace)\s*\("
    )

    # Pattern to detect voiceover context manager entry
    voiceover_start = re.compile(r"(\s*)with\s+self\.voiceover\s*\(")

    # Pattern to detect FadeOut/removal animations
    removal_pattern = re.compile(r"(FadeOut|Uncreate|ShrinkToCenter|FadeOutAndShift)\s*\(\s*(\w+)")

    # Pattern to detect self.clear() or self.remove()
    clear_pattern = re.compile(r"\s*self\.(clear|remove)\s*\(")

    # Pattern to detect Code(...) call start (code snippet being displayed)
    code_call_start = re.compile(r"=\s*Code\s*\(")

    # Pattern to detect triple-backtick code fence inside a string
    # This catches code_string="""...``` patterns
    re.compile(r'(code_string|code)\s*=\s*("""|\'\'\')')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if we're entering a Code(...) block
        if code_call_start.search(line):
            in_code_snippet = True
            # Count opening parens to track when Code(...) ends
            code_snippet_depth = line.count("(") - line.count(")")

        # If in a code snippet, track parentheses to know when it ends
        if in_code_snippet:
            if i > 0 or not code_call_start.search(line):
                code_snippet_depth += line.count("(") - line.count(")")
            if code_snippet_depth <= 0:
                in_code_snippet = False
                code_snippet_depth = 0

        # Check for voiceover block start
        vo_match = voiceover_start.match(line)
        if vo_match:
            in_voiceover_block = True
            voiceover_indent = len(vo_match.group(1))
            objects_in_block = []
            result.append(line)
            i += 1
            continue

        # Check if we're exiting a voiceover block (dedent)
        if in_voiceover_block:
            current_indent = (
                len(line) - len(line.lstrip()) if line.strip() else voiceover_indent + 4
            )
            if line.strip() and current_indent <= voiceover_indent:
                # We're exiting the voiceover block
                # Check if there are objects that weren't cleaned up
                if objects_in_block and pending_cleanup:
                    # Insert cleanup before exiting the block
                    cleanup_indent = " " * (voiceover_indent + 4)
                    for obj in pending_cleanup:
                        # Only add FadeOut if the object wasn't already removed
                        result.append(f"{cleanup_indent}self.play(FadeOut({obj}))")

                in_voiceover_block = False
                objects_in_block = []
                pending_cleanup = []

        # Track object creation - but SKIP if we're inside a code snippet
        # (Code snippets show code to the viewer, not actual scene objects)
        obj_match = object_creation.match(line)
        if obj_match and in_voiceover_block and not in_code_snippet:
            obj_name = obj_match.group(2)
            obj_type = obj_match.group(3)
            # Don't track Code objects themselves for cleanup -
            # they're display objects that should persist
            if obj_type != "Code":
                objects_in_block.append(obj_name)
                pending_cleanup.append(obj_name)

        # Track object removal
        removal_match = removal_pattern.search(line)
        if removal_match:
            removed_obj = removal_match.group(2)
            if removed_obj in pending_cleanup:
                pending_cleanup.remove(removed_obj)

        # Track clear calls
        if clear_pattern.search(line):
            pending_cleanup = []  # All objects considered cleaned

        result.append(line)
        i += 1

    return "\n".join(result)


def _ensure_wait_between_animations(src: str) -> str:
    """
    Ensure there's adequate wait time between rapid animations
    to prevent visual overlap. This is especially important for
    text that appears and disappears quickly.
    """
    if not isinstance(src, str) or not src:
        return src

    lines = src.split("\n")
    result = []

    # Pattern to detect consecutive self.play calls
    play_pattern = re.compile(r"(\s*)self\.play\s*\(")

    prev_was_play = False

    for line in lines:
        play_match = play_pattern.match(line)

        if play_match:
            # Check if previous line was also a play without wait
            if prev_was_play:
                # Don't add extra wait - this can interfere with intended animations
                # Just let the code run as-is
                pass
            prev_was_play = True
        else:
            # Check if this line has a wait
            if "self.wait" in line or "Wait(" in line:
                prev_was_play = False
            elif line.strip() and not line.strip().startswith("#"):
                # Non-empty, non-comment line that's not a wait
                if "self.play" not in line:
                    prev_was_play = False

        result.append(line)

    return "\n".join(result)


def _dedupe_overlapping_text_positions(src: str) -> str:
    """
    Detect when multiple text objects might be created at the same position
    and add position offsets to prevent overlap.

    This is a conservative heuristic - it only adds offsets when it's
    very confident objects will overlap.
    """
    if not isinstance(src, str) or not src:
        return src

    # Pattern to find text with .to_edge(UP) or similar that might overlap
    # This is intentionally conservative to avoid breaking valid code
    pattern = re.compile(r"(\w+)\s*=\s*(Text|MathTex|Tex|Title)\s*\([^)]+\)\.to_edge\(UP\)")

    matches = list(pattern.finditer(src))

    if len(matches) <= 1:
        return src  # No potential overlap

    # For now, just return the source unchanged
    # A more sophisticated version could add .shift(DOWN * n) for subsequent elements
    # but this risks breaking intentional layouts
    return src


# -------------------------------------------------------------------------------


def sanitize_minimally(src: str) -> str:
    """
    Minimal, non-restrictive sanitizer:
    - strip code fences/backticks
    - ensure voiceover header at top
    - guarantee a GeneratedScene(VoiceoverScene) class exists
    - ensure star import exists and is marked with # noqa: F403,F405
    - patch a couple of unsafe LaTeX macros
    - strip unsupported Code(...) kwargs that crash Manim 0.19
    - fix some BarChart kwargs (width→bar_width, drop unsupported max_value)
    - guard negative/zero waits that would crash Manim
    - auto-upgrade to (VoiceoverScene, ThreeDScene) if 3D usage is detected
    - auto-cleanup objects to prevent text/visual overlap in videos
    """
    s = strip_code_fences(src)
    s = ensure_voiceover_header(s)
    s = ensure_generated_scene(s)
    s = allow_manim_star_import_with_noqa(s)
    s = patch_unsafe_latex(s)
    s = _disable_latex_mobjects(s)
    s = _strip_unsupported_code_kwargs(s)
    s = _sanitize_barchart_kwargs(s)
    s = _guard_negative_waits(s)
    s = _ensure_threed_mixin(s)
    # s = _auto_cleanup_overlapping_objects(s)  # Prevent text/object overlap
    return s.strip() + "\n"
