import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any

from backend.agent.llm.clients import call_llm
from backend.runner.job_runner import STORAGE, to_static_url

logger = logging.getLogger(f"app.{__name__}")

THEME_PRESETS: dict[str, dict[str, str]] = {
    "space": {
        "bg0": "#040b2a",
        "bg1": "#0b1e4b",
        "panel": "rgba(10,18,44,0.72)",
        "accent": "#70d7ff",
        "glow": "#79a6ff",
    },
    "jungle": {
        "bg0": "#0b2b1b",
        "bg1": "#164d2f",
        "panel": "rgba(10,40,22,0.74)",
        "accent": "#9df27c",
        "glow": "#55d86b",
    },
    "ocean": {
        "bg0": "#06243b",
        "bg1": "#0a4868",
        "panel": "rgba(4,34,56,0.76)",
        "accent": "#80e6ff",
        "glow": "#53c9ff",
    },
    "city_lab": {
        "bg0": "#111a2f",
        "bg1": "#20345d",
        "panel": "rgba(18,26,48,0.76)",
        "accent": "#b7c8ff",
        "glow": "#8bb0ff",
    },
    "sunset_farm": {
        "bg0": "#3a1c2a",
        "bg1": "#f08c6b",
        "panel": "rgba(38,18,30,0.74)",
        "accent": "#ffd166",
        "glow": "#ff9f7a",
    },
    "meadow": {
        "bg0": "#1f3c2a",
        "bg1": "#6fcf97",
        "panel": "rgba(18,38,26,0.74)",
        "accent": "#c5f277",
        "glow": "#7ee081",
    },
}

HOST_PRESETS: dict[str, dict[str, str]] = {
    "scientist": {
        "kind": "scientist",
        "label": "Scientist Guide",
        "body": "#f2c9a2",
        "accent": "#4f79ff",
        "outfit": "#f7fbff",
    },
    "friendly_robot": {
        "kind": "robot",
        "label": "Robot Guide",
        "body": "#9ab7e9",
        "accent": "#6cf0ff",
        "outfit": "#cfe3ff",
    },
    "animal_guide": {
        "kind": "animal",
        "label": "Animal Guide",
        "body": "#d8c8a8",
        "accent": "#8b6b43",
        "outfit": "#5b4631",
    },
    "explorer": {
        "kind": "explorer",
        "label": "Explorer Guide",
        "body": "#f2c9a2",
        "accent": "#f59e0b",
        "outfit": "#1f2937",
    },
    "artist": {
        "kind": "artist",
        "label": "Artist Guide",
        "body": "#f1c6a8",
        "accent": "#ec4899",
        "outfit": "#fdf2f8",
    },
    "athlete": {
        "kind": "athlete",
        "label": "Athlete Guide",
        "body": "#f0c7a0",
        "accent": "#22c55e",
        "outfit": "#0f172a",
    },
}

DRAW_JS_SYSTEM = """Return ONLY a JavaScript function body. No HTML, no markdown, no explanation.
Function signature: (x, w, h, dt, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar, drawCharacterTemplate)
where x=CanvasRenderingContext2D, w=width, h=height, dt=elapsed seconds.

You have these helper functions available. Call them directly, do not redefine them:

drawCharacter(x, cx, cy, scale, headColor, bodyColor, eyeColor, mouthUp, bobAmt)
    Draws a rounded character: head, eyes, mouth, rounded torso, curved arms, hands, legs, shoes.
    cx,cy = center bottom of character. scale = 1.0 normal. bobAmt = Math.sin(dt*2)*6 for walking.

drawCloud(x, cx, cy, w)
    Draws a fluffy white cloud at cx,cy with approximate width w.

drawGround(x, w, h, groundY, grassColor, dirtColor)
    Draws a ground strip at groundY with grass on top.

drawSpeechBubble(x, cx, cy, text, fontSize)
    Draws a white rounded speech bubble with dark text and a pointer triangle below.
    This is the ONLY way to display text in the scene. Do NOT use fillText or strokeText directly.

drawStar(x, cx, cy, r, color)
    Draws a 5-point star at cx,cy with radius r.

drawCharacterTemplate(x, cx, cy, scale, variant, bobAmt)
    Draws a prebuilt character variant using fixed templates.

Scene structure to follow:
1. Background: sky gradient or theme color, ground strip at h*0.65
2. 2-3 characters placed at different x positions, y = groundY
3. At least 1 prop (object, sign, tree, building) relevant to the scene
4. Exactly 1 drawSpeechBubble call with a short lesson phrase (max 8 words) placed above the main character
5. Animate using: bob = Math.sin(dt*2)*6, swing = Math.sin(dt*3)*0.2
6. Use drawCharacterTemplate for all people/animals/robots (do not draw custom bodies)

Constraints:
- All x/y coordinates relative to w and h
- No hardcoded pixel values above 50
- Do not clear canvas, do not call requestAnimationFrame
- Keep under 50 lines
- ALL scene text must go through drawSpeechBubble ONLY — never call fillText or strokeText directly
- Do NOT draw heading bars, caption bars, or any text overlay rectangles
- Speech bubble text must be short (max 8 words) and placed above the main character"""


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


def _story_prompt(topic: str, host_character: str | None = None, theme: str | None = None) -> str:
    host_options = ", ".join(sorted(HOST_PRESETS.keys()))
    theme_options = ", ".join(sorted(THEME_PRESETS.keys()))
    host_line = f"Main character preference: {host_character}\n" if host_character else ""
    theme_line = f"Visual theme preference: {theme}\n" if theme else ""
    return (
        f"Educational story for children about: {topic}\n"
        f"Available main characters: {host_options}\n"
        f"Available visual themes: {theme_options}\n"
        f"{host_line}"
        f"{theme_line}"
        "Return ONLY valid JSON, no markdown.\n"
        '{"title":"...","characters":["..."],"moral":"...","conclusion":"...",'
        '"scenes":[{"heading":"...","lesson":"1-2 sentences","caption":"short narrator line",'
        '"visual":"specific drawable scene description","duration_sec":10}]}\n'
        "Rules: exactly 6 scenes, each exactly 10 seconds, total = 60 seconds. "
        "Simple vocabulary. Each scene is an animated storyboard with characters and objects moving. "
        "Make visual descriptions specific and drawable: "
        "name characters, objects, actions, and colors explicitly. "
        "If the topic includes a named character, use that name in the title, characters list, and scene visuals."
    )


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise RuntimeError("Story model returned non-JSON output.")
        return json.loads(m.group(0))


def _normalize_story_plan(plan: dict[str, Any], topic: str) -> dict[str, Any]:
    title = str(plan.get("title") or f"{topic} Story").strip()[:80]
    characters_in = plan.get("characters")
    characters: list[str] = []
    if isinstance(characters_in, list):
        for item in characters_in[:5]:
            txt = str(item or "").strip()
            if txt:
                characters.append(txt[:40])
    moral = str(plan.get("moral") or "").strip()[:220]
    conclusion = str(plan.get("conclusion") or "").strip()[:220]
    scenes_in = plan.get("scenes")
    if not isinstance(scenes_in, list):
        scenes_in = []

    scenes: list[dict[str, Any]] = []
    for i, s in enumerate(scenes_in[:7], start=1):
        if not isinstance(s, dict):
            continue
        heading = str(s.get("heading") or f"Scene {i}").strip()[:60]
        lesson = str(s.get("lesson") or "").strip()
        caption = str(s.get("caption") or lesson).strip()
        visual = str(s.get("visual") or "").strip()
        duration = s.get("duration_sec", 7)
        try:
            duration = int(duration)
        except Exception:
            duration = 7
        duration = max(5, min(12, duration))
        if not lesson:
            continue
        scenes.append(
            {
                "heading": heading,
                "lesson": lesson,
                "caption": caption,
                "visual": visual,
                "duration_sec": duration,
            }
        )

    if not scenes:
        scenes = [
            {
                "heading": "Let us explore",
                "lesson": f"Today we learn {topic} in a simple story.",
                "caption": f"Welcome! We are exploring {topic}.",
                "visual": "Friendly character points at colorful objects.",
                "duration_sec": 7,
            },
            {
                "heading": "The big idea",
                "lesson": f"{topic} helps us understand how things work in daily life.",
                "caption": f"The big idea: {topic} appears in daily life.",
                "visual": "Objects move with arrows and labels.",
                "duration_sec": 7,
            },
            {
                "heading": "Try it",
                "lesson": f"Imagine one example of {topic} around you and explain it in your own words.",
                "caption": "Can you find one example around you?",
                "visual": "Child character thinks with a light bulb icon.",
                "duration_sec": 7,
            },
        ]

    total = sum(int(s["duration_sec"]) for s in scenes)
    if total < 40:
        # Stretch slightly so it feels like a real story video.
        deficit = 40 - total
        for s in scenes:
            if deficit <= 0:
                break
            bump = min(2, deficit)
            s["duration_sec"] = min(12, int(s["duration_sec"]) + bump)
            deficit -= bump

    if not characters:
        characters = ["friendly guide"]
    if not moral:
        moral = f"Learning {topic} helps us make better choices."
    if not conclusion:
        conclusion = f"Great job exploring {topic}! Keep asking curious questions."
    return {
        "title": title,
        "audience": "children",
        "characters": characters,
        "moral": moral,
        "conclusion": conclusion,
        "scenes": scenes,
    }


def _find_ffmpeg() -> str:
    for key in ("UPCURVED_FFMPEG_PATH", "IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"):
        val = (os.getenv(key) or "").strip()
        if val and pathlib.Path(val).exists():
            return val
    which = shutil.which("ffmpeg")
    if which:
        return which
    raise RuntimeError("ffmpeg not found for story mode rendering.")


def _pick_theme(theme: str | None, visual: str) -> str:
    t = (theme or "").strip().lower().replace(" ", "_")
    if t in THEME_PRESETS:
        return t
    return "city_lab"


def _pick_host(host_character: str | None) -> str:
    h = (host_character or "").strip().lower().replace(" ", "_")
    if h in HOST_PRESETS:
        return h
    return "friendly_robot"


def _resolve_host_payload(host_character: str | None) -> dict[str, str]:
    host_key = _pick_host(host_character)
    if host_key in HOST_PRESETS:
        return HOST_PRESETS[host_key]
    return HOST_PRESETS["friendly_robot"]


def _extract_js_block(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            # Remove first fence and optional closing fence.
            body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
            text = "\n".join(body).strip()
    return text


def _generate_scene_draw_js(
    scene: dict[str, Any],
    *,
    provider: str,
    api_key: str,
    model: str | None,
    host_character: str | None = None,
    theme: str | None = None,
) -> str:
    use_model = model
    if not use_model and provider == "claude":
        use_model = "claude-haiku-4-5"
    host_options = ", ".join(sorted(HOST_PRESETS.keys()))
    theme_options = ", ".join(sorted(THEME_PRESETS.keys()))
    user = (
        f"Scene heading: {scene.get('heading', '')}\n"
        f"Visual description: {scene.get('visual', '')}\n"
        f"Lesson text: {scene.get('lesson', '')}\n"
        f"Available main characters: {host_options}\n"
        f"Available visual themes: {theme_options}\n"
        f"Main character preference: {host_character or 'auto'}\n"
        f"Selected theme: {theme or 'auto'}\n"
        "Render concrete objects from the visual description (not abstract particles only).\n"
        "Include at least one animated main character (person/animal/robot) with visible motion.\n"
        "Use any named characters from the scene/title (keep names consistent).\n"
        "Match a simple storyboard style: characters + props, clean shapes, no abstract blobs/particles.\n"
        "Use the theme colors for backgrounds and props.\n"
        "Animate characters and objects with moving parts (arms, heads, props, or gestures).\n"
        "Add visible motion so learners can understand cause/effect.\n"
        "Use drawCharacterTemplate for people/animals/robots (do not draw custom bodies).\n"
        "IMPORTANT: Use exactly ONE drawSpeechBubble call for the lesson text, placed above the main character.\n"
        "NEVER use fillText or strokeText directly — ALL text must go through drawSpeechBubble.\n"
        "Do NOT draw heading bars, caption rectangles, or any text overlay at top or bottom.\n"
        "Keep speech bubble text short and readable (max 8 words).\n"
        "Return only the JavaScript function body."
    )
    raw = call_llm(
        provider=provider,  # type: ignore[arg-type]
        api_key=api_key,
        model=use_model,
        system=DRAW_JS_SYSTEM,
        user=user,
        temperature=0.3,
        max_tokens=2000,
    )
    return _extract_js_block(raw)


def _build_scene_template_html(
    scene: dict[str, Any],
    host_payload: dict[str, str],
    scene_js: str,
    theme: str | None = None,
) -> str:
    theme_key = _pick_theme(theme, str(scene.get("visual") or ""))
    payload = {
        "heading": str(scene.get("heading") or "Story Scene"),
        "lesson": str(scene.get("lesson") or ""),
        "caption": str(scene.get("caption") or scene.get("lesson") or ""),
        "visual": str(scene.get("visual") or ""),
        "duration_sec": int(scene.get("duration_sec") or 10),
        "theme": THEME_PRESETS[theme_key],
        "host": host_payload,
    }
    payload_json = json.dumps(payload, ensure_ascii=True)
    scene_js_json = json.dumps(scene_js or "", ensure_ascii=True)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }}
    canvas {{ display: block; width: 100vw; height: 100vh; }}
  </style>
</head>
<body>
  <canvas id="c"></canvas>
  <script>
    const S = {payload_json};
    const SCENE_DRAW_JS = {scene_js_json};
    const c = document.getElementById('c');
    const x = c.getContext('2d');
        let drawSceneFn = null;
    try {{
      if (SCENE_DRAW_JS && SCENE_DRAW_JS.trim()) {{
                drawSceneFn = new Function(
                    'x', 'w', 'h', 'dt',
                    'drawCharacter', 'drawCloud', 'drawGround', 'drawSpeechBubble', 'drawStar',
                    'drawCharacterTemplate',
                    SCENE_DRAW_JS
                );
      }}
    }} catch (e) {{
      drawSceneFn = null;
    }}
        let w = 0, h = 0;
    function rs() {{
      c.width = Math.max(960, window.innerWidth);
      c.height = Math.max(540, window.innerHeight);
      w = c.width; h = c.height;
    }}
    window.addEventListener('resize', rs);
    rs();
    const start = performance.now();
        function drawCharacter(ctx, cx, cy, scale, headColor, bodyColor, eyeColor, mouthUp, bobAmt) {{
            const s = scale || 1;
            const hy = cy;
            ctx.lineCap = 'round';
            // Legs
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 8*s;
            ctx.beginPath(); ctx.moveTo(cx - 8*s, hy - 42*s); ctx.lineTo(cx - 10*s, hy - 8*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 8*s, hy - 42*s); ctx.lineTo(cx + 10*s, hy - 8*s); ctx.stroke();
            // Shoes
            ctx.fillStyle = '#3a3a3a';
            ctx.beginPath(); ctx.ellipse(cx - 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Torso (rounded)
            ctx.fillStyle = bodyColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 66*s, 22*s, 28*s, 0, 0, Math.PI*2); ctx.fill();
            // Arms
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 7*s;
            ctx.beginPath(); ctx.moveTo(cx - 22*s, hy - 78*s); ctx.quadraticCurveTo(cx - 38*s, hy - 68*s, cx - 36*s, hy - 52*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 22*s, hy - 78*s); ctx.quadraticCurveTo(cx + 38*s, hy - 68*s, cx + 36*s, hy - 52*s); ctx.stroke();
            // Hands
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.arc(cx - 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            // Neck
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 96*s, 6*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Head
            ctx.beginPath(); ctx.arc(cx, hy - 112*s, 24*s, 0, Math.PI*2); ctx.fill();
            // Eyes (sclera + pupil)
            ctx.fillStyle = '#fff';
            ctx.beginPath(); ctx.ellipse(cx - 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.fillStyle = eyeColor || '#222';
            ctx.beginPath(); ctx.arc(cx - 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            // Mouth
            ctx.beginPath();
            if (mouthUp) {{ ctx.arc(cx, hy - 105*s, 5*s, Math.PI, 0); }}
            else {{ ctx.arc(cx, hy - 103*s, 5*s, 0, Math.PI); }}
            ctx.strokeStyle = '#555'; ctx.lineWidth = 1.5*s; ctx.stroke();
        }}
        function drawCloud(ctx, cx, cy, cw) {{
            ctx.fillStyle = 'rgba(255,255,255,0.92)';
            ctx.beginPath(); ctx.arc(cx, cy, cw*0.28, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.22, cy + cw*0.04, cw*0.22, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.22, cy + cw*0.06, cw*0.2, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.08, cy + cw*0.15, cw*0.24, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.08, cy - cw*0.08, cw*0.18, 0, Math.PI*2); ctx.fill();
        }}
        function drawGround(ctx, w2, h2, groundY, grassColor, dirtColor) {{
            ctx.fillStyle = dirtColor || '#8B6543';
            ctx.fillRect(0, groundY, w2, h2 - groundY);
            ctx.fillStyle = grassColor || '#4a7c3f';
            ctx.fillRect(0, groundY, w2, 14);
        }}
        function drawSpeechBubble(ctx, cx, cy, text, fontSize) {{
            const fs = fontSize || 16;
            const maxW = Math.min(w * 0.5, 280);
            ctx.font = '600 ' + fs + 'px Arial';
            const words = String(text || '').split(/\s+/).filter(Boolean);
            const lines = [];
            let line = '';
            for (const wd of words) {{
                const t = line ? line + ' ' + wd : wd;
                if (ctx.measureText(t).width > maxW && line) {{
                    lines.push(line);
                    line = wd;
                }} else line = t;
            }}
            if (line) lines.push(line);
            const safeLines = lines.slice(0, 3);
            const widths = safeLines.map((l) => ctx.measureText(l).width);
            const textW = widths.length ? Math.max(...widths) : 0;
            const pad = 16;
            const bw = Math.min(maxW, textW) + pad * 2;
            const lineH = fs + 6;
            const bh = safeLines.length * lineH + pad;
            const margin = 8;
            let bx = cx - bw / 2;
            let by = cy - bh - 14;
            if (by < margin) by = margin;
            if (bx < margin) bx = margin;
            if (bx + bw > w - margin) bx = w - margin - bw;
            const textCx = bx + bw / 2;
            const ptrCx = Math.max(bx + 12, Math.min(cx, bx + bw - 12));
            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,0.18)';
            ctx.shadowBlur = 8;
            ctx.shadowOffsetY = 3;
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.fill();
            ctx.restore();
            ctx.strokeStyle = 'rgba(0,0,0,0.08)'; ctx.lineWidth = 1;
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.stroke();
            ctx.fillStyle = '#1e293b';
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            safeLines.forEach((ln, i) => {{
                ctx.fillText(ln, textCx, by + pad / 2 + i * lineH);
            }});
            ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            ctx.moveTo(ptrCx - 8, by + bh);
            ctx.lineTo(ptrCx + 8, by + bh);
            ctx.lineTo(ptrCx, by + bh + 12);
            ctx.closePath(); ctx.fill();
        }}
        function drawStar(ctx, cx, cy, r, color) {{
            ctx.fillStyle = color || '#ffd700';
            ctx.beginPath();
            for (let i = 0; i < 10; i++) {{
                const a = (i * Math.PI / 5) - Math.PI/2;
                const rad = i % 2 === 0 ? r : r * 0.4;
                if (i === 0) ctx.moveTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
                else ctx.lineTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
            }}
            ctx.closePath(); ctx.fill();
        }}
        function drawCharacterTemplate(ctx, cx, cy, scale, variant, bobAmt) {{
            const v = String(variant || 'friendly_robot');
            const templates = {{
                scientist: {{ head: '#f2c9a2', body: '#f7fbff', eye: '#1f2937', accent: '#4f79ff' }},
                friendly_robot: {{ head: '#b0d4f1', body: '#e0efff', eye: '#0f172a', accent: '#6cf0ff' }},
                animal_guide: {{ head: '#e0caa8', body: '#6b5640', eye: '#1f2937', accent: '#8b6b43' }},
                explorer: {{ head: '#f2c9a2', body: '#2d3748', eye: '#111827', accent: '#f59e0b' }},
                artist: {{ head: '#f1c6a8', body: '#fdf2f8', eye: '#111827', accent: '#ec4899' }},
                athlete: {{ head: '#f0c7a0', body: '#1a202c', eye: '#111827', accent: '#22c55e' }},
            }};
            const t = templates[v] || templates.friendly_robot;
            drawCharacter(ctx, cx, cy, scale, t.head, t.body, t.eye, true, bobAmt);
            const s = scale || 1;
            if (v === 'scientist') {{
                // Glasses
                ctx.strokeStyle = t.accent; ctx.lineWidth = 2 * s;
                ctx.beginPath(); ctx.arc(cx - 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.arc(cx + 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(cx - 1*s, cy - 116*s); ctx.lineTo(cx + 1*s, cy - 116*s); ctx.stroke();
                // Lab coat collar
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 94*s, 24*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'friendly_robot') {{
                // Antenna
                ctx.strokeStyle = '#888'; ctx.lineWidth = 2*s;
                ctx.beginPath(); ctx.moveTo(cx, cy - 136*s); ctx.lineTo(cx, cy - 148*s); ctx.stroke();
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.arc(cx, cy - 150*s, 4*s, 0, Math.PI*2); ctx.fill();
                // Visor band
                ctx.fillStyle = 'rgba(108,240,255,0.3)';
                ctx.beginPath(); ctx.ellipse(cx, cy - 116*s, 18*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'animal_guide') {{
                // Ears
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 128*s, 8*s, 12*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 128*s, 8*s, 12*s, 0.3, 0, Math.PI*2); ctx.fill();
                ctx.fillStyle = '#f0c0a0';
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 126*s, 4*s, 7*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 126*s, 4*s, 7*s, 0.3, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'explorer') {{
                // Hat
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 134*s, 28*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
                ctx.fillRect(cx - 14*s, cy - 146*s, 28*s, 14*s);
            }} else if (v === 'artist') {{
                // Beret
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx + 2*s, cy - 132*s, 20*s, 10*s, 0.2, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.arc(cx + 2*s, cy - 142*s, 3*s, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'athlete') {{
                // Headband
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 128*s, 26*s, 4*s, 0, 0, Math.PI*2); ctx.fill();
            }}
        }}
        function drawFallbackAnimated(tSec) {{
            const cx = w * 0.5;
            const cy = h * 0.48;
            const bob = Math.sin(tSec * 2.2) * 6;
            const arm = Math.sin(tSec * 3.1) * 8;
            const head = Math.sin(tSec * 1.7) * 0.08;
            x.save();
            x.translate(cx, cy + bob);
            x.rotate(head);
            x.fillStyle = '#e2e8f0';
            x.fillRect(-26, -10, 52, 60);
            x.fillStyle = '#0f172a';
            x.fillRect(-18, 10, 36, 40);
            x.fillStyle = '#fcd34d';
            x.beginPath(); x.arc(0, -28, 22, 0, Math.PI * 2); x.fill();
            x.fillStyle = '#111827';
            x.beginPath(); x.arc(-7, -30, 2.2, 0, Math.PI * 2); x.arc(7, -30, 2.2, 0, Math.PI * 2); x.fill();
            x.strokeStyle = '#111827'; x.lineWidth = 2;
            x.beginPath(); x.arc(0, -24, 7, 0.1, Math.PI - 0.1); x.stroke();
            x.strokeStyle = '#fcd34d'; x.lineWidth = 6;
            x.beginPath(); x.moveTo(-22, 0); x.lineTo(-40, 6 + arm); x.stroke();
            x.beginPath(); x.moveTo(22, 0); x.lineTo(40, 6 - arm); x.stroke();
            x.fillStyle = '#334155';
            x.beginPath(); x.ellipse(-12, 54, 12, 5, 0, 0, Math.PI * 2); x.fill();
            x.beginPath(); x.ellipse(12, 54, 12, 5, 0, 0, Math.PI * 2); x.fill();
            x.restore();

            const tableY = h * 0.62 + Math.sin(tSec * 1.3) * 2;
            x.fillStyle = '#6b4f34';
            x.fillRect(cx - 140, tableY, 280, 18);
            x.fillStyle = '#5a3f28';
            x.fillRect(cx - 120, tableY + 18, 16, 32);
            x.fillRect(cx + 104, tableY + 18, 16, 32);
            x.fillStyle = '#eab308';
            x.beginPath(); x.arc(cx - 40, tableY - 10, 12, 0, Math.PI * 2); x.fill();
            x.fillStyle = '#f97316';
            x.beginPath(); x.arc(cx + 30, tableY - 12, 10, 0, Math.PI * 2); x.fill();
        }}
    function tick(t) {{
      const dt = (t - start) / 1000;
      const g = x.createLinearGradient(0,0,0,h);
      g.addColorStop(0, S.theme.bg0); g.addColorStop(1, S.theme.bg1);
      x.fillStyle = g; x.fillRect(0,0,w,h);
            if (drawSceneFn) {{
                try {{
                    drawSceneFn(x, w, h, dt, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar, drawCharacterTemplate);
                }} catch (e) {{
                    drawFallbackAnimated(dt);
                }}
            }} else {{
                drawFallbackAnimated(dt);
            }}
      // Bottom-of-canvas info bar
      const barH = 80;
      const barY = h - barH;
      x.fillStyle = S.theme.panel || 'rgba(0,0,0,0.55)';
      x.fillRect(0, barY, w, barH);
      x.fillStyle = '#ffffff';
      x.font = '700 20px Arial';
      x.textAlign = 'center';
      x.textBaseline = 'top';
      x.fillText(String(S.heading || '').slice(0, 60), w / 2, barY + 12);
      x.font = '400 15px Arial';
      x.fillStyle = 'rgba(255,255,255,0.82)';
      const capText = String(S.caption || S.lesson || '').slice(0, 120);
      x.fillText(capText, w / 2, barY + 40);
      x.textAlign = 'left';
      x.textBaseline = 'alphabetic';
      requestAnimationFrame(tick);
    }}
    requestAnimationFrame(tick);
  </script>
</body>
</html>"""


def _render_html_to_clip(
    html: str,
    out_path: pathlib.Path,
    duration_sec: int,
    ffmpeg_bin: str,
    fps: int = 24,
) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from e

    def _candidate_roots() -> list[pathlib.Path]:
        roots: list[pathlib.Path] = []
        env_root = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
        if env_root:
            roots.append(pathlib.Path(env_root))
        home = pathlib.Path.home()
        roots.extend(
            [
                home / ".cache" / "ms-playwright",
                home / "Library" / "Caches" / "ms-playwright",
            ]
        )
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            roots.append(pathlib.Path(local_app_data) / "ms-playwright")
        seen: set[str] = set()
        deduped: list[pathlib.Path] = []
        for r in roots:
            k = str(r)
            if k in seen:
                continue
            seen.add(k)
            deduped.append(r)
        return deduped

    def _find_browser_executable() -> str | None:
        names_by_platform = {
            "linux": ["chrome-headless-shell", "chrome"],
            "darwin": ["Chromium", "chrome", "chrome-headless-shell"],
            "win32": ["chrome.exe", "chrome-headless-shell.exe"],
        }
        names = names_by_platform.get(sys.platform, ["chrome", "chrome-headless-shell"])
        candidates: list[pathlib.Path] = []
        for root in _candidate_roots():
            if not root.exists():
                continue
            for name in names:
                candidates.extend(root.rglob(name))
        candidates = [p for p in candidates if p.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])

    def _install_playwright_browser_default_cache() -> None:
        env = dict(os.environ)
        # Ensure install goes to default per-user cache in dev fallback.
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )

    frames_dir = out_path.parent / f"frames_{out_path.stem}"
    frames_dir.mkdir(exist_ok=True)
    total_frames = duration_sec * fps

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as launch_err:
                err_txt = str(launch_err)
                if "Executable doesn't exist" not in err_txt:
                    raise
                pw_env = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
                logger.warning(
                    "story: playwright launch failed at PLAYWRIGHT_BROWSERS_PATH=%s; trying explicit executable fallback",
                    pw_env,
                )
                exe = _find_browser_executable()
                if exe:
                    logger.info("story: launching playwright with explicit executable %s", exe)
                    browser = pw.chromium.launch(executable_path=exe)
                else:
                    logger.warning("story: no local playwright browser found, installing chromium to default cache")
                    _install_playwright_browser_default_cache()
                    exe2 = _find_browser_executable()
                    if not exe2:
                        raise RuntimeError(
                            "Playwright browser executable missing after install. "
                            "Run: python -m playwright install chromium"
                        )
                    browser = pw.chromium.launch(executable_path=exe2)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(html, wait_until="domcontentloaded")
            page.wait_for_timeout(200)

            for i in range(total_frames):
                page.evaluate(f"window._frameTime = {(i / fps) * 1000}")
                screenshot = page.screenshot(type="png")
                (frames_dir / f"frame_{i:05d}.png").write_bytes(screenshot)
                page.wait_for_timeout(int(1000 / fps))

            browser.close()

        cmd = [
            ffmpeg_bin,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg frame encode failed: {proc.stderr[-600:]}")
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _format_vtt_ts(total_sec: float) -> str:
    ms = int((total_sec % 1) * 1000)
    sec = int(total_sec) % 60
    minute = (int(total_sec) // 60) % 60
    hour = int(total_sec) // 3600
    return f"{hour:02d}:{minute:02d}:{sec:02d}.{ms:03d}"


def _write_vtt(job_dir: pathlib.Path, scenes: list[dict[str, Any]], out_name: str) -> pathlib.Path:
    vtt_path = job_dir / out_name
    lines = ["WEBVTT", ""]
    t = 0.0
    for idx, scene in enumerate(scenes, start=1):
        dur = float(scene["duration_sec"])
        start = _format_vtt_ts(t)
        end = _format_vtt_ts(t + dur)
        lines.append(f"{start} --> {end}")
        caption = str(scene.get("caption") or scene.get("lesson") or "").strip()
        lines.append(f"{scene['heading']}: {caption}")
        lines.append("")
        t += dur
    vtt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return vtt_path


def generate_story_video(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    story_options: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    from uuid import uuid4

    prov, key = _pick_provider_and_key(provider, provider_keys)
    options = story_options or {}
    host_character = str(options.get("host_character") or "").strip() or None
    theme = str(options.get("theme") or "").strip() or None
    raw = call_llm(
        provider=prov,
        api_key=key,
        model=model,
        system=None,
        user=_story_prompt(prompt, host_character=host_character, theme=theme),
        temperature=0.6,
        max_tokens=3000,
    )
    plan = _normalize_story_plan(_extract_json(raw), prompt)
    host_payload = _resolve_host_payload(host_character)

    ffmpeg_bin = _find_ffmpeg()
    jid = job_id or str(uuid4())[:8]
    job_dir = STORAGE / "jobs" / jid
    out_dir = job_dir / "out"
    logs_dir = job_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    clips: list[pathlib.Path] = []
    for idx, scene in enumerate(plan["scenes"], start=1):
        clip = out_dir / f"scene_{idx:02d}.mp4"
        try:
            logger.info(
                "story: rendering template scene %d/%d — %s",
                idx,
                len(plan["scenes"]),
                scene["heading"],
            )
            scene_js = _generate_scene_draw_js(
                scene,
                provider=prov,
                api_key=key,
                model=model,
                host_character=host_character,
                theme=theme,
            )
            scene_html = _build_scene_template_html(
                scene,
                host_payload=host_payload,
                scene_js=scene_js,
                theme=theme,
            )
        except Exception:
            logger.exception("story: scene template generation failed at index=%d heading=%s", idx, scene.get("heading"))
            raise
        _render_html_to_clip(
            html=scene_html,
            out_path=clip,
            duration_sec=int(scene["duration_sec"]),
            ffmpeg_bin=ffmpeg_bin,
        )
        clips.append(clip)

    concat_file = out_dir / "concat.txt"
    concat_file.write_text(
        "\n".join([f"file '{c.as_posix()}'" for c in clips]) + "\n", encoding="utf-8"
    )
    final_mp4 = out_dir / "final.mp4"
    concat_cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(final_mp4),
    ]
    proc = subprocess.run(concat_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Re-encode fallback if stream-copy concat fails.
        reencode_cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(final_mp4),
        ]
        proc2 = subprocess.run(reencode_cmd, capture_output=True, text=True)
        if proc2.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {proc2.stderr[-800:]}")

    vtt_path = _write_vtt(out_dir, plan["scenes"], "final.vtt")
    (logs_dir / "story_plan.json").write_text(json.dumps(plan, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "job_id": jid,
        "video_url": to_static_url(final_mp4),
        "vtt_url": to_static_url(vtt_path),
        "story_plan": plan,
    }


def _build_story_slider_html(
    plan: dict[str, Any],
    *,
    host_payload: dict[str, str],
    draw_js_by_scene: list[str],
    theme: str | None = None,
) -> str:
    scenes_payload: list[dict[str, Any]] = []
    for idx, scene in enumerate(plan.get("scenes", [])):
        scene_theme = THEME_PRESETS[_pick_theme(theme, str(scene.get("visual") or ""))]
        scenes_payload.append(
            {
                "heading": str(scene.get("heading") or f"Scene {idx + 1}"),
                "caption": str(scene.get("caption") or scene.get("lesson") or ""),
                "lesson": str(scene.get("lesson") or ""),
                "visual": str(scene.get("visual") or ""),
                "duration_sec": int(scene.get("duration_sec") or 10),
                "theme": scene_theme,
                "draw_js": draw_js_by_scene[idx] if idx < len(draw_js_by_scene) else "",
            }
        )
    payload = {
        "title": str(plan.get("title") or "Story"),
        "moral": str(plan.get("moral") or ""),
        "conclusion": str(plan.get("conclusion") or ""),
        "host": host_payload,
        "scenes": scenes_payload,
    }
    payload_json = json.dumps(payload, ensure_ascii=True)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #050b1f; color: #fff; overflow: hidden; font-family: Arial, sans-serif; }}
    .wrap {{ display: grid; grid-template-rows: minmax(0, 1fr) auto; width: 100%; height: 100%; }}
    .viz {{ position: relative; min-width: 0; min-height: 0; }}
    #c {{ width: 100%; height: 100%; display: block; }}
    .panel {{ background: rgba(8, 14, 34, 0.94); border-top: 1px solid rgba(255,255,255,0.12); padding: 12px 14px; display: grid; grid-template-columns: 1.3fr 1fr auto; gap: 12px; align-items: start; }}
    .title {{ font-size: 24px; font-weight: 700; margin: 0 0 6px 0; }}
    .row {{ display: flex; align-items: center; gap: 8px; }}
    .meta {{ font-size: 13px; color: #bfdbfe; margin-bottom: 6px; }}
    .caption {{ font-size: 14px; line-height: 1.4; color: #e2e8f0; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 10px; }}
    .dots {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; background: rgba(255,255,255,0.28); border: 0; cursor: pointer; }}
    .dot.active {{ background: #7dd3fc; }}
    .controls {{ display: flex; gap: 8px; align-items: center; justify-content: flex-end; min-width: 130px; }}
    button {{ border: 1px solid rgba(255,255,255,0.25); background: rgba(255,255,255,0.08); color: #fff; padding: 8px 10px; border-radius: 8px; cursor: pointer; }}
    button:hover {{ background: rgba(255,255,255,0.14); }}
    input[type="range"] {{ width: 100%; margin-top: 4px; }}
    .footer {{ font-size: 12px; color: #cbd5e1; padding-top: 6px; }}
    .col-main {{ min-width: 0; }}
    .col-nav {{ min-width: 0; }}
    @media (max-width: 920px) {{
      .panel {{ grid-template-columns: 1fr; gap: 10px; }}
      .controls {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="viz" id="viz"><canvas id="c"></canvas></div>
    <aside class="panel">
      <div class="col-main">
        <h2 class="title" id="storyTitle">Story</h2>
        <div class="row meta">
          <strong id="sceneLabel">Scene 1</strong>
          <span>•</span>
          <span id="sceneHeading">Loading...</span>
        </div>
        <div class="caption" id="sceneCaption">...</div>
        <div class="footer" id="storyFooter"></div>
      </div>
      <div class="col-nav">
        <input id="sceneSlider" type="range" min="1" max="1" step="1" value="1" />
        <div class="dots" id="sceneDots"></div>
      </div>
      <div class="controls">
        <button id="prevBtn" type="button" aria-label="Previous scene">Prev</button>
        <button id="nextBtn" type="button" aria-label="Next scene">Next</button>
      </div>
    </aside>
  </div>
  <script>
    const P = {payload_json};
    const cv = document.getElementById('c');
    const ctx = cv.getContext('2d');
    const viz = document.getElementById('viz');
    const storyTitle = document.getElementById('storyTitle');
    const sceneLabel = document.getElementById('sceneLabel');
    const sceneHeading = document.getElementById('sceneHeading');
    const sceneCaption = document.getElementById('sceneCaption');
    const sceneSlider = document.getElementById('sceneSlider');
    const sceneDots = document.getElementById('sceneDots');
    const storyFooter = document.getElementById('storyFooter');
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
        const scenes = Array.isArray(P.scenes) ? P.scenes : [];
        function drawCharacter(ctx, cx, cy, scale, headColor, bodyColor, eyeColor, mouthUp, bobAmt) {{
            const s = scale || 1;
            const hy = cy;
            ctx.lineCap = 'round';
            // Legs
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 8*s;
            ctx.beginPath(); ctx.moveTo(cx - 8*s, hy - 42*s); ctx.lineTo(cx - 10*s, hy - 8*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 8*s, hy - 42*s); ctx.lineTo(cx + 10*s, hy - 8*s); ctx.stroke();
            // Shoes
            ctx.fillStyle = '#3a3a3a';
            ctx.beginPath(); ctx.ellipse(cx - 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 10*s, hy - 4*s, 9*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Torso (rounded)
            ctx.fillStyle = bodyColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 66*s, 22*s, 28*s, 0, 0, Math.PI*2); ctx.fill();
            // Arms
            ctx.strokeStyle = bodyColor; ctx.lineWidth = 7*s;
            ctx.beginPath(); ctx.moveTo(cx - 22*s, hy - 78*s); ctx.quadraticCurveTo(cx - 38*s, hy - 68*s, cx - 36*s, hy - 52*s); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx + 22*s, hy - 78*s); ctx.quadraticCurveTo(cx + 38*s, hy - 68*s, cx + 36*s, hy - 52*s); ctx.stroke();
            // Hands
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.arc(cx - 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 36*s, hy - 50*s, 5*s, 0, Math.PI*2); ctx.fill();
            // Neck
            ctx.fillStyle = headColor;
            ctx.beginPath(); ctx.ellipse(cx, hy - 96*s, 6*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
            // Head
            ctx.beginPath(); ctx.arc(cx, hy - 112*s, 24*s, 0, Math.PI*2); ctx.fill();
            // Eyes (sclera + pupil)
            ctx.fillStyle = '#fff';
            ctx.beginPath(); ctx.ellipse(cx - 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(cx + 8*s, hy - 116*s, 5.5*s, 4.5*s, 0, 0, Math.PI*2); ctx.fill();
            ctx.fillStyle = eyeColor || '#222';
            ctx.beginPath(); ctx.arc(cx - 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + 7*s, hy - 116*s, 2.5*s, 0, Math.PI*2); ctx.fill();
            // Mouth
            ctx.beginPath();
            if (mouthUp) {{ ctx.arc(cx, hy - 105*s, 5*s, Math.PI, 0); }}
            else {{ ctx.arc(cx, hy - 103*s, 5*s, 0, Math.PI); }}
            ctx.strokeStyle = '#555'; ctx.lineWidth = 1.5*s; ctx.stroke();
        }}
        function drawCloud(ctx, cx, cy, cw) {{
            ctx.fillStyle = 'rgba(255,255,255,0.92)';
            ctx.beginPath(); ctx.arc(cx, cy, cw*0.28, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.22, cy + cw*0.04, cw*0.22, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.22, cy + cw*0.06, cw*0.2, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx + cw*0.08, cy + cw*0.15, cw*0.24, 0, Math.PI*2); ctx.fill();
            ctx.beginPath(); ctx.arc(cx - cw*0.08, cy - cw*0.08, cw*0.18, 0, Math.PI*2); ctx.fill();
        }}
        function drawGround(ctx, w2, h2, groundY, grassColor, dirtColor) {{
            ctx.fillStyle = dirtColor || '#8B6543';
            ctx.fillRect(0, groundY, w2, h2 - groundY);
            ctx.fillStyle = grassColor || '#4a7c3f';
            ctx.fillRect(0, groundY, w2, 14);
        }}
        function drawSpeechBubble(ctx, cx, cy, text, fontSize) {{
            const fs = fontSize || 16;
            const maxW = Math.min(w * 0.5, 280);
            ctx.font = '600 ' + fs + 'px Arial';
            const words = String(text || '').split(/\s+/).filter(Boolean);
            const lines = [];
            let line = '';
            for (const wd of words) {{
                const t = line ? line + ' ' + wd : wd;
                if (ctx.measureText(t).width > maxW && line) {{
                    lines.push(line);
                    line = wd;
                }} else line = t;
            }}
            if (line) lines.push(line);
            const safeLines = lines.slice(0, 3);
            const widths = safeLines.map((l) => ctx.measureText(l).width);
            const textW = widths.length ? Math.max(...widths) : 0;
            const pad = 16;
            const bw = Math.min(maxW, textW) + pad * 2;
            const lineH = fs + 6;
            const bh = safeLines.length * lineH + pad;
            const margin = 8;
            let bx = cx - bw / 2;
            let by = cy - bh - 14;
            if (by < margin) by = margin;
            if (bx < margin) bx = margin;
            if (bx + bw > w - margin) bx = w - margin - bw;
            const textCx = bx + bw / 2;
            const ptrCx = Math.max(bx + 12, Math.min(cx, bx + bw - 12));
            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,0.18)';
            ctx.shadowBlur = 8;
            ctx.shadowOffsetY = 3;
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.fill();
            ctx.restore();
            ctx.strokeStyle = 'rgba(0,0,0,0.08)'; ctx.lineWidth = 1;
            ctx.beginPath();
            if (ctx.roundRect) {{ ctx.roundRect(bx, by, bw, bh, 12); }}
            else {{ ctx.rect(bx, by, bw, bh); }}
            ctx.stroke();
            ctx.fillStyle = '#1e293b';
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            safeLines.forEach((ln, i) => {{
                ctx.fillText(ln, textCx, by + pad / 2 + i * lineH);
            }});
            ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            ctx.moveTo(ptrCx - 8, by + bh);
            ctx.lineTo(ptrCx + 8, by + bh);
            ctx.lineTo(ptrCx, by + bh + 12);
            ctx.closePath(); ctx.fill();
        }}
        function drawStar(ctx, cx, cy, r, color) {{
            ctx.fillStyle = color || '#ffd700';
            ctx.beginPath();
            for (let i = 0; i < 10; i++) {{
                const a = (i * Math.PI / 5) - Math.PI/2;
                const rad = i % 2 === 0 ? r : r * 0.4;
                if (i === 0) ctx.moveTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
                else ctx.lineTo(cx + Math.cos(a)*rad, cy + Math.sin(a)*rad);
            }}
            ctx.closePath(); ctx.fill();
        }}
        function drawCharacterTemplate(ctx, cx, cy, scale, variant, bobAmt) {{
            const v = String(variant || 'friendly_robot');
            const templates = {{
                scientist: {{ head: '#f2c9a2', body: '#f7fbff', eye: '#1f2937', accent: '#4f79ff' }},
                friendly_robot: {{ head: '#b0d4f1', body: '#e0efff', eye: '#0f172a', accent: '#6cf0ff' }},
                animal_guide: {{ head: '#e0caa8', body: '#6b5640', eye: '#1f2937', accent: '#8b6b43' }},
                explorer: {{ head: '#f2c9a2', body: '#2d3748', eye: '#111827', accent: '#f59e0b' }},
                artist: {{ head: '#f1c6a8', body: '#fdf2f8', eye: '#111827', accent: '#ec4899' }},
                athlete: {{ head: '#f0c7a0', body: '#1a202c', eye: '#111827', accent: '#22c55e' }},
            }};
            const t = templates[v] || templates.friendly_robot;
            drawCharacter(ctx, cx, cy, scale, t.head, t.body, t.eye, true, bobAmt);
            const s = scale || 1;
            if (v === 'scientist') {{
                ctx.strokeStyle = t.accent; ctx.lineWidth = 2 * s;
                ctx.beginPath(); ctx.arc(cx - 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.arc(cx + 8*s, cy - 116*s, 7*s, 0, Math.PI*2); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(cx - 1*s, cy - 116*s); ctx.lineTo(cx + 1*s, cy - 116*s); ctx.stroke();
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 94*s, 24*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'friendly_robot') {{
                ctx.strokeStyle = '#888'; ctx.lineWidth = 2*s;
                ctx.beginPath(); ctx.moveTo(cx, cy - 136*s); ctx.lineTo(cx, cy - 148*s); ctx.stroke();
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.arc(cx, cy - 150*s, 4*s, 0, Math.PI*2); ctx.fill();
                ctx.fillStyle = 'rgba(108,240,255,0.3)';
                ctx.beginPath(); ctx.ellipse(cx, cy - 116*s, 18*s, 6*s, 0, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'animal_guide') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 128*s, 8*s, 12*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 128*s, 8*s, 12*s, 0.3, 0, Math.PI*2); ctx.fill();
                ctx.fillStyle = '#f0c0a0';
                ctx.beginPath(); ctx.ellipse(cx - 20*s, cy - 126*s, 4*s, 7*s, -0.3, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.ellipse(cx + 20*s, cy - 126*s, 4*s, 7*s, 0.3, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'explorer') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 134*s, 28*s, 5*s, 0, 0, Math.PI*2); ctx.fill();
                ctx.fillRect(cx - 14*s, cy - 146*s, 28*s, 14*s);
            }} else if (v === 'artist') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx + 2*s, cy - 132*s, 20*s, 10*s, 0.2, 0, Math.PI*2); ctx.fill();
                ctx.beginPath(); ctx.arc(cx + 2*s, cy - 142*s, 3*s, 0, Math.PI*2); ctx.fill();
            }} else if (v === 'athlete') {{
                ctx.fillStyle = t.accent;
                ctx.beginPath(); ctx.ellipse(cx, cy - 128*s, 26*s, 4*s, 0, 0, Math.PI*2); ctx.fill();
            }}
        }}
        const drawFns = scenes.map((s) => {{
            try {{
                if (s.draw_js && String(s.draw_js).trim()) {{
                    return new Function(
                        'x', 'w', 'h', 'dt',
                        'drawCharacter', 'drawCloud', 'drawGround', 'drawSpeechBubble', 'drawStar',
                        'drawCharacterTemplate',
                        s.draw_js
                    );
                }}
            }} catch (e) {{}}
            return null;
        }});
    storyTitle.textContent = P.title || "Story";
    storyFooter.textContent = "";
    storyFooter.style.display = "none";
    sceneCaption.textContent = P.moral || P.conclusion || "";
    let w = 0, h = 0;
    let current = 0;
    let sceneStart = performance.now();
    function fit() {{
      cv.width = Math.max(800, viz.clientWidth);
      cv.height = Math.max(450, viz.clientHeight);
      w = cv.width; h = cv.height;
    }}
    function setScene(idx) {{
      const n = scenes.length || 1;
      current = ((idx % n) + n) % n;
      sceneStart = performance.now();
      const s = scenes[current] || {{}};
      sceneLabel.textContent = `Scene ${{current + 1}}`;
      sceneHeading.textContent = String(s.heading || P.title || 'Story');
      sceneCaption.textContent = String(s.caption || s.lesson || '');
      sceneSlider.value = String(current + 1);
      Array.from(sceneDots.children).forEach((el, i) => el.classList.toggle('active', i === current));
    }}
    function initUI() {{
      sceneDots.innerHTML = "";
      sceneSlider.max = String(Math.max(1, scenes.length));
      for (let i = 0; i < scenes.length; i++) {{
        const d = document.createElement('button');
        d.className = 'dot' + (i === 0 ? ' active' : '');
        d.type = 'button';
        d.addEventListener('click', () => setScene(i));
        sceneDots.appendChild(d);
      }}
      prevBtn.addEventListener('click', () => setScene(current - 1));
      nextBtn.addEventListener('click', () => setScene(current + 1));
      sceneSlider.addEventListener('input', () => setScene(Number(sceneSlider.value) - 1));
    }}
    function drawFallbackScene(s, dt) {{
      const pulse = 0.5 + 0.5 * Math.sin(dt * 1.8);
      const boxW = Math.min(w * 0.72, 640);
      const boxH = Math.min(h * 0.36, 280);
      const bx = (w - boxW) / 2;
      const by = (h - boxH) / 2 - 20;
      ctx.fillStyle = 'rgba(7, 12, 28, 0.82)';
      ctx.fillRect(bx, by, boxW, boxH);
      ctx.strokeStyle = 'rgba(125, 211, 252, 0.55)';
      ctx.lineWidth = 2 + pulse;
      ctx.strokeRect(bx, by, boxW, boxH);
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '700 24px Arial';
      ctx.fillText(String(s.heading || 'Scene'), bx + 18, by + 40);
      ctx.font = '500 17px Arial';
      const v = String(s.visual || s.lesson || '').slice(0, 220);
      const words = v.split(/\\s+/);
      let line = '';
      let y = by + 78;
      for (const word of words) {{
        const t = line ? line + ' ' + word : word;
        if (ctx.measureText(t).width > boxW - 36 && line) {{
          ctx.fillText(line, bx + 18, y);
          line = word;
          y += 24;
          if (y > by + boxH - 16) break;
        }} else {{
          line = t;
        }}
      }}
      if (line && y <= by + boxH - 16) ctx.fillText(line, bx + 18, y);
    }}
        function drawFallbackAnimated(dt, theme) {{
            const cx = w * 0.5;
            const cy = h * 0.48;
            const bob = Math.sin(dt * 2.2) * 6;
            const arm = Math.sin(dt * 3.1) * 8;
            const head = Math.sin(dt * 1.7) * 0.08;
            ctx.save();
            ctx.translate(cx, cy + bob);
            ctx.rotate(head);
            ctx.fillStyle = '#e2e8f0';
            ctx.fillRect(-26, -10, 52, 60);
            ctx.fillStyle = theme?.accent || '#60a5fa';
            ctx.fillRect(-18, 10, 36, 40);
            ctx.fillStyle = '#fcd34d';
            ctx.beginPath(); ctx.arc(0, -28, 22, 0, Math.PI * 2); ctx.fill();
            ctx.fillStyle = '#111827';
            ctx.beginPath(); ctx.arc(-7, -30, 2.2, 0, Math.PI * 2); ctx.arc(7, -30, 2.2, 0, Math.PI * 2); ctx.fill();
            ctx.strokeStyle = '#111827'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(0, -24, 7, 0.1, Math.PI - 0.1); ctx.stroke();
            ctx.strokeStyle = '#fcd34d'; ctx.lineWidth = 6;
            ctx.beginPath(); ctx.moveTo(-22, 0); ctx.lineTo(-40, 6 + arm); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(22, 0); ctx.lineTo(40, 6 - arm); ctx.stroke();
            ctx.fillStyle = '#334155';
            ctx.beginPath(); ctx.ellipse(-12, 54, 12, 5, 0, 0, Math.PI * 2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(12, 54, 12, 5, 0, 0, Math.PI * 2); ctx.fill();
            ctx.restore();

            const tableY = h * 0.62 + Math.sin(dt * 1.3) * 2;
            ctx.fillStyle = '#6b4f34';
            ctx.fillRect(cx - 140, tableY, 280, 18);
            ctx.fillStyle = '#5a3f28';
            ctx.fillRect(cx - 120, tableY + 18, 16, 32);
            ctx.fillRect(cx + 104, tableY + 18, 16, 32);
            ctx.fillStyle = theme?.glow || '#eab308';
            ctx.beginPath(); ctx.arc(cx - 40, tableY - 10, 12, 0, Math.PI * 2); ctx.fill();
            ctx.fillStyle = theme?.accent || '#f97316';
            ctx.beginPath(); ctx.arc(cx + 30, tableY - 12, 10, 0, Math.PI * 2); ctx.fill();
        }}
    function draw(t) {{
      const s = scenes[current] || {{}};
      const theme = s.theme || {{ bg0:'#070f25', bg1:'#1d345f', accent:'#7dd3fc', glow:'#60a5fa' }};
      const elapsed = (t - sceneStart) / 1000;
      const dur = Math.max(5, Number(s.duration_sec || 10));
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, theme.bg0); g.addColorStop(1, theme.bg1);
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
            ctx.globalAlpha = 1;
      const fn = drawFns[current];
    if (fn) {{
            try {{ fn(ctx, w, h, elapsed, drawCharacter, drawCloud, drawGround, drawSpeechBubble, drawStar, drawCharacterTemplate); }} catch (e) {{ drawFallbackAnimated(elapsed, theme); }}
    }} else {{
            drawFallbackAnimated(elapsed, theme);
    }}
      // Bottom-of-canvas info bar
      const barH = 80;
      const barY = h - barH;
      ctx.fillStyle = theme.panel || 'rgba(0,0,0,0.55)';
      ctx.fillRect(0, barY, w, barH);
      ctx.fillStyle = '#ffffff';
      ctx.font = '700 20px Arial';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(String(s.heading || '').slice(0, 60), w / 2, barY + 12);
      ctx.font = '400 15px Arial';
      ctx.fillStyle = 'rgba(255,255,255,0.82)';
      ctx.fillText(String(s.caption || s.lesson || '').slice(0, 120), w / 2, barY + 40);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      // Progress bar at top
      const p = Math.max(0, Math.min(1, elapsed / dur));
      ctx.fillStyle = 'rgba(255,255,255,0.22)';
      ctx.fillRect(16, 10, w - 32, 8);
      ctx.fillStyle = theme.accent || '#7dd3fc';
      ctx.fillRect(16, 10, (w - 32) * p, 8);
      if (elapsed >= dur && scenes.length > 1) setScene(current + 1);
      requestAnimationFrame(draw);
    }}
    window.addEventListener('resize', fit);
    fit();
    initUI();
    setScene(0);
    requestAnimationFrame(draw);
  </script>
</body>
</html>"""


def generate_story_slider(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    story_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prov, key = _pick_provider_and_key(provider, provider_keys)
    options = story_options or {}
    host_character = str(options.get("host_character") or "").strip() or None
    theme = str(options.get("theme") or "").strip() or None
    raw = call_llm(
        provider=prov,
        api_key=key,
        model=model,
        system=None,
        user=_story_prompt(prompt, host_character=host_character, theme=theme),
        temperature=0.6,
        max_tokens=3000,
    )
    plan = _normalize_story_plan(_extract_json(raw), prompt)
    host_payload = _resolve_host_payload(host_character)

    draw_js_by_scene: list[str] = []
    for idx, scene in enumerate(plan["scenes"], start=1):
        try:
            logger.info("story: generating slider scene overlay %d/%d — %s", idx, len(plan["scenes"]), scene["heading"])
            draw_js = _generate_scene_draw_js(
                scene,
                provider=prov,
                api_key=key,
                model=model,
                host_character=host_character,
                theme=theme,
            )
            draw_js_by_scene.append(draw_js or "")
        except Exception:
            logger.exception(
                "story: scene overlay generation failed at index=%d heading=%s, using template-only scene",
                idx,
                scene.get("heading"),
            )
            draw_js_by_scene.append("")

    html = _build_story_slider_html(
        plan,
        host_payload=host_payload,
        draw_js_by_scene=draw_js_by_scene,
        theme=theme,
    )
    return {
        "status": "ok",
        "widget_html": html,
        "story_plan": plan,
    }
