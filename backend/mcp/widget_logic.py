# backend/mcp/widget_logic.py
"""
Generate self-contained interactive HTML widgets for teaching concepts.
Standalone module, no LangGraph.
"""
import logging
import json
import re
from html import escape

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


WIDGET_SYSTEM = """You generate self-contained interactive educational HTML simulations.
Output ONLY a complete HTML document. No markdown, no backticks, no explanation.

This widget runs in a sandboxed iframe inside a desktop app. It must be robust.

Hard requirements:
1) Return a complete HTML document:
   - Starts with <!DOCTYPE html>
   - Contains <html>, <head>, <body>, and closing </html>

2) Technology constraints:
   - Vanilla HTML/CSS/JS only (no React, no build tools, no TypeScript).
   - No external scripts/styles/fonts/images/CDNs.
   - No external stylesheet links (<link rel="stylesheet" href="...">) and no CSS @import.
   - No fetch/XMLHttpRequest/WebSocket.
   - No localStorage/sessionStorage/cookies/indexedDB.
   - No window.top/window.parent assumptions.

3) Simulation-first UI structure:
   - Two-column layout:
     left = main visualization area (canvas or SVG),
     right = control panel.
   - Control panel sections:
     a) "Live Data" section with at least 3 numeric readouts with units.
     b) "Controls" section with at least 3 interactive controls.
   - Controls must be visible in initial viewport (no collapsed drawers required to access them).
   - Include one short concept explanation line.
   - Include one status/insight line that changes as controls change.

4) Interactivity:
   - Use addEventListener.
   - Use requestAnimationFrame for animated simulations.
   - The simulation must start with visible non-zero state (not an empty static canvas).
   - Keep simulation deterministic and smooth on modest hardware.
   - If using canvas interactions, use getBoundingClientRect() for coordinates.

5) Styling:
   - Use one <style> block in <head>.
   - Use one <script> block near end of <body>.
   - Make it visually polished and educational (not plain boilerplate).
   - Ensure good contrast and readable labels.
   - Ensure controls are visible without requiring hidden panels.
   - Do not place invisible overlays that block pointer events.

6) Complexity limits (for reliability):
   - Max 1 canvas.
   - Keep code compact and maintainable.
   - Avoid giant datasets and long hardcoded tables.

Completeness rules:
- Do not truncate output.
- Close all tags.
- Close all functions/objects/arrays/conditionals.
- End cleanly with </script> (if used), </body>, </html>.
- If concept is too complex, deliver a simplified but fully working simulation.

Required HTML skeleton (follow this structure exactly and fill in the simulation content):
<body>
  <div class="wrapper">
    <div class="viz-col" id="viz-col">
      <canvas id="sim-canvas"></canvas>
    </div>
    <div class="panel-col">
      <h2 class="panel-title">...</h2>
      <p class="concept-line">...</p>
      <div class="section-label">LIVE DATA</div>
      ...
      <div class="section-label">CONTROLS</div>
      ...
      <div class="insight-box" id="insight">...</div>
    </div>
  </div>
  <script>
    window.addEventListener('DOMContentLoaded', () => {
      const vizCol = document.getElementById('viz-col');
      const canvas = document.getElementById('sim-canvas');
      canvas.width = vizCol.clientWidth;
      canvas.height = vizCol.clientHeight;
      // initialize non-zero simulation state
      // start requestAnimationFrame loop here
    });
  </script>
</body>
"""


def _widget_user_prompt(topic: str) -> str:
    return (
        f"Create an interactive educational simulation for: {topic}\n\n"
        "Design target: app-like simulation quality, similar to science learning tools.\n"
        "Use a left visualization panel and right control panel.\n"
        "Include meaningful live metrics and controls that clearly change system behavior.\n"
        "Controls must always be visible (not hidden/collapsed).\n"
        "Canvas must be sized in DOMContentLoaded and animation must start there.\n"
        "Audience: middle/high school learners.\n"
        "The result must run on first load in a sandboxed iframe.\n\n"
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
    low = text.lower()
    if not low.startswith("<!doctype") and "<html" not in low:
        raise RuntimeError("Model did not return a valid HTML document.")
    if "<script" in low and "</script>" not in low:
        raise RuntimeError("Widget script block appears truncated (missing </script>).")
    if "</body>" not in low:
        raise RuntimeError("Widget HTML appears truncated (missing </body>).")
    if "</html>" not in low:
        raise RuntimeError("Widget HTML appears truncated (missing </html>).")
    # Defensive sanitation: strip accidental external assets that break sandboxed iframes.
    text = re.sub(
        r"""<script\b[^>]*\bsrc\s*=\s*["']https?://[^"']*["'][^>]*>\s*</script>""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"""<link\b[^>]*\brel\s*=\s*["']stylesheet["'][^>]*>""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"""<link\b[^>]*\brel\s*=\s*["']stylesheet["'][^>]*\bhref\s*=\s*["']https?://[^"']*["'][^>]*>""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"""@import\s+url\(["']?https?://[^"')]+["']?\)\s*;?""",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _count_control_elements(html: str) -> int:
    matches = re.findall(r"<(?:button|input|select)\b", html, flags=re.IGNORECASE)
    return len(matches)


def _validate_widget_html(html: str) -> tuple[bool, str]:
    low = html.lower()
    if "<!doctype html" not in low and "<html" not in low:
        return False, "missing full html document structure"
    if "<script" not in low:
        return False, "missing script block"
    if not ("<canvas" in low or "<svg" in low):
        return False, "missing visualization surface (canvas or svg)"
    if _count_control_elements(html) < 3:
        return False, "missing required interactive controls (need >=3)"
    if "requestanimationframe" not in low:
        return False, "missing requestAnimationFrame loop"
    if "domcontentloaded" not in low:
        return False, "missing DOMContentLoaded initialization"
    if re.search(r"<link\b[^>]*\brel\s*=\s*['\"]stylesheet['\"]", low):
        return False, "contains forbidden stylesheet link tag"
    if "@import" in low:
        return False, "contains forbidden CSS @import"
    return True, ""


def _repair_widget_html(
    *,
    provider: str,
    api_key: str,
    model: str | None,
    topic: str,
    prior_html: str,
    reason: str,
) -> str:
    repair_system = (
        "You repair interactive HTML simulations. "
        "Return ONLY fixed full HTML document. No markdown."
    )
    repair_user = (
        f"The previous widget for topic '{topic}' failed validation: {reason}.\n\n"
        "Fix it so it has:\n"
        "- visible animated visualization (canvas or svg) on load\n"
        "- right-side controls panel with >=3 controls\n"
        "- live metrics that update\n"
        "- requestAnimationFrame loop\n"
        "- no external scripts, no <link rel='stylesheet'>, no @import\n\n"
        "Previous HTML:\n"
        f"{prior_html}\n\n"
        "Return ONLY corrected full HTML."
    )
    fixed_raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=repair_system,
        user=repair_user,
        temperature=0.1,
        max_tokens=6000,
        max_output_tokens=6000,
    )
    return _extract_html(fixed_raw)


def _retry_widget_html(
    *,
    provider: str,
    api_key: str,
    model: str | None,
    topic: str,
    reason: str,
    prior_html: str | None = None,
) -> str:
    prior_html_section = (
        "Previous HTML (possibly truncated):\n" + prior_html if prior_html else ""
    )
    retry_system = (
        "You regenerate compact interactive HTML simulations. "
        "Output ONLY complete HTML. Keep it shorter and fully closed."
    )
    retry_user = (
        f"Topic: {topic}\n"
        f"Previous attempt failed due to: {reason}\n\n"
        "Return a SHORTER but still polished interactive simulation with:\n"
        "- left canvas + right controls panel\n"
        "- live metrics\n"
        "- >=3 visible controls\n"
        "- DOMContentLoaded init\n"
        "- requestAnimationFrame loop\n"
        "- no external assets, no link rel=stylesheet, no @import\n"
        "- complete closing tags\n\n"
        f"{prior_html_section}\n"
        "Output ONLY full HTML."
    )
    raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=retry_system,
        user=retry_user,
        temperature=0.1,
        max_tokens=6000,
        max_output_tokens=6000,
    )
    return _extract_html(raw)


def _extract_first_json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _derive_prompt_spec(
    *,
    provider: str,
    api_key: str,
    model: str | None,
    topic: str,
) -> dict:
    system = (
        "Return ONLY strict JSON for a simulation UI spec. "
        "No markdown. No comments."
    )
    user = (
        f"Topic: {topic}\n"
        "Return JSON with keys:\n"
        "title (string), concept_line (string), "
        "metrics (array of exactly 3 objects: {label, unit}), "
        "controls (array of exactly 3 objects: {label, min, max, step, value}), "
        "insight_low (string), insight_high (string).\n"
        "Keep labels concise and directly relevant to the topic."
    )
    raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=system,
        user=user,
        temperature=0.0,
        max_tokens=500,
        max_output_tokens=500,
    )
    spec = _extract_first_json_object(raw) or {}
    if not isinstance(spec, dict):
        return {}
    return spec


def _safe_spec(topic: str, spec: dict | None) -> dict:
    prompt = (topic or "").strip()
    prompt_short = prompt[:120] if prompt else "this concept"
    base = {
        "title": "Interactive Concept Lab",
        "concept_line": f"Explore: {prompt_short}",
        "metrics": [
            {"label": "Response", "unit": "u"},
            {"label": "Stability", "unit": "%"},
            {"label": "Rate", "unit": "u/s"},
        ],
        "controls": [
            {"label": "Primary factor", "min": 0.2, "max": 2.0, "step": 0.01, "value": 1.0},
            {"label": "Secondary factor", "min": 0.0, "max": 1.0, "step": 0.01, "value": 0.4},
            {"label": "Pacing", "min": 0.5, "max": 3.0, "step": 0.01, "value": 1.2},
        ],
        "insight_low": f"Lower settings simplify the behavior for {prompt_short}.",
        "insight_high": f"Higher settings produce stronger effects for {prompt_short}.",
    }
    data = spec if isinstance(spec, dict) else {}
    title = str(data.get("title") or base["title"])[:80]
    concept_line = str(data.get("concept_line") or base["concept_line"])[:220]
    metrics = data.get("metrics") if isinstance(data.get("metrics"), list) else []
    controls = data.get("controls") if isinstance(data.get("controls"), list) else []
    if len(metrics) < 3:
        metrics = base["metrics"]
    if len(controls) < 3:
        controls = base["controls"]

    def _metric(m: dict, fb: dict) -> dict:
        if not isinstance(m, dict):
            return fb
        return {"label": str(m.get("label") or fb["label"])[:28], "unit": str(m.get("unit") or fb["unit"])[:14]}

    def _num(v, fb):
        try:
            return float(v)
        except Exception:
            return fb

    def _control(c: dict, fb: dict) -> dict:
        if not isinstance(c, dict):
            return fb
        mn = _num(c.get("min"), fb["min"])
        mx = _num(c.get("max"), fb["max"])
        if mx <= mn:
            mn, mx = fb["min"], fb["max"]
        step = abs(_num(c.get("step"), fb["step"])) or fb["step"]
        val = _num(c.get("value"), fb["value"])
        val = min(max(val, mn), mx)
        return {
            "label": str(c.get("label") or fb["label"])[:32],
            "min": mn,
            "max": mx,
            "step": step,
            "value": val,
        }

    return {
        "title": escape(title),
        "concept_line": escape(concept_line),
        "metrics": [_metric(metrics[i], base["metrics"][i]) for i in range(3)],
        "controls": [_control(controls[i], base["controls"][i]) for i in range(3)],
        "insight_low": escape(str(data.get("insight_low") or base["insight_low"])[:220]),
        "insight_high": escape(str(data.get("insight_high") or base["insight_high"])[:220]),
    }


def _topic_fallback_widget_html(
    topic: str,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    derived = {}
    if provider and api_key:
        try:
            derived = _derive_prompt_spec(
                provider=provider,
                api_key=api_key,
                model=model,
                topic=topic,
            )
        except Exception:
            derived = {}
    s = _safe_spec(topic, derived)
    m1, m2, m3 = s["metrics"]
    c1, c2, c3 = s["controls"]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{s["title"]}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#0a1024;color:#eaf2ff}}
.wrapper{{display:grid;grid-template-columns:2fr 1fr;min-height:100vh}}
.viz-col{{border-right:1px solid #223e6d;position:relative}} #sim-canvas{{width:100%;height:100%;display:block}}
.panel-col{{padding:14px;background:#0f1d40}} .section-label{{margin-top:10px;font-size:12px;letter-spacing:.08em;color:#9ac5ff;font-weight:700}}
.row{{display:flex;justify-content:space-between;margin:6px 0}} .row b{{color:#7de0ff}} input[type=range]{{width:100%}}
.hint{{font-size:12px;color:#bfd4ff;margin-top:8px}} .insight-box{{margin-top:10px;padding:8px;border:1px solid #345b88;border-radius:8px;font-size:13px;color:#bae6fd}}
</style></head><body>
<div class="wrapper"><div class="viz-col" id="viz-col"><canvas id="sim-canvas"></canvas></div><div class="panel-col">
<h2 class="panel-title">{s["title"]}</h2><p class="concept-line">{s["concept_line"]}</p>
<div class="section-label">LIVE DATA</div>
<div class="row"><span>{m1["label"]}</span><b id="m1">0.00 {m1["unit"]}</b></div>
<div class="row"><span>{m2["label"]}</span><b id="m2">0.00 {m2["unit"]}</b></div>
<div class="row"><span>{m3["label"]}</span><b id="m3">0.00 {m3["unit"]}</b></div>
<div class="section-label">CONTROLS</div>
<label>{c1["label"]}<input id="a" type="range" min="{c1["min"]}" max="{c1["max"]}" step="{c1["step"]}" value="{c1["value"]}"></label>
<label>{c2["label"]}<input id="b" type="range" min="{c2["min"]}" max="{c2["max"]}" step="{c2["step"]}" value="{c2["value"]}"></label>
<label>{c3["label"]}<input id="c" type="range" min="{c3["min"]}" max="{c3["max"]}" step="{c3["step"]}" value="{c3["value"]}"></label>
<label class="hint"><input id="trail" type="checkbox" checked> Show motion trail</label>
<div class="insight-box" id="insight">{s["insight_low"]}</div>
</div></div>
<script>
window.addEventListener('DOMContentLoaded',()=>{{
const viz=document.getElementById('viz-col'), cv=document.getElementById('sim-canvas'), x=cv.getContext('2d');
const a=document.getElementById('a'), b=document.getElementById('b'), c=document.getElementById('c'), trail=document.getElementById('trail');
const m1=document.getElementById('m1'), m2=document.getElementById('m2'), m3=document.getElementById('m3'), insight=document.getElementById('insight');
let t=0, history=[]; const fit=()=>{{cv.width=viz.clientWidth;cv.height=viz.clientHeight;}}; fit(); window.addEventListener('resize',fit);
const lowMsg={json.dumps(s["insight_low"])}; const highMsg={json.dumps(s["insight_high"])};
const tick=()=>{{
  const w=cv.width,h=cv.height, av=Number(a.value), bv=Number(b.value), cvv=Number(c.value);
  const speed=(0.004+0.012*cvv), amp=(0.12+0.2*av)*Math.min(w,h), varc=(0.2+0.8*bv);
  t += speed*60;
  const px = w*0.5 + Math.cos(t*0.02)*(amp*(0.6+0.4*Math.sin(t*0.013*varc)));
  const py = h*0.5 + Math.sin(t*0.017)*(amp*(0.45+0.35*Math.cos(t*0.009*varc)));
  const response = (Math.abs(px-w*0.5)+Math.abs(py-h*0.5))/Math.max(1,(w+h)*0.25);
  const stability = Math.max(0, 100 - varc*50 - Math.abs(Math.sin(t*0.01))*20);
  const rate = speed*120;
  m1.textContent = response.toFixed(2) + " {m1["unit"]}";
  m2.textContent = stability.toFixed(1) + " {m2["unit"]}";
  m3.textContent = rate.toFixed(2) + " {m3["unit"]}";
  insight.textContent = (av + bv + cvv) > 2.2 ? highMsg : lowMsg;
  x.fillStyle='#060e22'; x.fillRect(0,0,w,h);
  x.strokeStyle='rgba(125,211,252,0.12)'; for(let gy=0; gy<h; gy+=36){{x.beginPath();x.moveTo(0,gy);x.lineTo(w,gy);x.stroke();}}
  x.strokeStyle='rgba(125,211,252,0.15)'; for(let gx=0; gx<w; gx+=36){{x.beginPath();x.moveTo(gx,0);x.lineTo(gx,h);x.stroke();}}
  if(trail.checked){{ history.push([px,py]); if(history.length>220) history.shift(); x.strokeStyle='#7de0ff'; x.beginPath(); history.forEach((p,i)=> i?x.lineTo(p[0],p[1]):x.moveTo(p[0],p[1])); x.stroke(); }} else {{ history=[]; }}
  x.fillStyle='#facc15'; x.beginPath(); x.arc(w*0.5,h*0.5,9,0,Math.PI*2); x.fill();
  x.fillStyle='#60a5fa'; x.beginPath(); x.arc(px,py,7,0,Math.PI*2); x.fill();
  requestAnimationFrame(tick);
}}; requestAnimationFrame(tick); }});
</script></body></html>"""


def generate_widget(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
) -> dict[str, str]:
    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    logger.info("widget: calling LLM provider=%s model=%s", prov, model)

    html = None
    first_error = None
    raw = ""
    try:
        raw = call_llm(
            provider=prov,
            api_key=api_key,
            model=model,
            system=WIDGET_SYSTEM,
            user=_widget_user_prompt(prompt),
            temperature=0.2,
            max_tokens=6000,
            max_output_tokens=6000,
        )
        if not raw or not raw.strip():
            raise RuntimeError("LLM returned empty widget.")
        html = _extract_html(raw)
        ok, reason = _validate_widget_html(html)
        if not ok:
            logger.warning("widget: validation failed (%s), attempting repair pass", reason)
            html = _repair_widget_html(
                provider=prov,
                api_key=api_key,
                model=model,
                topic=prompt,
                prior_html=html,
                reason=reason,
            )
            ok2, reason2 = _validate_widget_html(html)
            if not ok2:
                raise RuntimeError(f"Widget failed validation after repair: {reason2}")
    except Exception as e:
        first_error = e
        logger.warning(
            "widget: first generation failed (%s), attempting final compact retry",
            e,
        )
        try:
            retry_reason = str(e)
            # Truncation failures should avoid sending huge prior HTML back; that often causes repeat truncation.
            include_prior_html = "truncated" not in retry_reason.lower()
            retry_errors: list[str] = []
            for attempt_idx in range(1):
                html = _retry_widget_html(
                    provider=prov,
                    api_key=api_key,
                    model=model,
                    topic=prompt,
                    reason=f"{retry_reason} (retry {attempt_idx + 1}/1)",
                    prior_html=(raw[:2500] if (raw and include_prior_html) else None),
                )
                ok3, reason3 = _validate_widget_html(html)
                if ok3:
                    break
                retry_errors.append(reason3)
                retry_reason = reason3
                include_prior_html = False
            else:
                raise RuntimeError(
                    "Final compact retry failed validation: " + "; ".join(retry_errors)
                )
        except Exception as e2:
            logger.warning(
                "widget: compact retry failed (%s), using prompt-conditioned fallback",
                e2,
            )
            html = _topic_fallback_widget_html(
                prompt,
                provider=prov,
                api_key=api_key,
                model=model,
            )
            ok4, reason4 = _validate_widget_html(html)
            if not ok4:
                if first_error:
                    raise RuntimeError(f"Widget fallback invalid after generation error: {first_error}") from e2
                raise RuntimeError(f"Widget fallback invalid: {reason4}") from e2

    assert html is not None
    logger.info("widget: generated %d chars of HTML", len(html))

    return {
        "status": "ok",
        "widget_html": html,
    }
