# backend/agent/utils/helpers.py


def truncate(text: str | None, max_chars: int) -> str:
    """Truncate long fields so logs stay readable."""
    if not text:
        return ""
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text
