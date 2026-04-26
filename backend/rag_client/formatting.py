# backend/rag_client/formatting.py
from typing import Any


def format_retrieved_docs(results: list[dict[str, Any]], max_length: int = 2000) -> str:
    if not results:
        return ""
    parts, used = [], 0
    for i, r in enumerate(results, 1):
        content = r.get("content", "")
        md = r.get("metadata") or {}
        score = r.get("score", 0.0)
        source = md.get("source") or md.get("path") or md.get("file", "")
        category = md.get("category") or md.get("type", "")
        header_bits = []
        if source:
            header_bits.append(f"Source: {source}")
        if category:
            header_bits.append(f"Type: {category}")
        header_bits.append(f"Relevance: {score:.3f}")
        header = " | ".join(header_bits)
        block = f"[Doc {i}] {header}\n{content}\n"
        if used + len(block) > max_length:
            remain = max_length - used
            if remain > 100:
                trunc = content[: remain - 50] + "... [truncated]"
                block = f"[Doc {i}] {header}\n{trunc}\n"
                parts.append(block)
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts).strip()
