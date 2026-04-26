"""
RAG preprocessing pipeline (smart chunking)

This script processes Manim documentation (RST) and code samples into
clean, structure-aware chunks suitable for Retrieval Augmented Generation.

Key upgrades vs. the original:
- RST-aware chunking: never splits code blocks, tables, or lists; keeps section headers
- Token-aware sizes (uses tiktoken if available; otherwise a robust fallback)
- Stronger Scene detection (handles ast.Attribute bases like manim.Scene)
- Bundles required imports and referenced helper defs with each Scene
- Consistent relative paths under the same base directory
- More resilient category detection + small bug fixes

Usage:
    python rag/preprocess_rag_smart.py
    python rag/preprocess_rag_smart.py --chunk-size 450 --overlap 80
"""

import argparse
import ast
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# -------------------------------
# Token utilities
# -------------------------------


def _approx_token_len(text: str) -> int:
    """
    Fallback token estimator when tiktoken isn't available.
    Heuristic: ~1 token per 4 characters, bounded by word count.
    """
    if not text:
        return 0
    chars = len(text)
    words = len(re.findall(r"\S+", text))
    return max(words, chars // 4)


def token_len(text: str) -> int:
    """Prefer tiktoken if present, otherwise fallback to heuristic."""
    try:
        import tiktoken  # optional dependency

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return _approx_token_len(text)


# -------------------------------
# RST parsing and chunking
# -------------------------------

RST_CODE_BLOCK_RE = re.compile(r"^\s*\.\.\s*code-block::\s*([a-zA-Z0-9_\-+.]*)\s*$")
RST_DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+([a-zA-Z0-9_\-]+)::(.*)$")
RST_DOUBLE_COLON_END_RE = re.compile(r"::\s*$")
SECTION_UNDERLINE_CHARS = set("= - ` : ' \" ~ ^ _ # * + < >".split())


def _is_underline(line: str, title_len: int) -> bool:
    s = line.rstrip("\n")
    if not s:
        return False
    ch = s[0]
    if ch not in "".join(SECTION_UNDERLINE_CHARS):
        return False
    if any(c != ch for c in s):
        return False
    return len(s) >= title_len


def _collect_indented_block(lines: list[str], start_idx: int) -> tuple[int, list[str]]:
    """
    Collect a block of lines that are indented (>= 1 space) starting at start_idx.
    Returns (next_index, block_lines).
    """
    i = start_idx
    block = []
    # skip one optional blank line (RST allows a blank line after directives)
    if i < len(lines) and lines[i].strip() == "":
        block.append(lines[i])
        i += 1
    # collect indented lines (>= 1 leading space)
    while i < len(lines):
        if lines[i].startswith(" ") or lines[i].startswith("\t"):
            block.append(lines[i])
            i += 1
        elif lines[i].strip() == "" and block:
            # allow trailing blank lines to stick with the block
            block.append(lines[i])
            i += 1
        else:
            break
    # strip trailing blank lines to keep blocks tight
    while block and block[-1].strip() == "":
        block.pop()
    return i, block


def parse_rst_to_units(content: str) -> list[dict[str, Any]]:
    """
    Convert raw RST into a list of structural units:
    types: 'section', 'paragraph', 'code', 'list', 'table', 'admonition', 'raw'
    Each unit has 'text' (string). Code/list/table/admonition are treated as atomic.
    """
    lines = content.splitlines(keepends=True)
    units: list[dict[str, Any]] = []
    i = 0

    def flush_paragraph(buf: list[str]):
        text = "".join(buf).strip()
        if text:
            units.append({"type": "paragraph", "text": text + "\n"})
        buf.clear()

    para_buf: list[str] = []

    while i < len(lines):
        line = lines[i]

        # Section detection: title followed by underline line of repeated char
        if line.strip() and (i + 1) < len(lines) and _is_underline(lines[i + 1], len(line.strip())):
            # flush any paragraph before a section
            flush_paragraph(para_buf)
            title = line.strip()
            underline = lines[i + 1].rstrip("\n")
            units.append({"type": "section", "text": f"{title}\n{underline}\n"})
            i += 2
            continue

        # RST code-block directive
        m = RST_CODE_BLOCK_RE.match(line)
        if m:
            flush_paragraph(para_buf)
            lang = m.group(1) or ""
            # collect options lines starting with ":" and the following indented block
            i += 1
            # swallow any option lines (e.g., :linenos:)
            while i < len(lines) and lines[i].lstrip().startswith(":"):
                i += 1
            next_i, block = _collect_indented_block(lines, i)
            code_text = "".join(block)
            units.append({"type": "code", "lang": lang, "text": code_text})
            i = next_i
            continue

        # "double colon" -> code block follows
        if RST_DOUBLE_COLON_END_RE.search(line):
            flush_paragraph(para_buf)
            # include the line up to '::' as paragraph context
            base = RST_DOUBLE_COLON_END_RE.sub(":", line).rstrip() + "\n"
            # now collect the indented code block
            i += 1
            next_i, block = _collect_indented_block(lines, i)
            units.append({"type": "paragraph", "text": base})
            units.append({"type": "code", "lang": "", "text": "".join(block)})
            i = next_i
            continue

        # Admonitions (.. note::, .. warning::, etc.) – keep as unit incl. indented body
        mdir = RST_DIRECTIVE_RE.match(line)
        if mdir and mdir.group(1) in {
            "note",
            "warning",
            "tip",
            "important",
            "attention",
            "caution",
            "hint",
        }:
            flush_paragraph(para_buf)
            # capture directive line + its body
            directive_line = line
            i += 1
            next_i, block = _collect_indented_block(lines, i)
            units.append(
                {
                    "type": "admonition",
                    "role": mdir.group(1),
                    "text": directive_line + "".join(block),
                }
            )
            i = next_i
            continue

        # Simple table (grid or simple) – treat consecutive non-empty lines
        # with table rulers as a unit
        if re.match(r"^\s*[=+\-]+[=+\-\s]*$", line):
            # likely a table or section underline – disambiguate:
            if not (i > 0 and _is_underline(line, len(lines[i - 1].strip()))):
                flush_paragraph(para_buf)
                table_lines = [line]
                i += 1
                while i < len(lines) and (
                    lines[i].strip() != "" or re.match(r"^\s*[=+\-]+", lines[i])
                ):
                    table_lines.append(lines[i])
                    i += 1
                units.append({"type": "table", "text": "".join(table_lines)})
                continue

        # Lists – capture bullet/enum until blank line boundary
        if re.match(r"^\s*(?:[-+*]|\d+[\.)])\s+", line):
            flush_paragraph(para_buf)
            list_lines = [line]
            i += 1
            while i < len(lines) and (lines[i].strip() != "" or re.match(r"^\s{2,}\S", lines[i])):
                # allow indented continuation lines
                if lines[i].strip() == "" and (
                    i + 1 < len(lines) and re.match(r"^\s{2,}\S", lines[i + 1])
                ):
                    list_lines.append(lines[i])
                    i += 1
                    continue
                if lines[i].strip() == "":
                    break
                list_lines.append(lines[i])
                i += 1
            units.append({"type": "list", "text": "".join(list_lines)})
            continue

        # Normal text line → accumulate for paragraph
        if line.strip() == "":
            # paragraph boundary
            flush_paragraph(para_buf)
        else:
            para_buf.append(line)
        i += 1

    flush_paragraph(para_buf)
    return units


def chunk_units_smart(
    units: list[dict[str, Any]], chunk_size_tokens: int, overlap_tokens: int
) -> list[str]:
    """
    Build chunks from structural units without splitting atomic ones.
    Overlap is applied only over trailing paragraph text to aid continuity.
    """
    chunks: list[str] = []
    cur_parts: list[str] = []
    cur_tokens = 0

    def emit_chunk():
        nonlocal cur_parts, cur_tokens
        if not cur_parts:
            return
        chunk_text = "".join(cur_parts).strip()
        if chunk_text:
            chunks.append(chunk_text)
        cur_parts = []
        cur_tokens = 0

    last_paragraph_tail = ""

    for u in units:
        u_text = u.get("text", "")
        u_tok = token_len(u_text)

        # If adding this unit would exceed the budget, emit current chunk.
        if cur_parts and (cur_tokens + u_tok) > chunk_size_tokens:
            # prepare overlap only from paragraph tails
            emit_chunk()
            # apply overlap: reuse the last piece of paragraph tail, if present
            if last_paragraph_tail and overlap_tokens > 0:
                # trim tail to overlap budget
                tail = last_paragraph_tail
                # attempt to keep overlap within tokens
                # (coarse: slice last N chars; then ensure token budget later)
                # choose a generous slice; token_len will cap future additions anyway
                cur_parts.append(tail)
                cur_tokens = token_len("".join(cur_parts))
        # append current unit
        cur_parts.append(u_text)
        cur_tokens += u_tok

        # remember paragraph tails for overlap
        if u["type"] == "paragraph":
            # keep last ~overlap_tokens worth of paragraph
            text = u_text
            # approximate trimming by chars based on token heuristic
            want_chars = max(100, overlap_tokens * 4)
            last_paragraph_tail = text[-want_chars:]
        else:
            last_paragraph_tail = ""

    emit_chunk()
    return chunks


def extract_rst_content(rst_file: Path) -> str:
    """Read RST file with UTF-8 and ignore errors."""
    with open(rst_file, encoding="utf-8", errors="ignore") as f:
        return f.read()


def chunk_rst_document(rst_file: Path, chunk_size_tokens: int, overlap_tokens: int) -> list[str]:
    """Parse a single RST file into structure-aware chunks."""
    content = extract_rst_content(rst_file)
    if not content.strip():
        return []
    units = parse_rst_to_units(content)
    chunks = chunk_units_smart(units, chunk_size_tokens, overlap_tokens)
    return chunks


# -------------------------------
# Categories
# -------------------------------


def determine_doc_category(file_path: Path) -> str:
    """Determine content category from file path."""
    path_str = str(file_path).lower()
    if "animation" in path_str:
        return "animation"
    if "geometry" in path_str or "shape" in path_str:
        return "geometry"
    if "text" in path_str or "tex" in path_str:
        return "text"
    if "3d" in path_str or "three" in path_str:
        return "3d"
    if "graph" in path_str:
        return "graph"
    if "config" in path_str:
        return "configuration"
    return "general"


def determine_scene_category(scene_name: str, code: str) -> str:
    """Categorize scene based on name and content."""
    name_lower = scene_name.lower()
    code_lower = code.lower()
    if (
        "threed" in name_lower
        or "threedscene" in code_lower
        or "three_d" in code_lower
        or "3d" in code_lower
    ):
        return "3d"
    if "graph" in name_lower or "digraph" in code_lower or "graph(" in code_lower:
        return "graph"
    if "transform" in name_lower or "transform(" in code_lower:
        return "transform"
    if "tex" in code_lower or "mathtex" in code_lower or "mathml" in code_lower:
        return "math"
    if any(
        shape in code_lower for shape in ["circle", "square", "polygon", "rectangle", "triangle"]
    ):
        return "geometry"
    if "text(" in code_lower and "tex" not in code_lower:
        return "text"
    if "updater" in code_lower or "always" in code_lower:
        return "animation"
    return "general"


# -------------------------------
# Documentation processing
# -------------------------------


def chunk_documentation(
    doc_dir: Path, base_root: Path, chunk_size_tokens: int, overlap_tokens: int
) -> list[dict[str, Any]]:
    """Chunk all .rst files under doc_dir with structure-aware rules."""
    chunks: list[dict[str, Any]] = []
    print(f"  Scanning {doc_dir} for RST files...")
    rst_files = [
        path
        for path in doc_dir.rglob("*.rst")
        if "changelog" not in path.relative_to(doc_dir).parts[:1]
    ]
    print(f"Found {len(rst_files)} RST files to process")
    print("Processing documentation...")

    processed_count = 0
    global_chunk_id = 0

    for rst_file in rst_files:
        try:
            print(f"Processing: {rst_file.name}...", end="", flush=True)
            file_chunks = chunk_rst_document(rst_file, chunk_size_tokens, overlap_tokens)
            if not file_chunks:
                print(" [empty, skipped]")
                continue

            category = determine_doc_category(rst_file)
            cnt = 0
            for chunk in file_chunks:
                if len(chunk.strip()) < 80:  # skip trivially small chunks
                    continue
                chunks.append(
                    {
                        "content": chunk,
                        "source": str(rst_file.relative_to(base_root)),
                        "type": "documentation",
                        "chunk_id": f"doc_{global_chunk_id}",
                        "category": category,
                    }
                )
                global_chunk_id += 1
                cnt += 1
            processed_count += 1
            print(f" {cnt} chunks")
            if processed_count % 10 == 0:
                print(
                    f"Processed {processed_count}/{len(rst_files)} files | "
                    f"{len(chunks)} total chunks"
                )
        except Exception as e:
            print(f" Error: {e}")

    return chunks


# -------------------------------
# Code example extraction (AST)
# -------------------------------


def _base_name_from_node(base: ast.AST) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr  # e.g., manim.Scene -> attr="Scene"
    return ""


def _is_scene_subclass(node: ast.ClassDef) -> bool:
    base_names = [_base_name_from_node(b) for b in node.bases]
    return any("Scene" in n for n in base_names if n)


def _get_source_segment(source: str, node: ast.AST) -> str:
    lines = source.splitlines()
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", None)
    if end is None:
        # conservative fallback: 50 lines
        end = min(len(lines), start + 50)
    return "\n".join(lines[start:end])


def _collect_imports(tree: ast.AST, source: str) -> str:
    imports: list[str] = []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(_get_source_segment(source, node))
    # de-dup while preserving order
    seen = set()
    uniq = []
    for line in imports:
        if line not in seen:
            uniq.append(line)
            seen.add(line)
    return "\n".join(uniq)


def _collect_helpers(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    helpers: dict[str, ast.FunctionDef] = {}
    if not isinstance(tree, ast.Module):
        return helpers
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            helpers[node.name] = node
    return helpers


def _names_referenced_in_class(cls: ast.ClassDef) -> Iterable[str]:
    for n in ast.walk(cls):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            yield n.id


def _signature_and_doc_from_function(source: str, fn_node: ast.FunctionDef) -> str:
    full = _get_source_segment(source, fn_node)
    lines = full.splitlines()
    # signature (first line with 'def' ... ':')
    sig = ""
    for ln in lines:
        if ln.lstrip().startswith("def "):
            sig = ln
            break
    # docstring (ast.get_docstring would need the module tree; simpler manual)
    doc = ast.get_docstring(fn_node)
    doc_part = f'    """{doc}"""' if doc else ""
    return "\n".join([sig, doc_part]).strip() + ("\n" if doc_part else "")


def extract_scene_classes(
    py_file: Path, include_helpers: bool = True, max_tokens: int = 1200
) -> list[dict[str, Any]]:
    """Extract Scene classes and bundle imports + referenced helpers (when useful)."""
    try:
        with open(py_file, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError):
        return []

    scenes: list[dict[str, Any]] = []
    if not isinstance(tree, ast.Module):
        return scenes

    imports_text = _collect_imports(tree, content)
    helpers = _collect_helpers(tree)
    helper_names = set(helpers.keys())

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _is_scene_subclass(node):
            class_code = _get_source_segment(content, node)
            if len(class_code) < 50:
                continue

            needed_helpers = set(_names_referenced_in_class(node)).intersection(helper_names)
            helper_blocks: list[str] = []
            if include_helpers and needed_helpers:
                # try full helper defs first
                for hname in sorted(needed_helpers):
                    helper_blocks.append(_get_source_segment(content, helpers[hname]))

            assembled = []
            if imports_text.strip():
                assembled.append(imports_text.strip() + "\n")
            if helper_blocks:
                assembled.append("\n".join(helper_blocks).strip() + "\n\n")
            assembled.append(class_code.strip())

            full_block = "\n".join(assembled).strip()
            if token_len(full_block) > max_tokens and helper_blocks:
                # Too big: fall back to helper signatures only
                signature_blocks = [
                    _signature_and_doc_from_function(content, helpers[h])
                    for h in sorted(needed_helpers)
                ]
                assembled = []
                if imports_text.strip():
                    assembled.append(imports_text.strip() + "\n")
                if signature_blocks:
                    assembled.append(
                        "# Helper summaries (signatures/docstrings only)\n"
                        + "\n\n".join(signature_blocks).strip()
                        + "\n\n"
                    )
                assembled.append(class_code.strip())
                full_block = "\n".join(assembled).strip()

            category = determine_scene_category(node.name, class_code)
            scenes.append(
                {
                    "content": full_block,
                    "source": str(py_file),  # will normalize to relative later by caller
                    "type": "code_example",
                    "chunk_id": "placeholder",  # will be replaced with a unique ID
                    "scene_name": node.name,
                    "category": category,
                }
            )

    return scenes


def extract_all_examples(
    examples_dir: Path, base_root: Path, start_id: int = 0
) -> list[dict[str, Any]]:
    """Extract all Scene examples from example directories."""
    all_scenes: list[dict[str, Any]] = []

    print(f"Scanning {examples_dir} for Python files...")
    skip_patterns = ["__init__", "__pycache__", "config", "setup", "test_", "conftest"]

    py_files = [
        f for f in examples_dir.rglob("*.py") if not any(skip in str(f) for skip in skip_patterns)
    ]

    print(f"Found {len(py_files)} Python files to scan")
    print("Extracting Scene classes...")

    processed_count = 0
    files_with_scenes = 0
    current_id = start_id

    for py_file in py_files:
        scenes = extract_scene_classes(py_file)
        if scenes:
            # normalize sources to be relative to base_root
            for scene in scenes:
                scene["source"] = str(Path(scene["source"]).relative_to(base_root))
                scene["chunk_id"] = f"code_{current_id}"
                current_id += 1
            files_with_scenes += 1
            print(
                f"Found {len(scenes)} scene(s) in {py_file.name} | Total: "
                f"{len(all_scenes) + len(scenes)}"
            )
            all_scenes.extend(scenes)

        processed_count += 1
        if processed_count % 50 == 0:
            print(
                f"{processed_count}/{len(py_files)} files scanned, {len(all_scenes)} scenes found"
            )

    print(f"Scanned {processed_count} files, found scenes in {files_with_scenes} files")
    return all_scenes


# -------------------------------
# Output helpers
# -------------------------------


def save_chunks(chunks: list[dict[str, Any]], output_file: Path):
    """Save chunks to JSON file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(chunks)} chunks to {output_file}")


def print_statistics(chunks: list[dict[str, Any]]):
    """Print stats about the chunks."""
    from collections import Counter

    types = Counter(c["type"] for c in chunks)
    categories = Counter(c["category"] for c in chunks)

    print("\nStatistics:")
    print(f"Total chunks: {len(chunks)}")
    print("\nBy type:")
    for typ, count in types.items():
        print(f"{typ}: {count}")

    print("\nBy category:")
    for cat, count in categories.most_common():
        print(f"{cat}: {count}")

    avg_size_chars = sum(len(c["content"]) for c in chunks) / max(1, len(chunks))
    avg_size_tokens = sum(token_len(c["content"]) for c in chunks) / max(1, len(chunks))
    print(f"\nAverage chunk size: {avg_size_chars:.0f} characters (~{avg_size_tokens:.0f} tokens)")


# -------------------------------
# CLI
# -------------------------------


def main():
    parser = argparse.ArgumentParser(description="Preprocess Manim RAG data (smart chunking)")
    parser.add_argument("--base-dir", default="rag-data", help="Base directory for RAG data")
    parser.add_argument(
        "--chunk-size", type=int, default=450, help="Target token size for documentation chunks"
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=80,
        help="Token overlap for documentation chunks (paragraph tails only)",
    )
    parser.add_argument(
        "--output",
        default="processed/chunks/all_chunks.json",
        help="Output file for chunks (relative to base-dir)",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    # Define a single root so sources are consistent
    base_root = base_dir  # everything under rag-data/...
    doc_dir = base_dir / "documentation" / "manim-docs" / "docs" / "source"
    examples_dir = base_dir / "examples"
    output_file = base_dir / args.output

    import time

    total_start = time.time()
    print("Starting RAG preprocessing pipeline...\n")

    # Step 1: Documentation
    print("Step 1/5: Extracting documentation chunks (structure-aware)...")
    step_start = time.time()
    if doc_dir.exists():
        doc_chunks = chunk_documentation(doc_dir, base_root, args.chunk_size, args.overlap)
        step_time = time.time() - step_start
        print(f"Found {len(doc_chunks)} documentation chunks in {step_time:.1f} seconds\n")
    else:
        print(f"Documentation directory not found: {doc_dir}")
        doc_chunks = []

    # Step 2: Code examples
    print("Step 2/5: Extracting code examples (Scene classes + helpers/imports)...")
    step_start = time.time()
    if examples_dir.exists():
        code_chunks = extract_all_examples(examples_dir, base_root, start_id=len(doc_chunks))
        step_time = time.time() - step_start
        print(f"Found {len(code_chunks)} code examples in {step_time:.1f} seconds\n")
    else:
        print(f"Examples directory not found: {examples_dir}")
        code_chunks = []

    # Step 3: Combine
    print("Step 3/5: Combining chunks...")
    all_chunks = doc_chunks + code_chunks
    if not all_chunks:
        print("No chunks found.")
        return
    print(
        f"Combined {len(doc_chunks)} doc chunks + {len(code_chunks)} code chunks = "
        f"{len(all_chunks)} total\n"
    )

    # Step 4: Save
    print("Step 4/5: Saving chunks...")
    save_chunks(all_chunks, output_file)

    # Step 5: Statistics
    print("Step 5/5: Statistics")
    print_statistics(all_chunks)

    total_time = time.time() - total_start
    print(f"\nTotal processing time: {total_time:.1f} seconds ({total_time / 60:.1f} minutes)")
    print("\nPreprocessing complete.")
    print(f"\nChunks saved to: {output_file}")


if __name__ == "__main__":
    main()
