# backend/mcp/widget_logic.py
"""
Generate self-contained interactive HTML widgets for teaching concepts.
Standalone module, no LangGraph.
"""
import json
import logging
import os
import re
from html import escape

from backend.agent.llm.clients import call_llm
from backend.agent.llm.multimodal import (
    NEEDS_CLARIFICATION_MESSAGE,
    call_multimodal_llm,
    is_needs_clarification,
)
from backend.agent.llm.provider_config import (
    resolve_provider_and_key as _pick_provider_and_key,
)
from backend.agent.prompts import (
    WIDGET_EDIT_SYSTEM,
    WIDGET_FALLBACK_SPEC_SYSTEM,
    WIDGET_REPAIR_SYSTEM,
    WIDGET_SIMPLE_FALLBACK_SYSTEM,
    WIDGET_SYSTEM,
    build_widget_edit_user_prompt,
    build_widget_fallback_spec_user_prompt,
    build_widget_repair_user_prompt,
    build_widget_simple_fallback_user_prompt,
    build_widget_user_prompt,
)
from backend.utils import app_logging  # noqa: F401

logger = logging.getLogger(f"app.{__name__}")

# Output budget for a whole widget document. The retry uses the same larger cap
# the edit and repair paths already use, so this is not a new ceiling.
WIDGET_OUTPUT_TOKENS = 5000
WIDGET_RETRY_OUTPUT_TOKENS = 8000


class WidgetTruncated(RuntimeError):
    """The model's HTML stopped mid-document, i.e. it ran out of output budget."""


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
        raise WidgetTruncated("Widget script block appears truncated (missing </script>).")
    if "</body>" not in low:
        raise WidgetTruncated("Widget HTML appears truncated (missing </body>).")
    if "</html>" not in low:
        raise WidgetTruncated("Widget HTML appears truncated (missing </html>).")
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
    matches = re.findall(
        r"<(?:button|input|select|textarea)\b|\bcontenteditable\s*=|\bdraggable\s*=",
        html,
        flags=re.IGNORECASE,
    )
    return len(matches)


def _visible_text_length(html: str) -> int:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return len(re.sub(r"\s+", " ", text).strip())


def _extract_script_blocks(html: str) -> list[str]:
    return re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)


def _find_matching_brace(text: str, open_pos: int) -> int:
    """Best-effort brace matching for generated vanilla JS validation."""
    depth = 0
    quote: str | None = None
    escaped = False
    for i in range(open_pos, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"', '`'):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _function_body(script: str, name: str) -> str | None:
    m = re.search(rf"\bfunction\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", script)
    if not m:
        return None
    open_pos = script.find("{", m.start())
    close_pos = _find_matching_brace(script, open_pos)
    if close_pos < 0:
        return None
    return script[open_pos + 1 : close_pos]


def _enclosing_block_end(text: str, pos: int) -> int:
    """Return the closing brace for the block containing pos, or len(text)."""
    stack: list[int] = []
    quote: str | None = None
    escaped = False
    i = 0
    while i < min(pos, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', '`'):
            quote = ch
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            stack.pop()
        i += 1
    if not stack:
        return len(text)
    close_pos = _find_matching_brace(text, stack[-1])
    return close_pos if close_pos >= 0 else len(text)


def _same_block_has_state_declaration(text: str) -> bool:
    """Find const/let declarations while ignoring nested brace blocks."""
    visible: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False
    for ch in text:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            visible.append(" " if depth else ch)
            continue
        if ch in ("'", '"', '`'):
            quote = ch
            visible.append(ch if depth == 0 else " ")
        elif ch == "{":
            depth += 1
            visible.append(" ")
        elif ch == "}":
            depth = max(0, depth - 1)
            visible.append(" ")
        else:
            visible.append(ch if depth == 0 else " ")
    return bool(re.search(r"\b(?:const|let)\s+[A-Za-z_$][\w$]*", "".join(visible)))


def _detect_unsafe_initial_draw_order(html: str) -> str | None:
    """Catch a common generated-widget runtime bug.

    Several free models produce code like:
      function resizeCanvas(){ ... draw(); }
      resizeCanvas();
      const penguin = {...};

    The initial resize call triggers draw before state variables exist, causing
    errors like: Cannot access 'penguin' before initialization. We reject that
    during backend validation so the normal repair/fallback path can fix it
    before a teacher sees a broken widget.
    """
    for script in _extract_script_blocks(html):
        # Look for immediate calls at script initialization time. This is a
        # simple static check, not a full JS parser, but it catches the failure
        # pattern without requiring Node/browser execution in the backend.
        for call in re.finditer(r"(?:^|[;\n])\s*([A-Za-z_$][\w$]*)\s*\(\s*\)\s*;", script):
            name = call.group(1)
            if name in {"update", "draw", "render", "redraw", "animate"}:
                # Calling a drawing/update loop before later state declarations is unsafe.
                block_end = _enclosing_block_end(script, call.end())
                if _same_block_has_state_declaration(script[call.end() : block_end]):
                    return f"initial {name}() call occurs before later state declarations"
                continue
            if name.lower() not in {"fit", "resize", "resizecanvas", "sizecanvas", "initcanvas"}:
                continue
            body = _function_body(script, name)
            if not body:
                continue
            if not re.search(r"\b(draw|render|redraw|update|animate)\s*\(", body):
                continue
            block_end = _enclosing_block_end(script, call.end())
            if _same_block_has_state_declaration(script[call.end() : block_end]):
                return (
                    f"{name}() calls draw/render/update before later state variables are initialized; "
                    "move the initial call after all state declarations or make resize only size the canvas"
                )

        # Also catch the literal error pattern if the model embeds a known broken message.
        if "cannot access" in script.lower() and "before initialization" in script.lower():
            return "script contains a known before-initialization runtime error"
    return None


def _validate_widget_html(html: str) -> tuple[bool, str]:
    low = html.lower()
    if "<!doctype html" not in low and "<html" not in low:
        return False, "missing full html document structure"
    if "<script" not in low:
        return False, "missing script block"
    if "</body>" not in low or "</html>" not in low:
        return False, "incomplete html document"
    if re.search(r"<script\b[^>]*\bsrc\s*=", low):
        return False, "contains forbidden external script source"
    if "<link" in low and "stylesheet" in low:
        return False, "contains forbidden stylesheet link tag"
    if "@import" in low:
        return False, "contains forbidden CSS @import"
    if any(token in low for token in ("fetch(", "xmlhttprequest", "websocket(", "localstorage", "sessionstorage")):
        return False, "contains forbidden network or storage access"
    if _visible_text_length(html) < 24:
        return False, "missing meaningful visible teaching content"

    init_order_reason = _detect_unsafe_initial_draw_order(html)
    if init_order_reason:
        return False, init_order_reason

    generic_markers = (
        "interactive concept lab",
        "primary factor",
        "secondary factor",
        "response</span>",
        "stability</span>",
        "show motion trail",
    )
    if sum(1 for marker in generic_markers if marker in low) >= 3:
        return False, "generic fallback widget is not topic-specific"

    event_names = (
        "click",
        "pointerdown",
        "pointermove",
        "pointerup",
        "mousedown",
        "mousemove",
        "mouseup",
        "dragstart",
        "dragover",
        "drop",
        "input",
        "change",
        "submit",
        "keydown",
        "touchstart",
    )
    has_event_listener = "addeventlistener" in low and any(
        re.search(rf"[\"']{event}[\"']", low) for event in event_names
    )
    if not has_event_listener:
        return False, "missing JavaScript event listener for a learner action"

    control_count = _count_control_elements(html)
    has_direct_visual_surface = "<canvas" in low or "<svg" in low
    if control_count < 1 and not has_direct_visual_surface:
        return False, "missing a visible learner interaction surface"

    has_canvas = "<canvas" in low
    has_svg = "<svg" in low
    if has_canvas and "getcontext" not in low:
        return False, "canvas is present but no drawing context is created"

    has_dom_state_change = bool(
        re.search(
            r"\.(?:textcontent|innertext|innerhtml|classlist|style|hidden|value|checked|dataset)\b"
            r"|\b(?:setattribute|appendchild|replacechildren|removechild|insertadjacenthtml)\s*\(",
            low,
        )
    )
    has_draw_or_render = bool(
        re.search(r"\b(?:draw|render|redraw|update|plot|paint)\s*\(", low)
        or "requestanimationframe" in low
        or (has_svg and "setattribute" in low)
    )
    has_feedback_target = bool(
        re.search(
            r"(?:id|class)\s*=\s*[\"'][^\"']*(?:feedback|status|insight|result|message|notice|explanation)",
            low,
        )
        or "<output" in low
        or "aria-live" in low
    )

    if not (has_dom_state_change or has_draw_or_render or has_feedback_target):
        return False, "learner action has no visible feedback or state update"
    if has_canvas and not has_draw_or_render:
        return False, "canvas widget has no draw/render update path"

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
    fixed_raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=WIDGET_REPAIR_SYSTEM,
        user=build_widget_repair_user_prompt(
            original_title=topic,
            edit_instructions=f"Create a working educational widget about {topic}",
            prior_html=prior_html,
            reason=reason,
        ),
        temperature=0.05,
        max_tokens=5000,
        max_output_tokens=5000,
    )
    return _extract_html(fixed_raw)


def _generate_simple_fallback_html(
    *,
    provider: str,
    api_key: str,
    model: str | None,
    topic: str,
    reason: str,
) -> str:
    """Generate a fresh, smaller widget without reusing failed HTML."""
    raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=WIDGET_SIMPLE_FALLBACK_SYSTEM,
        user=build_widget_simple_fallback_user_prompt(topic=topic, reason=reason),
        temperature=0.05,
        max_tokens=4200,
        max_output_tokens=4200,
    )
    if not raw or not raw.strip():
        raise RuntimeError("LLM returned empty simple fallback widget.")
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
    reason: str | None = None,
) -> dict:
    """Ask the model for a compact topic-specific fallback spec, not HTML.

    This is intentionally used only after custom HTML + repair/compact retry fail.
    It keeps the normal path creative, but gives us a reliable non-generic fallback
    when a free model truncates a full HTML document.
    """
    raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=WIDGET_FALLBACK_SPEC_SYSTEM,
        user=build_widget_fallback_spec_user_prompt(topic=topic, reason=reason),
        temperature=0.0,
        max_tokens=900,
        max_output_tokens=900,
    )
    spec = _extract_first_json_object(raw) or {}
    return spec if isinstance(spec, dict) else {}


def _topic_words(topic: str) -> str:
    cleaned = re.sub(r"\s+", " ", (topic or "").strip())
    cleaned = re.sub(r"^(explain|show|teach|create|make|build)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned[:90] or "this concept"


def _keyword_spec(topic: str) -> dict:
    """Small local fallback if the JSON spec call fails too."""
    t = _topic_words(topic)
    low = t.lower()
    if "penguin" in low:
        return {
            "title": "Penguin Warmth Explorer",
            "concept_line": "Explore how huddling, insulation, and cold water affect a penguin's heat loss.",
            "visual_items": ["Penguin", "Feathers", "Huddle", "Cold water", "Heat loss"],
            "controls": [
                {"label": "Water temperature", "min": -20, "max": 10, "step": 1, "value": -5, "low_label": "icy", "high_label": "less cold"},
                {"label": "Huddle size", "min": 1, "max": 20, "step": 1, "value": 8, "low_label": "alone", "high_label": "large group"},
                {"label": "Feather insulation", "min": 0, "max": 100, "step": 1, "value": 65, "low_label": "thin", "high_label": "dense/oily"},
            ],
            "metrics": [
                {"label": "Heat loss", "unit": "%"},
                {"label": "Warmth score", "unit": "%"},
                {"label": "Energy saved", "unit": "%"},
            ],
            "try_this": "Make the water colder, then increase huddle size. What changes?",
            "notice": "Penguins reduce heat loss with dense feathers and by sharing warmth in groups.",
            "low_insight": "Cold water and small groups increase heat loss.",
            "high_insight": "Better insulation and larger huddles help penguins stay warmer.",
        }
    return {
        "title": f"{t.title()} Explorer",
        "concept_line": f"Adjust variables and watch how they change {t}.",
        "visual_items": [t.title(), "Variable A", "Variable B", "Result"],
        "controls": [
            {"label": f"{t.title()} amount", "min": 0, "max": 100, "step": 1, "value": 50, "low_label": "less", "high_label": "more"},
            {"label": "Environment level", "min": 0, "max": 100, "step": 1, "value": 45, "low_label": "low", "high_label": "high"},
            {"label": "Time or scale", "min": 0, "max": 100, "step": 1, "value": 60, "low_label": "small", "high_label": "large"},
        ],
        "metrics": [
            {"label": f"{t.title()} effect", "unit": "%"},
            {"label": "Pattern strength", "unit": "%"},
            {"label": "Change rate", "unit": "%"},
        ],
        "try_this": "Move one slider at a time. Which variable changes the result most?",
        "notice": "Changing one variable at a time helps reveal cause and effect.",
        "low_insight": f"Lower settings show a weaker version of {t}.",
        "high_insight": f"Higher settings make the pattern in {t} easier to see.",
    }


def _clean_label(value: object, fallback: str, limit: int = 42) -> str:
    text = re.sub(r"\s+", " ", str(value or fallback)).strip()
    banned = {"primary factor", "secondary factor", "response", "stability", "concept lab", "interactive concept lab"}
    if text.lower() in banned:
        text = fallback
    return text[:limit]


def _num(v: object, fb: float) -> float:
    try:
        return float(v)
    except Exception:
        return fb


def _safe_spec(topic: str, spec: dict | None) -> dict:
    fallback = _keyword_spec(topic)
    data = spec if isinstance(spec, dict) else {}
    title = _clean_label(data.get("title"), fallback["title"], 80)
    concept_line = _clean_label(data.get("concept_line"), fallback["concept_line"], 180)

    raw_items = data.get("visual_items") if isinstance(data.get("visual_items"), list) else fallback["visual_items"]
    visual_items = [_clean_label(item, fallback["visual_items"][0], 24) for item in raw_items[:5]]
    if len(visual_items) < 3:
        visual_items = fallback["visual_items"][:]

    raw_controls = data.get("controls") if isinstance(data.get("controls"), list) else fallback["controls"]
    raw_metrics = data.get("metrics") if isinstance(data.get("metrics"), list) else fallback["metrics"]
    while len(raw_controls) < 3:
        raw_controls.append(fallback["controls"][len(raw_controls)])
    while len(raw_metrics) < 3:
        raw_metrics.append(fallback["metrics"][len(raw_metrics)])

    controls = []
    for i in range(3):
        src = raw_controls[i] if isinstance(raw_controls[i], dict) else {}
        fb = fallback["controls"][i]
        mn = _num(src.get("min"), fb["min"])
        mx = _num(src.get("max"), fb["max"])
        if mx <= mn:
            mn, mx = fb["min"], fb["max"]
        step = abs(_num(src.get("step"), fb["step"])) or fb["step"]
        value = min(max(_num(src.get("value"), fb["value"]), mn), mx)
        controls.append({
            "label": _clean_label(src.get("label"), fb["label"], 36),
            "min": mn,
            "max": mx,
            "step": step,
            "value": value,
            "low_label": _clean_label(src.get("low_label"), fb.get("low_label", "low"), 24),
            "high_label": _clean_label(src.get("high_label"), fb.get("high_label", "high"), 24),
        })

    metrics = []
    for i in range(3):
        src = raw_metrics[i] if isinstance(raw_metrics[i], dict) else {}
        fb = fallback["metrics"][i]
        metrics.append({
            "label": _clean_label(src.get("label"), fb["label"], 34),
            "unit": _clean_label(src.get("unit"), fb.get("unit", ""), 10),
        })

    return {
        "title": title,
        "concept_line": concept_line,
        "visual_items": visual_items,
        "controls": controls,
        "metrics": metrics,
        "try_this": _clean_label(data.get("try_this"), fallback["try_this"], 150),
        "notice": _clean_label(data.get("notice"), fallback["notice"], 150),
        "low_insight": _clean_label(data.get("low_insight"), fallback["low_insight"], 150),
        "high_insight": _clean_label(data.get("high_insight"), fallback["high_insight"], 150),
    }


def _hanoi_fallback_widget_html(topic: str) -> str:
    title = "Towers of Hanoi Practice"
    return """<!DOCTYPE html>
<html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"><title>Towers of Hanoi Practice</title>
<style>
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#09111f;color:#eaf2ff}.wrapper{display:grid;grid-template-columns:2fr 1fr;min-height:100vh}.viz-col{position:relative;border-right:1px solid #27476f}canvas{width:100%;height:100%;display:block}.panel-col{padding:16px;background:#0f1d35}.panel-title{margin:0 0 6px}.concept-line{color:#c7d8ef;font-size:14px}.section-label{margin-top:14px;font-size:12px;letter-spacing:.08em;color:#9ac5ff;font-weight:800}.row{display:flex;justify-content:space-between;margin:7px 0}.row b{color:#7dd3fc}button,select{width:100%;margin-top:8px;padding:9px;border:0;border-radius:9px;background:#2563eb;color:white;font-weight:700}select{background:#10274a;border:1px solid #315985}.insight-box,.try-box{margin-top:10px;padding:10px;border:1px solid #345b88;border-radius:10px;background:#102445;font-size:13px;color:#d7e8ff}.try-box{background:#14213d;color:#bae6fd}
</style></head><body><div class=\"wrapper\"><div class=\"viz-col\" id=\"viz-col\"><canvas id=\"sim-canvas\"></canvas></div><div class=\"panel-col\"><h2 class=\"panel-title\">Towers of Hanoi Practice</h2><p class=\"concept-line\">Move one top disk at a time. A larger disk can never sit on a smaller disk.</p><div class=\"section-label\">LIVE DATA</div><div class=\"row\"><span>Moves made</span><b id=\"moves\">0</b></div><div class=\"row\"><span>Minimum moves</span><b id=\"minimum\">7</b></div><div class=\"row\"><span>Selected peg</span><b id=\"selected\">none</b></div><div class=\"section-label\">CONTROLS</div><label>Disks<select id=\"diskCount\"><option value=\"3\">3 disks</option><option value=\"4\">4 disks</option><option value=\"5\">5 disks</option></select></label><button id=\"reset\">Reset puzzle</button><button id=\"hint\">Hint</button><div class=\"try-box\">Try this: solve 3 disks first, then switch to 4. What happens to the minimum moves?</div><div class=\"insight-box\" id=\"insight\">Click a peg to pick up its top disk, then click another peg to move it.</div></div></div><script>
window.addEventListener('DOMContentLoaded',()=>{const viz=document.getElementById('viz-col'),canvas=document.getElementById('sim-canvas'),ctx=canvas.getContext('2d'),movesEl=document.getElementById('moves'),minEl=document.getElementById('minimum'),selEl=document.getElementById('selected'),insight=document.getElementById('insight'),diskCount=document.getElementById('diskCount'),resetBtn=document.getElementById('reset'),hintBtn=document.getElementById('hint');let n=3,pegs=[],selected=null,moves=0;function fit(){canvas.width=viz.clientWidth;canvas.height=viz.clientHeight;draw()}window.addEventListener('resize',fit);function minMoves(){return Math.pow(2,n)-1}function reset(){n=Number(diskCount.value);pegs=[[],[],[]];for(let d=n;d>=1;d--)pegs[0].push(d);selected=null;moves=0;insight.textContent='Click a peg to pick up its top disk, then click another peg to move it.';update();draw()}function update(){movesEl.textContent=String(moves);minEl.textContent=String(minMoves());selEl.textContent=selected==null?'none':String(selected+1)}function top(i){return pegs[i][pegs[i].length-1]}function pegAt(x){return Math.max(0,Math.min(2,Math.floor(x/(canvas.width/3))))}function handlePeg(i){if(selected==null){if(!pegs[i].length){insight.textContent='That peg is empty. Pick a peg with a top disk.';return}selected=i;insight.textContent='Selected peg '+(i+1)+'. Now choose a target peg.';update();draw();return}if(i===selected){selected=null;insight.textContent='Selection cleared.';update();draw();return}const disk=top(selected),target=top(i);if(target&&target<disk){insight.textContent='Illegal move: a larger disk cannot go on a smaller disk.';selected=null;update();draw();return}pegs[selected].pop();pegs[i].push(disk);moves++;selected=null;if(pegs[2].length===n){insight.textContent='Solved! Minimum possible was '+minMoves()+' moves. Can you match it?'}else{insight.textContent='Legal move. Keep moving the smallest blocking stack first.'}update();draw()}canvas.addEventListener('click',e=>{const r=canvas.getBoundingClientRect();handlePeg(pegAt(e.clientX-r.left))});diskCount.addEventListener('change',reset);resetBtn.addEventListener('click',reset);hintBtn.addEventListener('click',()=>{insight.textContent='Hint: move the top '+(n-1)+' disks out of the way, move the largest disk, then rebuild the stack.'});function draw(){const w=canvas.width,h=canvas.height;ctx.fillStyle='#071020';ctx.fillRect(0,0,w,h);ctx.fillStyle='#dbeafe';ctx.font='bold 22px system-ui';ctx.fillText('Move the tower to peg 3',24,34);const baseY=h*0.78,pegH=h*0.45;for(let i=0;i<3;i++){const x=w*(i+0.5)/3;ctx.strokeStyle=selected===i?'#facc15':'#93c5fd';ctx.lineWidth=8;ctx.beginPath();ctx.moveTo(x,baseY);ctx.lineTo(x,baseY-pegH);ctx.stroke();ctx.fillStyle='#cbd5e1';ctx.font='14px system-ui';ctx.textAlign='center';ctx.fillText('Peg '+(i+1),x,baseY+28);pegs[i].forEach((disk,idx)=>{const maxW=w/3*0.72,minW=w/3*0.30,dw=minW+(disk-1)*(maxW-minW)/Math.max(1,n-1),dy=baseY-18-idx*24;ctx.fillStyle=['#60a5fa','#34d399','#fbbf24','#f472b6','#a78bfa'][disk-1]||'#7dd3fc';ctx.beginPath();ctx.roundRect(x-dw/2,dy,dw,20,7);ctx.fill();ctx.fillStyle='#08111f';ctx.font='bold 12px system-ui';ctx.fillText(String(disk),x,dy+14)})}ctx.textAlign='left';requestAnimationFrame(draw)}fit();reset()});
</script></body></html>"""


def _topic_fallback_widget_html(
    topic: str,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    reason: str | None = None,
) -> str:
    low = (topic or "").lower()
    if "hanoi" in low or "tower of" in low or "towers of" in low:
        return _hanoi_fallback_widget_html(topic)

    derived = {}
    if provider and api_key:
        try:
            derived = _derive_prompt_spec(
                provider=provider,
                api_key=api_key,
                model=model,
                topic=topic,
                reason=reason,
            )
        except Exception as exc:
            logger.warning("widget: JSON fallback spec generation failed (%s); using local topic spec", exc)
            derived = {}

    s = _safe_spec(topic, derived)
    spec_json = json.dumps(s, ensure_ascii=False)
    title = escape(s["title"])
    concept_line = escape(s["concept_line"])
    c1, c2, c3 = s["controls"]
    m1, m2, m3 = s["metrics"]
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#08111f;color:#eaf2ff}}.wrapper{{display:grid;grid-template-columns:2fr 1fr;min-height:100vh}}.viz-col{{position:relative;border-right:1px solid #27476f}}#sim-canvas{{width:100%;height:100%;display:block}}.panel-col{{padding:16px;background:#0f1d35;overflow:auto}}.panel-title{{margin:0 0 6px}}.concept-line{{color:#c7d8ef;font-size:14px;line-height:1.35}}.section-label{{margin-top:14px;font-size:12px;letter-spacing:.08em;color:#9ac5ff;font-weight:800}}.row{{display:flex;justify-content:space-between;gap:12px;margin:7px 0}}.row b{{color:#7dd3fc;text-align:right}}label{{display:block;margin:10px 0;color:#dbeafe;font-size:13px}}input[type=range]{{width:100%}}.scale{{display:flex;justify-content:space-between;font-size:11px;color:#9fb7da}}button{{width:100%;margin-top:8px;padding:9px;border:0;border-radius:9px;background:#2563eb;color:white;font-weight:700}}.insight-box,.try-box{{margin-top:10px;padding:10px;border:1px solid #345b88;border-radius:10px;background:#102445;font-size:13px;line-height:1.35;color:#d7e8ff}}.try-box{{background:#14213d;color:#bae6fd}}
</style></head><body><div class="wrapper"><div class="viz-col" id="viz-col"><canvas id="sim-canvas"></canvas></div><div class="panel-col"><h2 class="panel-title">{title}</h2><p class="concept-line">{concept_line}</p><div class="section-label">LIVE DATA</div><div class="row"><span>{escape(m1["label"])}</span><b id="m1">0 {escape(m1["unit"])}</b></div><div class="row"><span>{escape(m2["label"])}</span><b id="m2">0 {escape(m2["unit"])}</b></div><div class="row"><span>{escape(m3["label"])}</span><b id="m3">0 {escape(m3["unit"])}</b></div><div class="section-label">CONTROLS</div><label>{escape(c1["label"])}<input id="a" type="range" min="{c1["min"]}" max="{c1["max"]}" step="{c1["step"]}" value="{c1["value"]}"><span class="scale"><em>{escape(c1["low_label"])}</em><em>{escape(c1["high_label"])}</em></span></label><label>{escape(c2["label"])}<input id="b" type="range" min="{c2["min"]}" max="{c2["max"]}" step="{c2["step"]}" value="{c2["value"]}"><span class="scale"><em>{escape(c2["low_label"])}</em><em>{escape(c2["high_label"])}</em></span></label><label>{escape(c3["label"])}<input id="c" type="range" min="{c3["min"]}" max="{c3["max"]}" step="{c3["step"]}" value="{c3["value"]}"><span class="scale"><em>{escape(c3["low_label"])}</em><em>{escape(c3["high_label"])}</em></span></label><button id="reset">Reset</button><div class="try-box">Try this: {escape(s["try_this"])}</div><div class="insight-box" id="insight">{escape(s["notice"])}</div></div></div><script>
window.addEventListener('DOMContentLoaded',()=>{{
const SPEC={spec_json};
const viz=document.getElementById('viz-col'),cv=document.getElementById('sim-canvas'),ctx=cv.getContext('2d');
const a=document.getElementById('a'),b=document.getElementById('b'),c=document.getElementById('c'),reset=document.getElementById('reset'),insight=document.getElementById('insight');
const m1=document.getElementById('m1'),m2=document.getElementById('m2'),m3=document.getElementById('m3');
let t=0,pulse=0,focus=0;function fit(){{cv.width=viz.clientWidth;cv.height=viz.clientHeight;}}fit();window.addEventListener('resize',fit);
function norm(el){{const min=Number(el.min),max=Number(el.max);return (Number(el.value)-min)/Math.max(1e-6,max-min);}}
function scoreVals(){{const vals=[norm(a),norm(b),norm(c)];const score=Math.max(0,Math.min(100,(vals[0]*.38+vals[1]*.34+vals[2]*.28)*100));const balance=Math.max(0,100-Math.abs(vals[0]-vals[1])*65-Math.abs(vals[1]-vals[2])*35);const change=Math.max(0,Math.min(100,(vals[2]*.55+Math.abs(vals[0]-vals[1])*.45)*100));return [score,balance,change,vals];}}
function update(){{const [score,balance,change]=scoreVals();m1.textContent=score.toFixed(0)+' '+(SPEC.metrics[0].unit||'');m2.textContent=balance.toFixed(0)+' '+(SPEC.metrics[1].unit||'');m3.textContent=change.toFixed(0)+' '+(SPEC.metrics[2].unit||'');insight.textContent=score>62?SPEC.high_insight:score<38?SPEC.low_insight:SPEC.notice;}}
[a,b,c].forEach(el=>el.addEventListener('input',()=>{{pulse=1;update();}}));reset.addEventListener('click',()=>{{[a,b,c].forEach((el,i)=>el.value=SPEC.controls[i].value);focus=0;pulse=1;update();}});cv.addEventListener('click',e=>{{const r=cv.getBoundingClientRect();focus=(Math.floor((e.clientX-r.left)/(cv.width/Math.max(1,SPEC.visual_items.length)))+1)%SPEC.visual_items.length;insight.textContent='Focus: '+SPEC.visual_items[focus]+'. Now adjust one control and watch the change.';pulse=1;}});
function roundRect(x,y,w,h,r){{ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}}
function draw(){{const w=cv.width,h=cv.height;const [score,balance,change,vals]=scoreVals();t+=0.018;pulse*=0.94;ctx.fillStyle='#071020';ctx.fillRect(0,0,w,h);ctx.strokeStyle='rgba(147,197,253,.12)';for(let x=0;x<w;x+=42){{ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}}for(let y=0;y<h;y+=42){{ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}}ctx.fillStyle='#dbeafe';ctx.font='bold 22px system-ui';ctx.textAlign='left';ctx.fillText(SPEC.title,24,36);ctx.font='14px system-ui';ctx.fillStyle='#9fb7da';ctx.fillText('Click a label to focus it, or adjust the sliders to test cause and effect.',24,60);const cx=w*.5,cy=h*.48;ctx.strokeStyle='rgba(125,211,252,.35)';ctx.lineWidth=3;ctx.beginPath();ctx.arc(cx,cy,Math.min(w,h)*(.18+.08*vals[0]+pulse*.02),0,Math.PI*2);ctx.stroke();const items=SPEC.visual_items.slice(0,5);items.forEach((name,i)=>{{const ang=-Math.PI/2+i*(Math.PI*2/items.length)+t*.12;const rad=Math.min(w,h)*(.24+.04*vals[1]);const x=cx+Math.cos(ang)*rad,y=cy+Math.sin(ang)*rad;ctx.fillStyle=i===focus?'#facc15':'#60a5fa';ctx.beginPath();ctx.arc(x,y,18+vals[2]*10+(i===focus?5:0),0,Math.PI*2);ctx.fill();ctx.fillStyle='#eaf2ff';ctx.font='12px system-ui';ctx.textAlign='center';ctx.fillText(name,x,y+34);ctx.strokeStyle='rgba(186,230,253,.28)';ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(x,y);ctx.stroke();}});ctx.fillStyle='#34d399';roundRect(cx-70,cy-32,140,64,16);ctx.fill();ctx.fillStyle='#082032';ctx.font='bold 15px system-ui';ctx.textAlign='center';ctx.fillText(Math.round(score)+'%',cx,cy-2);ctx.font='12px system-ui';ctx.fillText(SPEC.metrics[0].label,cx,cy+17);const barY=h-92;SPEC.controls.forEach((ctl,i)=>{{const x=36+i*(w-72)/3,bw=(w-120)/3;ctx.fillStyle='rgba(148,163,184,.22)';roundRect(x,barY,bw,16,8);ctx.fill();ctx.fillStyle=['#7dd3fc','#a7f3d0','#fde68a'][i];roundRect(x,barY,bw*vals[i],16,8);ctx.fill();ctx.fillStyle='#cbd5e1';ctx.font='12px system-ui';ctx.textAlign='left';ctx.fillText(ctl.label,x,barY-9);}});requestAnimationFrame(draw);}}update();requestAnimationFrame(draw);
}});
</script></body></html>'''


def _repair_edited_widget_html(
    *,
    provider: str,
    api_key: str,
    model: str | None,
    original_title: str | None,
    edit_instructions: str,
    prior_html: str,
    reason: str,
) -> str:
    repair_system = WIDGET_REPAIR_SYSTEM
    repair_user = build_widget_repair_user_prompt(
        original_title=original_title,
        edit_instructions=edit_instructions,
        prior_html=prior_html,
        reason=reason,
    )
    fixed_raw = call_llm(
        provider=provider,
        api_key=api_key,
        model=model,
        system=repair_system,
        user=repair_user,
        temperature=0.1,
        max_tokens=8000,
        max_output_tokens=8000,
    )
    return _extract_html(fixed_raw)


def edit_widget(
    *,
    original_html: str,
    edit_instructions: str,
    original_title: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
) -> dict[str, str]:
    """Revise an existing widget using its actual HTML source.

    This is intentionally different from generate_widget(). It avoids rebuilding
    from only the visible text, which can produce a totally different widget.
    """
    if not original_html or not original_html.strip():
        raise RuntimeError("original_html is required")
    if not edit_instructions or not edit_instructions.strip():
        raise RuntimeError("edit_instructions is required")

    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    logger.info("widget edit: calling LLM provider=%s model=%s", prov, model)

    raw = call_llm(
        provider=prov,
        api_key=api_key,
        model=model,
        system=WIDGET_EDIT_SYSTEM,
        user=build_widget_edit_user_prompt(
            original_html=original_html,
            edit_instructions=edit_instructions,
            original_title=original_title,
        ),
        temperature=0.1,
        max_tokens=8000,
        max_output_tokens=8000,
    )
    if not raw or not raw.strip():
        raise RuntimeError("LLM returned empty edited widget.")

    html = _extract_html(raw)
    ok, reason = _validate_widget_html(html)
    if not ok:
        logger.warning("widget edit: validation failed (%s), attempting repair", reason)
        html = _repair_edited_widget_html(
            provider=prov,
            api_key=api_key,
            model=model,
            original_title=original_title,
            edit_instructions=edit_instructions,
            prior_html=html,
            reason=reason,
        )
        ok2, reason2 = _validate_widget_html(html)
        if not ok2:
            raise RuntimeError(f"Edited widget failed validation after repair: {reason2}")

    logger.info("widget edit: generated %d chars of HTML", len(html))
    return {"status": "ok", "widget_html": html}

def generate_widget(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    learner_prompt: str | None = None,
    images: list[object] | None = None,
    default_image_prompt_used: bool = False,
) -> dict[str, object]:
    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    logger.info("widget: calling LLM provider=%s model=%s", prov, model)

    html: str | None = None
    generation_path = "primary"
    first_error: Exception | None = None
    generation_diagnostics: dict[str, object] | None = None

    def _call_primary(output_budget: int):
        return call_multimodal_llm(
            provider=prov,
            api_key=api_key,
            model=model,
            system=WIDGET_SYSTEM,
            user=build_widget_user_prompt(prompt),
            learner_prompt=(learner_prompt if learner_prompt is not None else prompt),
            images=images,
            provider_keys=provider_keys,
            default_image_prompt_used=default_image_prompt_used,
            temperature=0.15,
            max_tokens=output_budget,
            max_output_tokens=output_budget,
        )

    try:
        llm_result = _call_primary(WIDGET_OUTPUT_TOKENS)
        raw = llm_result.text
        generation_diagnostics = llm_result.metadata.to_dict()
        if is_needs_clarification(raw):
            return {
                "ok": False,
                "status": "needs_clarification",
                "error": "needs_clarification",
                "message": NEEDS_CLARIFICATION_MESSAGE,
                "widget_html": None,
                "generation_diagnostics": generation_diagnostics,
            }
        if not raw or not raw.strip():
            raise RuntimeError("LLM returned empty widget.")

        try:
            html = _extract_html(raw)
        except WidgetTruncated as truncated:
            # Nothing is wrong with the request; the document did not fit. Retry
            # once with more room before treating this as a failure.
            logger.warning(
                "widget: output truncated at %d tokens (%s); retrying at %d",
                WIDGET_OUTPUT_TOKENS,
                truncated,
                WIDGET_RETRY_OUTPUT_TOKENS,
            )
            llm_result = _call_primary(WIDGET_RETRY_OUTPUT_TOKENS)
            raw = llm_result.text
            generation_diagnostics = llm_result.metadata.to_dict()
            if not raw or not raw.strip():
                raise RuntimeError("LLM returned empty widget on the retry.") from truncated
            html = _extract_html(raw)
            generation_path = "retried_larger_budget"

        ok, reason = _validate_widget_html(html)
        if not ok:
            logger.warning("widget: primary validation failed (%s); attempting targeted repair", reason)
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
                raise RuntimeError(f"Widget failed validation after targeted repair: {reason2}")
            generation_path = "repaired_primary"

    except Exception as exc:
        # Never let an image-backed request silently degrade into a prompt-only fallback.
        # Once images are involved, a failed primary/repair path should surface as a real
        # generation failure rather than producing a widget that may ignore the source image.
        if images:
            raise
        first_error = exc
        logger.warning(
            "widget: primary path failed (%s); generating a fresh simple fallback",
            exc,
        )
        try:
            html = _generate_simple_fallback_html(
                provider=prov,
                api_key=api_key,
                model=model,
                topic=prompt,
                reason=str(exc),
            )
            ok3, reason3 = _validate_widget_html(html)
            if not ok3:
                raise RuntimeError(f"Simple fallback failed validation: {reason3}")
            generation_path = "simple_llm_fallback"

        except Exception as fallback_exc:
            logger.warning(
                "widget: simple fallback failed (%s); using emergency topic fallback",
                fallback_exc,
            )
            if os.environ.get("UPCURVED_WIDGET_DISABLE_JSON_FALLBACK", "0").strip().lower() in {
                "1",
                "true",
                "yes",
            }:
                raise RuntimeError(
                    "Widget generation failed after the primary and simple fallback attempts. "
                    "Try again or switch models."
                ) from fallback_exc

            html = _topic_fallback_widget_html(
                prompt,
                provider=prov,
                api_key=api_key,
                model=model,
                reason=str(fallback_exc),
            )
            ok4, reason4 = _validate_widget_html(html)
            if not ok4:
                detail = str(first_error) if first_error else reason4
                raise RuntimeError(
                    f"Emergency widget fallback invalid after generation error: {detail}"
                ) from fallback_exc
            generation_path = "emergency_spec_fallback"

    assert html is not None
    logger.info(
        "widget: generated %d chars of HTML path=%s",
        len(html),
        generation_path,
    )

    return {
        "status": "ok",
        "widget_html": html,
        "generation_path": generation_path,
        "generation_diagnostics": generation_diagnostics,
    }

