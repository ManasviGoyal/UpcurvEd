"""Manim code sanitization and preflight utilities.

New model-authored creative scenes use complete Python scripts and pass through
``sanitize_manim_script``. Existing deterministic and legacy code paths may continue using
``sanitize_minimally`` for backward compatibility.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import asdict, dataclass, field
from textwrap import dedent
from typing import Any

RE_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$", re.MULTILINE)
RE_FROM_MANIM_STAR = re.compile(
    r"^\s*from\s+manim\s+import\s+\*\s*(?:#.*)?$",
    re.MULTILINE,
)

VOICEOVER_HEADER = dedent(
    """\
    from manim_voiceover import VoiceoverScene
    from manim_voiceover.services.gtts import GTTSService
    """
)

_CANONICAL_IMPORTS = (
    "from manim import *  # noqa: F403,F405",
    "from manim_voiceover import VoiceoverScene",
    "from manim_voiceover.services.gtts import GTTSService",
)
_NUMPY_IMPORT = "import numpy as np"

_3D_MARKERS = re.compile(
    r"\b(?:"
    r"ThreeDScene|ThreeDAxes|Surface|Polyhedron|Cube|Sphere|Prism|Cone|Cylinder|"
    r"Dot3D|Line3D|Arrow3D|set_camera_orientation|move_camera|"
    r"begin_ambient_camera_rotation|stop_ambient_camera_rotation"
    r")\b"
)

_DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("exec", re.compile(r"\bexec\s*\(")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("compile", re.compile(r"\bcompile\s*\(")),
    ("__import__", re.compile(r"\b__import__\s*\(")),
    ("open", re.compile(r"\bopen\s*\(")),
    ("filesystem", re.compile(r"\b(?:pathlib|shutil)\b|\bos\.")),
    ("subprocess", re.compile(r"\bsubprocess\b")),
    ("network", re.compile(r"\b(?:requests|urllib|httpx|socket|fetch)\b")),
    ("environment", re.compile(r"\b(?:getenv|environ)\b")),
)

_ALLOWED_IMPORT_EXACT = {
    "from manim import *",
    "from manim import *  # noqa: F403,F405",
    "from manim_voiceover import VoiceoverScene",
    "from manim_voiceover.services.gtts import GTTSService",
    "import numpy as np",
}


@dataclass(slots=True)
class SanitizeResult:
    source: str
    changes: list[str] = field(default_factory=list)
    removed_imports: list[str] = field(default_factory=list)
    unresolved_references: list[str] = field(default_factory=list)
    blocked_operations: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    compile_error: str | None = None
    requires_repair: bool = False
    uses_3d: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def strip_code_fences(src: str) -> str:
    if not isinstance(src, str):
        return ""
    return RE_FENCE.sub("", src).replace("\r\n", "\n").replace("\r", "\n").strip()


def patch_unsafe_latex(src: str) -> str:
    replacements = {
        r"\\enclose{longdiv}": r"\\overline",
        r"\\cancel": r"\\times",
    }
    out = src
    for bad, safe in replacements.items():
        out = re.sub(bad, safe, out)
    return out


def _disable_latex_mobjects(src: str) -> str:
    if os.getenv("UPCURVED_DISABLE_LATEX", "0") != "1":
        return src
    out = re.sub(r"\bMathTex\s*\(", "Text(", src)
    out = re.sub(r"(?<!Math)\bTex\s*\(", "Text(", out)
    out = re.sub(r"\.set_color_by_tex_to_color_map\([^)]*\)", "", out)
    out = re.sub(r"\.set_color_by_tex\([^)]*\)", "", out)
    out = re.sub(r"\.get_parts_by_tex\([^)]*\)", "", out)
    out = re.sub(r"\.get_part_by_tex\([^)]*\)", "", out)
    return out


def _guard_negative_waits(src: str) -> str:
    out = re.sub(
        r"self\.wait\(\s*tracker\.duration\s*-\s*([^)]+)\)",
        r"self.wait(max(0.1, tracker.duration - \1))",
        src,
    )
    out = re.sub(
        r"self\.wait\(\s*max\(\s*0(?:\.0)?\s*,\s*([^)]+)\)\s*\)",
        r"self.wait(max(0.1, \1))",
        out,
    )

    def clamp_numeric(match: re.Match[str]) -> str:
        raw = match.group(1)
        try:
            value = float(raw)
        except ValueError:
            return match.group(0)
        if value <= 0:
            return f"self.wait({max(0.1, value):.3f})"
        return match.group(0)

    return re.sub(r"self\.wait\(\s*(-?\d+(?:\.\d+)?)\s*\)", clamp_numeric, out)


def _balanced_call_spans(src: str, call_name: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(call_name)}\s*\(")
    for match in pattern.finditer(src):
        start = match.start()
        index = match.end()
        depth = 1
        quote = ""
        triple = False
        escaped = False
        while index < len(src) and depth > 0:
            char = src[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif triple and src.startswith(quote * 3, index):
                    index += 2
                    quote = ""
                    triple = False
                elif not triple and char == quote:
                    quote = ""
                index += 1
                continue
            if src.startswith("'''", index) or src.startswith('"""', index):
                quote = src[index]
                triple = True
                index += 3
                continue
            if char in {"'", '"'}:
                quote = char
                triple = False
                index += 1
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        if depth == 0:
            spans.append((start, index))
    return spans


def _split_top_level_args(inner: str) -> list[str]:
    args: list[str] = []
    start = 0
    depth = 0
    quote = ""
    triple = False
    escaped = False
    index = 0
    while index < len(inner):
        char = inner[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif triple and inner.startswith(quote * 3, index):
                index += 2
                quote = ""
                triple = False
            elif not triple and char == quote:
                quote = ""
            index += 1
            continue
        if inner.startswith("'''", index) or inner.startswith('"""', index):
            quote = inner[index]
            triple = True
            index += 3
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            args.append(inner[start:index].strip())
            start = index + 1
        index += 1
    tail = inner[start:].strip()
    if tail:
        args.append(tail)
    return args


def _rewrite_call_kwargs(
    src: str,
    call_name: str,
    *,
    allowed: set[str] | None = None,
    rename: dict[str, str] | None = None,
    remove: set[str] | None = None,
) -> tuple[str, list[str]]:
    rename = rename or {}
    remove = remove or set()
    changes: list[str] = []
    spans = _balanced_call_spans(src, call_name)
    if not spans:
        return src, changes
    out = src
    for start, end in reversed(spans):
        call = out[start:end]
        open_index = call.find("(")
        inner = call[open_index + 1 : -1]
        rebuilt: list[str] = []
        for arg in _split_top_level_args(inner):
            match = re.match(r"^([A-Za-z_]\w*)\s*=", arg, flags=re.DOTALL)
            if not match:
                rebuilt.append(arg)
                continue
            key = match.group(1)
            value = arg[match.end() :].strip()
            if key in remove or (allowed is not None and key not in allowed):
                changes.append(f"Removed unsupported {call_name} keyword: {key}")
                continue
            new_key = rename.get(key, key)
            if new_key != key:
                changes.append(f"Renamed {call_name} keyword {key} to {new_key}")
            rebuilt.append(f"{new_key}={value}")
        replacement = f"{call_name}({', '.join(rebuilt)})"
        out = out[:start] + replacement + out[end:]
    return out, changes


def _patch_known_manim_compatibility(src: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    out, code_changes = _rewrite_call_kwargs(
        src,
        "Code",
        allowed={"code_string", "code_file", "language", "add_line_numbers"},
    )
    changes.extend(code_changes)
    out, chart_changes = _rewrite_call_kwargs(
        out,
        "BarChart",
        rename={"width": "bar_width"},
        remove={"max_value"},
    )
    changes.extend(chart_changes)
    guarded = _guard_negative_waits(out)
    if guarded != out:
        changes.append("Clamped potentially non-positive self.wait durations")
    out = guarded
    latex = patch_unsafe_latex(out)
    if latex != out:
        changes.append("Replaced unsupported LaTeX macros")
    out = _disable_latex_mobjects(latex)
    return out, changes


def _imported_names_from_line(line: str) -> tuple[str, list[str]]:
    stripped = line.strip()
    try:
        node = ast.parse(stripped).body[0]
    except Exception:
        return stripped, []
    names: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.append(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name != "*":
                names.append(alias.asname or alias.name)
    return stripped, names


def _normalize_imports(src: str) -> tuple[str, list[str], list[str], list[str]]:
    """Remove model imports and rebuild the exact allowed import header.

    A few unambiguous aliases are normalized locally: ``import manim as mn`` becomes the
    canonical star import with ``mn.`` prefixes removed, and nonstandard NumPy aliases become
    ``np.``. Other libraries are removed and any remaining references are reported.
    """
    kept_lines: list[str] = []
    removed_imports: list[str] = []
    removed_names: list[str] = []
    changes: list[str] = []
    numpy_requested = False
    manim_aliases: list[str] = []
    numpy_aliases: list[str] = []

    for line in src.splitlines():
        stripped = line.strip()
        if not re.match(r"^(?:from\s+\S+\s+import\s+|import\s+)", stripped):
            kept_lines.append(line)
            continue

        normalized = re.sub(r"\s+#.*$", "", stripped).strip()
        if normalized in _ALLOWED_IMPORT_EXACT:
            if normalized.startswith("import numpy"):
                numpy_requested = True
            continue

        manim_alias = re.fullmatch(r"import\s+manim(?:\s+as\s+([A-Za-z_]\w*))?", normalized)
        if manim_alias:
            alias = manim_alias.group(1) or "manim"
            manim_aliases.append(alias)
            changes.append(f"Normalized {normalized} to the canonical Manim star import")
            continue
        if re.fullmatch(r"from\s+manim\s+import\s+.+", normalized):
            changes.append(f"Normalized {normalized} to the canonical Manim star import")
            continue

        numpy_alias = re.fullmatch(r"import\s+numpy(?:\s+as\s+([A-Za-z_]\w*))?", normalized)
        if numpy_alias:
            alias = numpy_alias.group(1) or "numpy"
            numpy_aliases.append(alias)
            numpy_requested = True
            changes.append(f"Normalized {normalized} to import numpy as np")
            continue

        original, names = _imported_names_from_line(stripped)
        removed_imports.append(original)
        removed_names.extend(names)
        changes.append(f"Removed unsupported import: {original}")

    body = "\n".join(kept_lines).strip()
    for alias in sorted(set(manim_aliases), key=len, reverse=True):
        replaced = re.sub(rf"\b{re.escape(alias)}\.", "", body)
        if replaced != body:
            changes.append(f"Removed {alias}. prefixes after normalizing the Manim import")
        body = replaced
    for alias in sorted(set(numpy_aliases), key=len, reverse=True):
        replaced = re.sub(rf"\b{re.escape(alias)}\.", "np.", body)
        if replaced != body:
            changes.append(f"Normalized {alias}. references to np.")
        body = replaced
    if re.search(r"\bnumpy\.", body):
        body = re.sub(r"\bnumpy\.", "np.", body)
        numpy_requested = True
        changes.append("Normalized numpy. references to np.")
    if re.search(r"\bnp\.", body):
        numpy_requested = True

    header = list(_CANONICAL_IMPORTS)
    if numpy_requested:
        header.append(_NUMPY_IMPORT)
    source = "\n".join(header) + "\n\n" + body
    return source.strip() + "\n", changes, removed_imports, removed_names


def _find_unresolved_removed_names(src: str, names: list[str]) -> list[str]:
    unresolved: list[str] = []
    for name in sorted(set(names)):
        if not name or name in {"VoiceoverScene", "GTTSService", "np"}:
            continue
        patterns = (
            rf"\b{re.escape(name)}\s*\.",
            rf"\b{re.escape(name)}\s*\(",
            rf"\b{re.escape(name)}\b",
        )
        if any(re.search(pattern, src) for pattern in patterns):
            unresolved.append(name)
    return unresolved


def _class_header_span(src: str) -> tuple[re.Match[str] | None, list[re.Match[str]]]:
    pattern = re.compile(
        r"^(?P<indent>[ \t]*)class\s+(?P<name>[A-Za-z_]\w*)\s*(?:\((?P<bases>[^)]*)\))?\s*:\s*$",
        flags=re.MULTILINE,
    )
    matches = list(pattern.finditer(src))
    return (matches[0] if matches else None), matches


def _normalize_single_scene_class(src: str, uses_3d: bool) -> tuple[str, list[str], list[str]]:
    changes: list[str] = []
    errors: list[str] = []
    first, matches = _class_header_span(src)
    if not matches:
        errors.append("No scene class was defined. Return exactly one GeneratedScene class.")
        return src, changes, errors
    if len(matches) > 1:
        errors.append("More than one class was defined. Return exactly one GeneratedScene class.")
        return src, changes, errors

    assert first is not None
    desired_bases = "VoiceoverScene, ThreeDScene" if uses_3d else "VoiceoverScene"
    desired = f"{first.group('indent')}class GeneratedScene({desired_bases}):"
    current = first.group(0)
    if current != desired:
        src = src[: first.start()] + desired + src[first.end() :]
        changes.append(
            "Normalized scene class to "
            + ("GeneratedScene(VoiceoverScene, ThreeDScene)" if uses_3d else "GeneratedScene(VoiceoverScene)")
        )
    return src, changes, errors


def _validate_scene_ast(src: str, uses_3d: bool) -> tuple[list[str], str | None]:
    errors: list[str] = []
    try:
        tree = ast.parse(src)
        compile(src, "<generated-manim-scene>", "exec")
    except SyntaxError as exc:
        detail = f"SyntaxError: {exc.msg} at line {exc.lineno}, column {exc.offset}"
        return errors, detail
    except Exception as exc:
        return errors, f"{type(exc).__name__}: {exc}"

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        errors.append("Script must define exactly one class.")
        return errors, None
    scene_class = classes[0]
    if scene_class.name != "GeneratedScene":
        errors.append("Scene class must be named GeneratedScene.")

    base_names: set[str] = set()
    for base in scene_class.bases:
        if isinstance(base, ast.Name):
            base_names.add(base.id)
        elif isinstance(base, ast.Attribute):
            base_names.add(base.attr)
    if "VoiceoverScene" not in base_names:
        errors.append("GeneratedScene must inherit VoiceoverScene.")
    if uses_3d and "ThreeDScene" not in base_names:
        errors.append("3D usage requires GeneratedScene(VoiceoverScene, ThreeDScene).")

    methods = [node for node in scene_class.body if isinstance(node, ast.FunctionDef)]
    constructs = [node for node in methods if node.name == "construct"]
    if len(constructs) != 1:
        errors.append("GeneratedScene must define exactly one construct(self) method.")
    if len(methods) != 1:
        errors.append("GeneratedScene should define only construct(self); nested helpers may be local functions.")

    if "self.set_speech_service" not in src or "GTTSService" not in src:
        errors.append("construct() must configure GTTSService with self.set_speech_service(...).")
    if "self.voiceover" not in src:
        errors.append("Creative scene must include at least one self.voiceover block.")
    if src.count("self.play(") < 2:
        errors.append("Creative scene should contain at least two self.play(...) calls.")
    if re.search(r"\b(?:MathTex|Tex)\s*\(", src):
        errors.append("Tex and MathTex are not allowed; use Text with portable formulas.")
    return errors, None


def sanitize_manim_script(src: str) -> SanitizeResult:
    """Sanitize and statically preflight one model-authored complete Manim script."""
    original = str(src or "")
    changes: list[str] = []
    cleaned = strip_code_fences(original)
    if cleaned != original.strip():
        changes.append("Removed markdown code fences or transport whitespace")

    cleaned, compatibility_changes = _patch_known_manim_compatibility(cleaned)
    changes.extend(compatibility_changes)

    cleaned, import_changes, removed_imports, removed_names = _normalize_imports(cleaned)
    changes.extend(import_changes)

    uses_3d = bool(_3D_MARKERS.search(cleaned))
    cleaned, class_changes, structural_errors = _normalize_single_scene_class(cleaned, uses_3d)
    changes.extend(class_changes)

    unresolved = _find_unresolved_removed_names(cleaned, removed_names)
    blocked = [name for name, pattern in _DANGEROUS_PATTERNS if pattern.search(cleaned)]
    validation_errors, compile_error = _validate_scene_ast(cleaned, uses_3d)
    validation_errors = list(dict.fromkeys(structural_errors + validation_errors))

    if unresolved:
        validation_errors.append(
            "References remain after unsupported imports were removed: " + ", ".join(unresolved)
        )
    if blocked:
        validation_errors.append(
            "Blocked operations remain in the script: " + ", ".join(blocked)
        )

    requires_repair = bool(compile_error or validation_errors or unresolved or blocked)
    return SanitizeResult(
        source=cleaned.strip() + "\n",
        changes=list(dict.fromkeys(changes)),
        removed_imports=list(dict.fromkeys(removed_imports)),
        unresolved_references=unresolved,
        blocked_operations=blocked,
        validation_errors=list(dict.fromkeys(validation_errors)),
        compile_error=compile_error,
        requires_repair=requires_repair,
        uses_3d=uses_3d,
    )


# ---------------------------------------------------------------------------
# Legacy/minimal sanitizer retained for deterministic wrappers and old paths.
# ---------------------------------------------------------------------------


def ensure_voiceover_header(src: str) -> str:
    out = src.replace("from manim_voiceover import VoiceoverScene", "")
    out = out.replace("from manim_voiceover.services.gtts import GTTSService", "")
    return VOICEOVER_HEADER + "\n" + out.lstrip()


def ensure_generated_scene(src: str) -> str:
    first, matches = _class_header_span(src)
    if first is not None:
        uses_3d = bool(_3D_MARKERS.search(src))
        bases = "VoiceoverScene, ThreeDScene" if uses_3d else "VoiceoverScene"
        replacement = f"{first.group('indent')}class GeneratedScene({bases}):"
        return src[: first.start()] + replacement + src[first.end() :]
    return src.rstrip() + "\n\nclass GeneratedScene(VoiceoverScene):\n    def construct(self):\n        pass\n"


def allow_manim_star_import_with_noqa(src: str) -> str:
    if RE_FROM_MANIM_STAR.search(src):
        return RE_FROM_MANIM_STAR.sub("from manim import *  # noqa: F403,F405", src)
    if src.startswith(VOICEOVER_HEADER):
        return (
            VOICEOVER_HEADER
            + "from manim import *  # noqa: F403,F405\n"
            + src[len(VOICEOVER_HEADER) :]
        )
    return "from manim import *  # noqa: F403,F405\n" + src


def _ensure_threed_mixin(src: str) -> str:
    if not _3D_MARKERS.search(src):
        return src
    pattern = re.compile(
        r"^(\s*class\s+GeneratedScene\s*\()\s*VoiceoverScene\s*(\)\s*:\s*)$",
        re.MULTILINE,
    )
    return pattern.sub(r"\1VoiceoverScene, ThreeDScene\2", src)


def sanitize_minimally(src: str) -> str:
    """Backward-compatible non-restrictive sanitizer for trusted wrapper code."""
    out = strip_code_fences(src)
    out = ensure_voiceover_header(out)
    out = ensure_generated_scene(out)
    out = allow_manim_star_import_with_noqa(out)
    out, _changes = _patch_known_manim_compatibility(out)
    out = _ensure_threed_mixin(out)
    return out.strip() + "\n"
