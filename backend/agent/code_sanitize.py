"""Manim code sanitization and preflight utilities.

New model-authored creative scenes use complete Python scripts and pass through
``sanitize_manim_script``. Existing deterministic and legacy code paths may continue using
``sanitize_minimally`` for backward compatibility.
"""

from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from dataclasses import asdict, dataclass, field
from textwrap import dedent
from typing import Any

RE_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$", re.MULTILINE)
RE_FROM_MANIM_STAR = re.compile(
    r"^\s*from\s+manim\s+import\s+\*\s*(?:#.*)?$",
    re.MULTILINE,
)

# Scenes are authored against manim-voiceover's GTTSService because that is the
# idiom the model reliably produces, but they render with edge-tts neural voices.
# Rewriting the import here (rather than in the prompt) keeps the generated code,
# its AST validation, and the scene body identical while swapping the engine.
_LEGACY_SERVICE_IMPORT = "from manim_voiceover.services.gtts import GTTSService"
VOICEOVER_SERVICE_IMPORT = "from backend.tts.manim_service import EdgeTTSService as GTTSService"
_SERVICE_IMPORT_MODULE = "backend.tts.manim_service"

VOICEOVER_HEADER = dedent(
    f"""\
    from manim_voiceover import VoiceoverScene
    {VOICEOVER_SERVICE_IMPORT}
    """
)

_CANONICAL_IMPORTS = (
    "from manim import *  # noqa: F403,F405",
    "from manim_voiceover import VoiceoverScene",
    VOICEOVER_SERVICE_IMPORT,
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
    _LEGACY_SERVICE_IMPORT,
    VOICEOVER_SERVICE_IMPORT,
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
    out = _sub_outside_literals(src, r"\bMathTex\s*\(", "Text(")
    out = _sub_outside_literals(out, r"(?<!Math)\bTex\s*\(", "Text(")
    out = _sub_outside_literals(out, r"\.set_color_by_tex_to_color_map\([^)]*\)", "")
    out = _sub_outside_literals(out, r"\.set_color_by_tex\([^)]*\)", "")
    out = _sub_outside_literals(out, r"\.get_parts_by_tex\([^)]*\)", "")
    out = _sub_outside_literals(out, r"\.get_part_by_tex\([^)]*\)", "")
    return out


def _guard_negative_waits(src: str) -> str:
    out = _sub_outside_literals(
        src,
        r"self\.wait\(\s*tracker\.duration\s*-\s*([^)]+)\)",
        r"self.wait(max(0.1, tracker.duration - \1))",
    )
    out = _sub_outside_literals(
        out,
        r"self\.wait\(\s*max\(\s*0(?:\.0)?\s*,\s*([^)]+)\)\s*\)",
        r"self.wait(max(0.1, \1))",
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

    return _sub_outside_literals(
        out,
        r"self\.wait\(\s*(-?\d+(?:\.\d+)?)\s*\)",
        clamp_numeric,
    )


def _string_and_comment_spans(src: str) -> list[tuple[int, int]]:
    """Return absolute source spans occupied by Python strings or comments."""
    line_offsets = [0]
    for line in src.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))

    spans: list[tuple[int, int]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for token in tokens:
            if token.type not in {tokenize.STRING, tokenize.COMMENT}:
                continue
            start_line, start_col = token.start
            end_line, end_col = token.end
            start = line_offsets[max(0, start_line - 1)] + start_col
            end = line_offsets[max(0, end_line - 1)] + end_col
            spans.append((start, end))
    except (tokenize.TokenError, IndentationError):
        pass
    return spans


def _sub_outside_literals(
    src: str,
    pattern: str | re.Pattern[str],
    replacement: str | Any,
    *,
    flags: int = 0,
) -> str:
    """Apply a regex replacement only to executable source, never strings/comments."""
    compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
    spans = _string_and_comment_spans(src)
    matches = [
        match
        for match in compiled.finditer(src)
        if not any(start <= match.start() < end for start, end in spans)
    ]
    out = src
    for match in reversed(matches):
        value = replacement(match) if callable(replacement) else match.expand(replacement)
        out = out[: match.start()] + value + out[match.end() :]
    return out


def _uses_3d_ast(src: str) -> bool:
    """Detect actual executable 3D API usage while ignoring displayed code strings."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    markers = {
        "ThreeDScene", "ThreeDAxes", "Surface", "Polyhedron", "Cube", "Sphere",
        "Prism", "Cone", "Cylinder", "Dot3D", "Line3D", "Arrow3D",
        "set_camera_orientation", "move_camera", "begin_ambient_camera_rotation",
        "stop_ambient_camera_rotation",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in markers:
            return True
        if isinstance(node, ast.Attribute) and node.attr in markers:
            return True
    return False


def _balanced_call_spans(src: str, call_name: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    ignored = _string_and_comment_spans(src)
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(call_name)}\s*\(")
    for match in pattern.finditer(src):
        start = match.start()
        if any(span_start <= start < span_end for span_start, span_end in ignored):
            continue
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



def _sanitize_code_calls(src: str) -> tuple[str, list[str]]:
    """Normalize Code(...) calls without discarding the learner-facing source.

    Model outputs commonly use ``code=`` or a first positional argument. Both are converted
    to ``code_string=``. File-backed and styling kwargs are removed because generated scenes
    must be self-contained and the supported Manim surface varies across installations.
    """
    changes: list[str] = []
    spans = _balanced_call_spans(src, "Code")
    if not spans:
        return src, changes

    out = src
    allowed = {"code_string", "language", "add_line_numbers"}
    rename = {"code": "code_string"}
    for start, end in reversed(spans):
        call = out[start:end]
        open_index = call.find("(")
        args = _split_top_level_args(call[open_index + 1 : -1])
        rebuilt: list[str] = []
        positional: list[str] = []
        seen: set[str] = set()

        for arg in args:
            match = re.match(r"^([A-Za-z_]\w*)\s*=", arg, flags=re.DOTALL)
            if not match:
                if arg:
                    positional.append(arg)
                continue
            key = match.group(1)
            value = arg[match.end() :].strip()
            new_key = rename.get(key, key)
            if new_key != key:
                changes.append("Renamed Code keyword code to code_string")
            if new_key == "code_file":
                changes.append("Removed file-backed Code keyword: code_file")
                continue
            if new_key not in allowed:
                changes.append(f"Removed unsupported Code keyword: {key}")
                continue
            if new_key in seen:
                changes.append(f"Removed duplicate Code keyword: {new_key}")
                continue
            seen.add(new_key)
            rebuilt.append(f"{new_key}={value}")

        if positional:
            if "code_string" not in seen:
                rebuilt.insert(0, f"code_string={positional[0]}")
                seen.add("code_string")
                changes.append("Converted the first positional Code argument to code_string")
                positional = positional[1:]
            if positional:
                changes.append(
                    f"Removed {len(positional)} unsupported extra positional Code argument"
                    + ("s" if len(positional) != 1 else "")
                )

        replacement = f"Code({', '.join(rebuilt)})"
        out = out[:start] + replacement + out[end:]
    return out, changes


def _code_usage_errors(tree: ast.AST) -> list[str]:
    """Return only deterministic errors for incomplete ``Code(...)`` calls.

    Display and animation choices around a Code mobject are intentionally not validated here.
    Those choices are best tested by the real Manim render, not guessed statically.
    """
    errors: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "Code":
            continue
        code_kw = next((kw for kw in node.keywords if kw.arg == "code_string"), None)
        if code_kw is None:
            errors.append(
                "Every Code(...) call must provide learner-facing source with code_string=."
            )
        elif isinstance(code_kw.value, ast.Constant) and (
            not isinstance(code_kw.value.value, str) or not code_kw.value.value.strip()
        ):
            errors.append("Code(..., code_string=...) cannot be empty.")
        if node.args:
            errors.append("Code(...) must not retain positional arguments after sanitization.")
        unsupported = [
            kw.arg
            for kw in node.keywords
            if kw.arg not in {"code_string", "language", "add_line_numbers"}
        ]
        if unsupported:
            errors.append(
                "Unsupported Code keyword(s) remain: "
                + ", ".join(sorted(set(str(x) for x in unsupported if x)))
            )
    return list(dict.fromkeys(errors))

def _patch_known_manim_compatibility(src: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    out, code_changes = _sanitize_code_calls(src)
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
    out = _disable_latex_mobjects(guarded)
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



def _replace_prefix_outside_literals(src: str, alias: str, replacement: str) -> tuple[str, bool]:
    """Replace ``alias.`` without touching displayed source inside strings/comments."""
    spans = _string_and_comment_spans(src)
    pattern = re.compile(rf"\b{re.escape(alias)}\.")
    matches = [
        match
        for match in pattern.finditer(src)
        if not any(start <= match.start() < end for start, end in spans)
    ]
    if not matches:
        return src, False
    out = src
    value = f"{replacement}." if replacement else ""
    for match in reversed(matches):
        out = out[: match.start()] + value + out[match.end() :]
    return out, True


def _source_offsets(src: str) -> list[int]:
    offsets = [0]
    for line in src.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _node_span(src: str, node: ast.AST) -> tuple[int, int] | None:
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    col = getattr(node, "col_offset", None)
    end_col = getattr(node, "end_col_offset", None)
    if None in {lineno, end_lineno, col, end_col}:
        return None
    offsets = _source_offsets(src)
    try:
        return offsets[int(lineno) - 1] + int(col), offsets[int(end_lineno) - 1] + int(end_col)
    except Exception:
        return None


def _root_name(node: ast.AST) -> str:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def _find_blocked_operations_ast(src: str) -> list[str]:
    """Inspect executable AST nodes while ignoring code shown inside string literals."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    blocked: list[str] = []
    dangerous_calls = {"exec", "eval", "compile", "__import__", "open"}
    module_categories = {
        "os": "filesystem/environment",
        "pathlib": "filesystem",
        "shutil": "filesystem",
        "subprocess": "subprocess",
        "requests": "network",
        "urllib": "network",
        "httpx": "network",
        "socket": "network",
    }
    file_method_names = {"read_text", "write_text", "read_bytes", "write_bytes", "unlink", "rmdir"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in dangerous_calls:
                blocked.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                root = _root_name(node.func)
                if root in module_categories:
                    blocked.append(module_categories[root])
                if node.func.attr in file_method_names:
                    blocked.append("filesystem")
        elif isinstance(node, ast.Attribute):
            root = _root_name(node)
            if root in module_categories:
                blocked.append(module_categories[root])
    return list(dict.fromkeys(blocked))



def _normalize_imports(src: str) -> tuple[str, list[str], list[str], list[str]]:
    """Rebuild the small allowed import header without inspecting displayed code strings.

    Earlier line-based normalization could mistake ``import`` statements inside a learner-facing
    triple-quoted code snippet for executable imports. This implementation uses the Python AST,
    so educational source code remains byte-for-byte intact.
    """
    changes: list[str] = []
    removed_imports: list[str] = []
    removed_names: list[str] = []
    numpy_requested = False
    manim_aliases: list[str] = []
    numpy_aliases: list[str] = []

    try:
        tree = ast.parse(src)
    except SyntaxError:
        # Do not perform speculative line surgery on malformed code. Compilation will trigger
        # one evidence-based repair call with the original source preserved.
        header = "\n".join(_CANONICAL_IMPORTS)
        return header + "\n\n" + src.strip() + "\n", changes, removed_imports, removed_names

    import_nodes = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    spans: list[tuple[int, int]] = []
    for node in import_nodes:
        segment = ast.get_source_segment(src, node) or ""
        normalized = re.sub(r"\s+#.*$", "", segment.strip()).strip()
        span = _node_span(src, node)
        if span is not None:
            spans.append(span)

        if isinstance(node, ast.ImportFrom) and node.module == "manim":
            if any(alias.name == "*" for alias in node.names):
                continue
            for alias in node.names:
                if alias.asname and alias.asname != alias.name:
                    removed_names.append(alias.asname)
            changes.append(f"Normalized {normalized} to the canonical Manim star import")
            continue

        if isinstance(node, ast.ImportFrom) and node.module == "manim_voiceover":
            continue
        if isinstance(node, ast.ImportFrom) and node.module in {
            "manim_voiceover.services.gtts",
            _SERVICE_IMPORT_MODULE,
        }:
            # Either spelling is dropped here and replaced by _CANONICAL_IMPORTS.
            continue

        if isinstance(node, ast.Import):
            handled = True
            for alias in node.names:
                if alias.name == "manim":
                    manim_aliases.append(alias.asname or "manim")
                    changes.append(f"Normalized {normalized} to the canonical Manim star import")
                elif alias.name == "numpy":
                    numpy_aliases.append(alias.asname or "numpy")
                    numpy_requested = True
                    changes.append(f"Normalized {normalized} to import numpy as np")
                else:
                    handled = False
            if handled:
                continue

        original, names = _imported_names_from_line(segment)
        removed_imports.append(original or normalized)
        removed_names.extend(names)
        changes.append(f"Removed unsupported import: {original or normalized}")

    body = src
    for start, end in sorted(spans, reverse=True):
        body = body[:start] + body[end:]

    for alias in sorted(set(manim_aliases), key=len, reverse=True):
        body, changed = _replace_prefix_outside_literals(body, alias, "")
        if changed:
            changes.append(f"Removed {alias}. prefixes after normalizing the Manim import")
    for alias in sorted(set(numpy_aliases), key=len, reverse=True):
        body, changed = _replace_prefix_outside_literals(body, alias, "np")
        if changed and alias != "np":
            changes.append(f"Normalized {alias}. references to np.")
    body, changed = _replace_prefix_outside_literals(body, "numpy", "np")
    if changed:
        numpy_requested = True
        changes.append("Normalized numpy. references to np.")

    # Determine executable np usage from the parsed body, not from snippet strings.
    try:
        body_tree = ast.parse(body)
        if any(isinstance(node, ast.Name) and node.id == "np" for node in ast.walk(body_tree)):
            numpy_requested = True
    except SyntaxError:
        pass

    header = list(_CANONICAL_IMPORTS)
    if numpy_requested:
        header.append(_NUMPY_IMPORT)
    source = "\n".join(header) + "\n\n" + body.strip()
    return source.strip() + "\n", list(dict.fromkeys(changes)), list(dict.fromkeys(removed_imports)), list(dict.fromkeys(removed_names))

def _find_unresolved_removed_names(src: str, names: list[str]) -> list[str]:
    """Find executable references to removed imports, ignoring string literal contents."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return sorted(
        name
        for name in set(names)
        if name and name not in {"VoiceoverScene", "GTTSService", "np"} and name in used
    )

def _class_header_span(src: str) -> tuple[re.Match[str] | None, list[re.Match[str]]]:
    pattern = re.compile(
        r"^(?P<indent>[ \t]*)class\s+(?P<name>[A-Za-z_]\w*)\s*(?:\((?P<bases>[^)]*)\))?\s*:\s*$",
        flags=re.MULTILINE,
    )
    matches = list(pattern.finditer(src))
    return (matches[0] if matches else None), matches


def _normalize_single_scene_class(src: str, uses_3d: bool) -> tuple[str, list[str], list[str]]:
    """Normalize the actual scene class while allowing harmless helper classes."""
    changes: list[str] = []
    errors: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src, changes, errors

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    generated = [node for node in classes if node.name == "GeneratedScene"]
    candidate: ast.ClassDef | None = generated[0] if generated else None
    if candidate is None:
        scene_like: list[ast.ClassDef] = []
        for node in classes:
            base_names = {
                base.id if isinstance(base, ast.Name) else base.attr
                for base in node.bases
                if isinstance(base, (ast.Name, ast.Attribute))
            }
            if base_names & {"VoiceoverScene", "ThreeDScene", "Scene"}:
                scene_like.append(node)
        if len(scene_like) == 1:
            candidate = scene_like[0]
        elif len(classes) == 1:
            candidate = classes[0]

    if candidate is None:
        errors.append("No renderable scene class was found. Define GeneratedScene.")
        return src, changes, errors

    lines = src.splitlines(keepends=True)
    line_index = int(candidate.lineno) - 1
    if line_index < 0 or line_index >= len(lines):
        errors.append("Could not locate the GeneratedScene class header.")
        return src, changes, errors
    original_line = lines[line_index]
    if not re.match(r"^\s*class\s+[A-Za-z_]\w*\s*(?:\([^\n]*\))?\s*:\s*(?:#.*)?$", original_line.rstrip("\n")):
        errors.append("GeneratedScene must use a single-line class header.")
        return src, changes, errors

    indent = re.match(r"^\s*", original_line).group(0)
    bases = "VoiceoverScene, ThreeDScene" if uses_3d else "VoiceoverScene"
    ending = "\n" if original_line.endswith("\n") else ""
    desired = f"{indent}class GeneratedScene({bases}):{ending}"
    if original_line != desired:
        lines[line_index] = desired
        changes.append(
            "Normalized the renderable scene class to "
            + ("GeneratedScene(VoiceoverScene, ThreeDScene)" if uses_3d else "GeneratedScene(VoiceoverScene)")
        )
    return "".join(lines), changes, errors

def _validate_scene_ast(src: str, uses_3d: bool) -> tuple[list[str], str | None]:
    """Validate only conditions known to prevent a safe, voiced scene from running."""
    errors: list[str] = []
    try:
        tree = ast.parse(src)
        compile(src, "<generated-manim-scene>", "exec")
    except SyntaxError as exc:
        detail = f"SyntaxError: {exc.msg} at line {exc.lineno}, column {exc.offset}"
        return errors, detail
    except Exception as exc:
        return errors, f"{type(exc).__name__}: {exc}"

    scene_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GeneratedScene"
    ]
    if len(scene_classes) != 1:
        errors.append("Script must define exactly one top-level GeneratedScene class.")
        return errors, None
    scene_class = scene_classes[0]

    base_names: set[str] = set()
    for base in scene_class.bases:
        if isinstance(base, ast.Name):
            base_names.add(base.id)
        elif isinstance(base, ast.Attribute):
            base_names.add(base.attr)
    if "VoiceoverScene" not in base_names:
        errors.append("GeneratedScene must inherit VoiceoverScene.")
    if uses_3d and "ThreeDScene" not in base_names:
        errors.append("Actual 3D API usage requires ThreeDScene inheritance.")

    constructs = [
        node for node in scene_class.body if isinstance(node, ast.FunctionDef) and node.name == "construct"
    ]
    if len(constructs) != 1:
        errors.append("GeneratedScene must define exactly one construct(self) method.")
        return list(dict.fromkeys(errors)), None
    construct = constructs[0]

    def is_self_call(node: ast.AST, attr: str) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        )

    calls = [node for node in ast.walk(construct) if isinstance(node, ast.Call)]
    if not any(is_self_call(node, "set_speech_service") for node in calls):
        errors.append("construct() must call self.set_speech_service(...).")
    if not any(
        isinstance(node.func, ast.Name) and node.func.id == "GTTSService"
        for node in calls
    ):
        errors.append("construct() must configure GTTSService.")
    if not any(is_self_call(node, "voiceover") for node in calls):
        errors.append("Creative scene must include at least one self.voiceover block.")
    errors.extend(_code_usage_errors(tree))
    return list(dict.fromkeys(errors)), None

def sanitize_manim_script(src: str) -> SanitizeResult:
    """Sanitize one model-authored script using hard safety/execution checks only.

    Visual quality, number of animations, graph construction style, and pedagogical choices are
    intentionally left to the real render and evidence-based repair path.
    """
    original = str(src or "")
    changes: list[str] = []
    cleaned = strip_code_fences(original)
    if cleaned != original.strip():
        changes.append("Removed markdown code fences or transport whitespace")

    cleaned, compatibility_changes = _patch_known_manim_compatibility(cleaned)
    changes.extend(compatibility_changes)

    cleaned, import_changes, removed_imports, removed_names = _normalize_imports(cleaned)
    changes.extend(import_changes)

    uses_3d = _uses_3d_ast(cleaned)
    cleaned, class_changes, structural_errors = _normalize_single_scene_class(cleaned, uses_3d)
    changes.extend(class_changes)

    unresolved = _find_unresolved_removed_names(cleaned, removed_names)
    blocked = _find_blocked_operations_ast(cleaned)
    validation_errors, compile_error = _validate_scene_ast(cleaned, uses_3d)
    validation_errors = list(dict.fromkeys(structural_errors + validation_errors))

    if unresolved:
        validation_errors.append(
            "References remain after unsupported imports were removed: " + ", ".join(unresolved)
        )
    if blocked:
        validation_errors.append(
            "Blocked executable operations remain in the script: " + ", ".join(blocked)
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
    out = out.replace(_LEGACY_SERVICE_IMPORT, "")
    out = out.replace(VOICEOVER_SERVICE_IMPORT, "")
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
