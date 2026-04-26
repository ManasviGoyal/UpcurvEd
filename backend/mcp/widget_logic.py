# backend/mcp/widget_logic.py
"""
Generate self-contained interactive HTML widgets for teaching concepts.
Mirrors the pattern of podcast_logic.py — standalone module, no LangGraph.
"""
import logging

from backend.agent.llm.clients import call_llm
from backend.utils import app_logging  # noqa: F401

logger = logging.getLogger(f"app.{__name__}")


def _pick_provider_and_key(
    provider: str | None, provider_keys: dict[str, str] | None
) -> tuple[str, str]:
    keys = provider_keys or {}
    prov = (provider or "").lower()
    if prov in ("claude", "gemini"):
        key = keys.get(prov) or ""
        if not key:
            raise RuntimeError(f"Missing API key for provider '{prov}'.")
        return prov, key
    if keys.get("claude"):
        return "claude", keys["claude"]
    if keys.get("gemini"):
        return "gemini", keys["gemini"]
    raise RuntimeError("No provider keys available. Provide 'claude' or 'gemini' key.")


WIDGET_SYSTEM = """\
You generate self-contained interactive educational HTML widgets.
Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

The HTML must:
1. Be 100% self-contained — NO external CDN links whatsoever. No src= pointing 
   to unpkg, cdnjs, cdn.tailwindcss.com, or any URL. Everything inline. Or else it won't load and the user will see a broken widget.

2. Use only vanilla HTML, CSS, and JavaScript (ES6+). No React, no Babel, 
   no Tailwind, no libraries. All JS in a <script> block, all CSS in a <style> block.

3. Teach ONE concept through hands-on interaction:
   - Use <input type="range">, buttons, or checkboxes with addEventListener
   - Draw on <canvas> or manipulate DOM elements directly in JS
   - At least TWO interactive controls the student can manipulate
   - Clear title, one-sentence explanation, labeled controls

4. Style with an inline <style> block. White background, system-ui font,
   good contrast. Compact layout (~450px height).

5. NO fetch(), NO XMLHttpRequest, NO external resources of any kind.
   Must work fully offline in a sandboxed iframe with allow-scripts only.

6. Start with <!DOCTYPE html> and end with </html>.
"""


def _widget_user_prompt(topic: str) -> str:
    return (
        f"Create an interactive educational widget that teaches: {topic}\n\n"
        "Focus on the most fundamental, visualizable aspect of this concept.\n"
        "Make it immediately intuitive — a student should understand the core idea "
        "within 30 seconds of playing with it.\n"
        "Output ONLY the HTML document."
    )


def _extract_html(raw: str) -> str:
    """Strip any accidental markdown fences the model may add."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text.lower().startswith("<!doctype") and "<html" not in text.lower():
        raise RuntimeError("Model did not return a valid HTML document.")
    return text


def generate_widget(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Generate an interactive HTML widget for the given topic.
    Returns { status, widget_html } — no GCS upload, HTML is inline.
    """
    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    logger.info("widget: calling LLM provider=%s model=%s", prov, model)

    raw = call_llm(
        provider=prov,
        api_key=api_key,
        model=model,
        system=WIDGET_SYSTEM,
        user=_widget_user_prompt(prompt),
        temperature=0.4,
    )

    if not raw or not raw.strip():
        raise RuntimeError("LLM returned empty widget.")

    html = _extract_html(raw)
    logger.info("widget: generated %d chars of HTML", len(html))

    return {
        "status": "ok",
        "widget_html": html,
    }
