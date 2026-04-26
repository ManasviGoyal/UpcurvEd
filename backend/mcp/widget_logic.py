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
1. Be fully self-contained — all JS/CSS inline or from these CDNs only:
     React 18:    https://unpkg.com/react@18/umd/react.development.js
     ReactDOM 18: https://unpkg.com/react-dom@18/umd/react-dom.development.js
     Babel:       https://unpkg.com/@babel/standalone/babel.min.js
     Tailwind:    https://cdn.tailwindcss.com

2. Use React + JSX (Babel will transpile it at runtime):
     <script type="text/babel">
       const { useState, useEffect, useRef, useCallback } = React;
       function App() { ... }
       const root = ReactDOM.createRoot(document.getElementById('root'));
       root.render(<App />);
     </script>

3. Teach ONE concept through hands-on interaction:
   - Sliders, toggles, buttons that change the visualization in real time
   - Animated values, charts drawn on <canvas>, or CSS transitions
   - Clear labels, a short title, and a one-line explanation
   - At least TWO interactive controls the student can manipulate

4. Style with Tailwind utility classes. Keep the layout clean and mobile-friendly.
   Use a white or light-gray background. Keep it compact (fits in ~450px height).

5. NO external API calls, no localStorage, no cookies.
   Must work entirely in a sandboxed iframe after CDN scripts load.

6. The document must start with <!DOCTYPE html> and end with </html>.
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
