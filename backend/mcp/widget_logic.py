# backend/mcp/widget_logic.py
"""
Generate self-contained interactive HTML widgets for teaching concepts.
Standalone module, no LangGraph.
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


WIDGET_SYSTEM = """You generate self-contained interactive educational HTML widgets.
Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

This widget will be rendered inside a sandboxed iframe in a desktop app.
If you break any rule below, the widget may fail.

Hard requirements:
1. Return a complete HTML document:
   - It must start with <!DOCTYPE html>
   - It must contain <html>, <head>, <body>, and a closing </html>

2. Use ONLY vanilla HTML, CSS, and JavaScript.
   - No React, ReactDOM, Babel, Tailwind, libraries, modules, imports, TypeScript, JSX, or templates.
   - No external scripts, external CSS, external fonts, external images, CDN URLs, or network requests.
   - No fetch, XMLHttpRequest, localStorage, cookies, window.top, window.parent, or same-origin assumptions.

3. Keep it small and reliable.
   - Maximum 1 canvas
   - Maximum 2 buttons
   - Maximum 2 sliders
   - Maximum 1 select
   - No large arrays or long hardcoded datasets
   - No more than about 220 lines total

4. The widget must teach exactly one concept through interaction.
   - Include a clear title
   - Include one short explanatory sentence
   - Include a visible status/result text element that updates when the user interacts
   - Include at least 2 interactive controls

5. All CSS must be in one <style> block in <head>.
6. All JavaScript must be in one <script> block near the end of <body>.
7. Use addEventListener for interactivity.
8. If using a canvas:
   - attach listeners directly to the canvas
   - compute coordinates with getBoundingClientRect()
9. Use a white background, system-ui font, good contrast, and compact side-panel layout.
10. Do not use transparent overlays or absolute-positioned elements that could block pointer events.

Completeness requirements:
- Do not truncate the response.
- Do not end inside a JavaScript function, object, array, string, or conditional.
- Make sure every <style> tag is closed.
- Make sure every <script> tag is closed.
- Make sure every HTML tag is closed.
- Before finishing, verify that the document ends with </script> (if a script is used), </body>, and </html>.
- If you cannot complete a working widget, return a simpler widget instead of a partial one.

Fallback rule:
- If the concept is too complex for a reliable interactive widget, simplify it to the most basic visual intuition and build a smaller widget that still teaches the core idea.

Reliability rules:
- Prefer simple deterministic interaction over fancy visuals.
- Do not generate partial code.
- Do not leave any object literals, arrays, functions, strings, or conditions unfinished.
- Make sure every tag is closed and every function body is complete.
- The widget must actually run, not just look impressive.
"""


def _widget_user_prompt(topic: str) -> str:
    return (
        f"Create an interactive educational widget that teaches: {topic}\n\n"
        "Focus on the most fundamental, visualizable aspect of this concept. "
        "Keep the implementation simple, compact, and robust. "
        "The widget must work on the first try in a sandboxed iframe.\n\n"
        "Output ONLY the HTML document."
    )


def _extract_html(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
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
    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    logger.info("widget: calling LLM provider=%s model=%s", prov, model)

    raw = call_llm(
        provider=prov,
        api_key=api_key,
        model=model,
        system=WIDGET_SYSTEM,
        user=_widget_user_prompt(prompt),
        temperature=0.2,
    )

    if not raw or not raw.strip():
        raise RuntimeError("LLM returned empty widget.")

    html = _extract_html(raw)
    logger.info("widget: generated %d chars of HTML", len(html))

    return {
        "status": "ok",
        "widget_html": html,
    }
