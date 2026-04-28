import logging
import re
from tempfile import NamedTemporaryFile

from gtts import gTTS
from langdetect import detect

from backend.agent.llm.clients import call_llm
from backend.runner.job_runner import STORAGE, to_static_url

# Import to trigger app-level logging configuration (handlers, format, level).
from backend.utils import app_logging  # noqa: F401

logger = logging.getLogger(f"app.{__name__}")

WELCOME_PREFIX = "welcome to upcurved podcasts"


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


def _podcast_prompt(user_prompt: str, mode: str = "standard") -> str:
    low_mode = (mode or "standard").strip().lower()
    if low_mode == "debate":
        return f"""
You are writing a structured educational debate podcast script.
Let the script be in the language implied by the user's prompt.

IMPORTANT: You MUST start with this greeting (translated to the same language):
'Welcome to UpCurved Podcasts, where we take big ideas and curve them upwards
into simple, fun explanations. Today's episode: [GENERATE A SIMPLE, DIRECT
TITLE FOR THIS EPISODE BASED ON THE TOPIC]. Let's turn complexity into
curiosity!'

Debate format rules:
1) Introduce the topic in 2-3 lines.
2) Expert A gives argument for Viewpoint 1.
3) Expert B gives argument for Viewpoint 2.
4) Include one direct rebuttal round each (A rebuts B, B rebuts A).
5) End with a Judge Summary section that compares both sides, clarifies what is correct,
   and gives a practical takeaway for learners.
6) Target spoken duration MUST be between 2 and 3 minutes total.
7) Keep total script length around 320-450 words so TTS lands near 2-3 minutes.

Style rules:
- Keep it educational, clear, and balanced.
- Keep labels explicit in plain text: "Host:", "Expert A:", "Expert B:", "Judge:".
- No markdown, JSON, code blocks, stage directions, music cues, or SFX.
- Do not end abruptly.

Topic: {user_prompt}
"""


def _episode_title_from_prompt(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", (prompt or "").strip())
    cleaned = re.sub(r"[^A-Za-z0-9 \-]", "", cleaned).strip()
    if not cleaned:
        return "Learning Essentials"
    words = cleaned.split()
    return " ".join(words[:5]).strip()


def _ensure_debate_greeting(script: str, user_prompt: str) -> str:
    txt = (script or "").strip()
    if not txt:
        return txt
    head = txt[:500].lower()
    if WELCOME_PREFIX in head:
        return txt
    title = _episode_title_from_prompt(user_prompt)
    greeting = (
        "Host: Welcome to UpCurved Podcasts, where we take big ideas and curve them upwards "
        f"into simple, fun explanations. Today's episode: {title}. "
        "Let's turn complexity into curiosity!"
    )
    return f"{greeting}\n\n{txt}"
    return f"""
You are a skilled podcast writer and narrator.
Write a concise but engaging single-speaker podcast script for the following topic.
Let the script be in the language implied by the user's prompt.

IMPORTANT: You MUST start the script with this exact greeting (translate it to
match the language of the user's prompt):

'Welcome to UpCurved Podcasts, where we take big ideas and curve them upwards
into simple, fun explanations. Today's episode: [GENERATE A SIMPLE, DIRECT
TITLE FOR THIS EPISODE BASED ON THE TOPIC]. Let's turn complexity into
curiosity!'

Replace [GENERATE A SIMPLE, DIRECT TITLE FOR THIS EPISODE BASED ON THE TOPIC]
with a straightforward title that directly describes the topic. Keep it simple
and clear (ideally 2-5 words). Examples: 'Reinforcement Learning', 'Quantum
Mechanics Explained', 'Understanding Photosynthesis'. Avoid overly creative or
metaphorical titles.

After the greeting, continue with the main podcast content.
Keep it natural, conversational, and structured with main points and a brief
closing.
Avoid markdown, JSON, or code blocks; return plain text only.
Do NOT include stage directions, music cues, or SFX like 'upbeat intro', 'fade
in', 'fade out', or '[music]'.
Do NOT include speaker labels; write only the spoken content.
Do NOT end the script abruptly. Generate entire script.

Topic: {user_prompt}
"""


def _infer_gtts_lang(script_text: str) -> str:
    """Infer a gTTS language code from script text using langdetect with sane fallbacks."""
    try:
        code = detect(script_text or "")
    except Exception:
        return "en"
    code = (code or "en").lower()
    # Map common variants for gTTS compatibility
    if code.startswith("zh"):
        return "zh-cn"
    if code in {"pt-br", "pt_pt"}:
        return "pt"
    return code


def _split_sentences(text: str) -> list[str]:
    # Simple sentence splitter by punctuation/newlines
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p and not p.isspace()]


def _format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = int(seconds) // 60
    h = m // 60
    m = m % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _make_srt(script_text: str, words_per_sec: float = 2.5) -> str:
    """Generate naive SRT by assigning durations per sentence based on word count."""
    sents = _split_sentences(script_text)
    out_lines = []
    t = 0.0
    idx = 1
    for s in sents:
        wc = max(1, len(s.split()))
        dur = max(1.2, wc / max(0.5, words_per_sec))
        start = _format_ts(t)
        end = _format_ts(t + dur)
        out_lines.append(str(idx))
        out_lines.append(f"{start} --> {end}")
        out_lines.append(s)
        out_lines.append("")
        t += dur
        idx += 1
    return "\n".join(out_lines).strip() + "\n"


def _srt_to_vtt(srt_text: str) -> str:
    """Convert basic SRT to WebVTT: add header and switch comma milliseconds to dot.
    Note: This is a naive converter that assumes valid SRT timing lines.
    """
    # Replace 00:00:01,000 --> 00:00:03,000 with 00:00:01.000 --> 00:00:03.000
    vtt_body = re.sub(
        r"^(\d{2}:\d{2}:\d{2}),(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}),(\d{3})",
        r"\1.\2 --> \3.\4",
        srt_text,
        flags=re.MULTILINE,
    )
    # Remove SRT cue indices (standalone lines with only digits)
    vtt_lines = []
    for line in vtt_body.splitlines():
        if re.match(r"^\s*\d+\s*$", line):
            continue
        vtt_lines.append(line)
    return "WEBVTT\n\n" + "\n".join(vtt_lines).strip() + "\n"


def _make_srt_proportional(script_text: str, total_seconds: float, min_per_cue: float = 0.8) -> str:
    """
    Distribute caption cue durations across the total audio length proportionally
    to sentence length. This better matches speaking speed for the synthesized
    audio, without needing phoneme timestamps.
    """
    sents = _split_sentences(script_text)
    if not sents:
        return ""
    # Weight by word count; small bonus for punctuation that usually implies pauses
    weights = []
    for s in sents:
        wc = max(1, len(s.split()))
        pauses = len(re.findall(r"[,:;]", s))
        weights.append(wc + 0.5 * pauses)
    total_w = sum(weights) or 1.0

    # Initial proportional durations
    raw = [(w / total_w) * max(0.0, float(total_seconds)) for w in weights]
    durations = [max(min_per_cue, d) for d in raw]

    sum_d = sum(durations)
    T = max(0.0, float(total_seconds))
    if sum_d > 0 and T > 0 and sum_d != T:
        if sum_d > T:
            # Reduce proportionally from the part above the minimums
            reducible = [max(0.0, d - min_per_cue) for d in durations]
            sum_reducible = sum(reducible)
            over = sum_d - T
            if sum_reducible > 0:
                durations = [
                    d - over * (max(0.0, d - min_per_cue) / sum_reducible) for d in durations
                ]
            else:
                # Edge case: everything at min; spread evenly
                durations = [T / len(durations) for _ in durations]
        else:
            # Under-filled (rare); distribute extra evenly
            under = T - sum_d
            add = under / len(durations)
            durations = [d + add for d in durations]

    # Build cues
    out_lines = []
    t = 0.0
    for idx, (s, d) in enumerate(zip(sents, durations, strict=False), start=1):
        start = _format_ts(t)
        # Ensure last cue ends exactly at total
        if idx == len(sents):
            end_ts = T
        else:
            end_ts = t + max(0.0, d)
        end = _format_ts(end_ts)
        out_lines.append(str(idx))
        out_lines.append(f"{start} --> {end}")
        out_lines.append(s)
        out_lines.append("")
        t = end_ts
    return "\n".join(out_lines).strip() + "\n"


def _parse_labeled_debate_segments(script_text: str) -> list[tuple[str, str]]:
    """
    Parse labeled dialogue lines like:
      Host: ...
      Expert A: ...
      Expert B: ...
      Judge: ...
    Returns ordered (speaker, text) chunks.
    """
    lines = [ln.strip() for ln in (script_text or "").splitlines() if ln.strip()]
    segments: list[tuple[str, str]] = []
    current_speaker = None
    buffer: list[str] = []
    label_re = re.compile(r"^(Host|Expert A|Expert B|Judge)\s*:\s*(.*)$", re.IGNORECASE)

    def flush():
        nonlocal current_speaker, buffer
        if current_speaker and buffer:
            text = " ".join(buffer).strip()
            if text:
                segments.append((current_speaker, text))
        current_speaker = None
        buffer = []

    for ln in lines:
        m = label_re.match(ln)
        if m:
            flush()
            current_speaker = m.group(1).title()
            first_text = (m.group(2) or "").strip()
            if first_text:
                buffer.append(first_text)
            continue
        if current_speaker:
            buffer.append(ln)
    flush()
    return segments


def _voice_kwargs_for_speaker(speaker: str, lang: str) -> dict:
    """
    Build gTTS kwargs for each speaker so Expert A / Expert B sound distinct.
    For English we vary region voice; for other languages we vary speed.
    """
    sp = (speaker or "").strip().lower()
    kwargs = {"lang": lang, "slow": False}
    if lang.startswith("en"):
        if sp == "expert a":
            kwargs["tld"] = "co.uk"
            kwargs["slow"] = False
        elif sp == "expert b":
            kwargs["tld"] = "com.au"
            kwargs["slow"] = True
        elif sp == "judge":
            kwargs["tld"] = "co.in"
            kwargs["slow"] = False
        else:  # host/default
            kwargs["tld"] = "com"
            kwargs["slow"] = False
    else:
        if sp == "expert b":
            kwargs["slow"] = True
    return kwargs


def _synthesize_debate_multivoice(script: str, lang: str, out_mp3_path) -> None:
    """
    Synthesize debate script with distinct voices for Expert A and Expert B,
    then concatenate into a single mp3.
    """
    segments = _parse_labeled_debate_segments(script)
    if len(segments) < 4:
        raise RuntimeError("Debate script did not include enough labeled dialogue segments.")
    if not any(sp.lower() == "expert a" for sp, _ in segments):
        raise RuntimeError("Debate script missing Expert A lines.")
    if not any(sp.lower() == "expert b" for sp, _ in segments):
        raise RuntimeError("Debate script missing Expert B lines.")

    from pydub import AudioSegment

    merged = AudioSegment.silent(duration=0)
    gap = AudioSegment.silent(duration=180)
    temp_files = []
    try:
        for speaker, text in segments:
            if not text.strip():
                continue
            with NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                temp_files.append(tmp.name)
                tts_kwargs = _voice_kwargs_for_speaker(speaker, lang)
                try:
                    gTTS(text=text, **tts_kwargs).save(tmp.name)
                except Exception:
                    # Fallback voice per segment if region/speed combo unsupported.
                    gTTS(text=text, lang=lang).save(tmp.name)
            clip = AudioSegment.from_file(temp_files[-1], format="mp3")
            merged += clip + gap
        merged.export(str(out_mp3_path), format="mp3")
    finally:
        from pathlib import Path as _Path

        for p in temp_files:
            try:
                _Path(p).unlink(missing_ok=True)
            except Exception:
                pass


def generate_podcast(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    provider_keys: dict[str, str] | None = None,
    mode: str = "standard",
    job_id: str | None = None,
) -> dict[str, str]:
    """
    Generate a podcast script from LLM, TTS to mp3 with language inferred via
    langdetect, and produce a naive SRT caption file. Returns {status, job_id,
    video_url} where video_url points to the mp3.
    """
    # Resolve provider/key
    prov, api_key = _pick_provider_and_key(provider, provider_keys)
    # Generate script
    logger.info("podcast: calling LLM provider=%s model=%s", prov, model)
    script = call_llm(
        provider=prov,
        api_key=api_key,
        model=model,
        system=None,
        user=_podcast_prompt(prompt, mode=mode),
        temperature=0.5,  # Higher temperature for more natural, varied dialogue
    )
    if not script or not script.strip():
        raise RuntimeError("LLM returned empty script")
    if (mode or "standard").strip().lower() == "debate":
        script = _ensure_debate_greeting(script, prompt)

    # Detect language for TTS
    lang = _infer_gtts_lang(script)
    logger.info("podcast: detected language=%s", lang)

    # Prepare output dirs
    from uuid import uuid4

    job_id = job_id or str(uuid4())[:8]
    job_dir = STORAGE / "jobs" / job_id
    out_dir = job_dir / "out"
    logs_dir = job_dir / "logs"
    for d in (job_dir, out_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    mode_norm = (mode or "standard").strip().lower()

    # Synthesize audio
    mp3_path = job_dir / "podcast.mp3"
    try:
        if mode_norm == "debate":
            logger.info("podcast: synthesizing debate multi-voice mp3 (lang=%s)", lang)
            _synthesize_debate_multivoice(script, lang, mp3_path)
        else:
            logger.info("podcast: synthesizing TTS mp3 (lang=%s)", lang)
            tts = gTTS(text=script, lang=lang)
            tts.save(str(mp3_path))
    except Exception as e:
        # Retry once with English (or fallback single-voice for debate) if TTS fails.
        msg = str(e) if str(e) else type(e).__name__
        logger.warning(
            "podcast: TTS failed with lang=%s mode=%s: %s; retrying fallback",
            lang,
            mode_norm,
            msg,
        )
        try:
            if mode_norm == "debate":
                _synthesize_debate_multivoice(script, "en", mp3_path)
                logger.info("podcast: debate fallback multi-voice synthesis in 'en' succeeded")
            else:
                tts = gTTS(text=script, lang="en")
                tts.save(str(mp3_path))
                logger.info("podcast: gTTS fallback to 'en' succeeded")
        except Exception as e2:
            logger.warning("podcast: fallback TTS failed (%s), trying final single-voice 'en'", e2)
            try:
                tts = gTTS(text=script, lang="en")
                tts.save(str(mp3_path))
                logger.info("podcast: final single-voice fallback succeeded")
            except Exception as e3:
                logger.exception("podcast: final TTS fallback failed: %s", e3)
                raise RuntimeError(f"TTS failed: {msg}; fallback failed: {e3}") from e3

    # After audio is created, measure duration and build SRT/VTT to match speaking speed
    srt_path = job_dir / "podcast.srt"
    vtt_path = job_dir / "podcast.vtt"
    total_secs: float | None = None
    try:
        from mutagen.mp3 import MP3

        audio = MP3(str(mp3_path))
        total_secs = float(getattr(audio.info, "length", 0.0) or 0.0)
        logger.info("podcast: mp3 duration detected: %.2fs", total_secs)
    except Exception as e:
        logger.warning("podcast: failed to read mp3 duration for alignment: %s", e)

    try:
        if total_secs and total_secs > 0.0:
            srt_text = _make_srt_proportional(script, total_secs)
        else:
            srt_text = _make_srt(script)
        srt_path.write_text(srt_text, encoding="utf-8")
        vtt_text = _srt_to_vtt(srt_text)
        vtt_path.write_text(vtt_text, encoding="utf-8")
    except Exception as e:
        logger.exception("podcast: failed to generate SRT/VTT: %s", e)

    return {
        "status": "ok",
        "job_id": job_id,
        # Reuse existing frontend field name to avoid wider changes
        "video_url": to_static_url(mp3_path),
        "srt_url": to_static_url(srt_path),
        "vtt_url": to_static_url(vtt_path),
        "lang": lang,
        "script": script,  # Fallback for quiz when VTT unavailable
    }
