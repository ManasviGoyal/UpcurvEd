# backend/tts/engine.py
"""Neural speech synthesis with edge-tts, plus the helpers callers need to fall back.

gTTS reads text with Google Translate's pre-neural voice, which is why generated
audio sounds robotic. edge-tts uses Microsoft Edge's neural voices, is free and
keyless, and sounds dramatically more natural.

It is also an unofficial client of an endpoint we do not control, so every caller
must keep gTTS wired up behind it. This module never falls back on its own: it
raises :class:`TTSUnavailable` and lets the caller decide, so a partially
synthesized artifact never silently mixes two engines.

Language coverage is deliberately conservative. gTTS supports far more languages
than we map voices for here, so an unmapped language raises ``TTSUnavailable``
and the caller's gTTS path handles it -- switching engines must not shrink the
set of languages the product supports.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(f"app.{__name__}")

ENGINE_ENV_VAR = "UPCURVED_TTS_ENGINE"

_DISABLED_VALUES = {"gtts", "google", "off", "none", "disabled", "0", "false"}

# An edge-tts failure can still leave a zero-length or truncated file behind, so
# anything smaller than a plausible MP3 frame is treated as a failed synthesis.
_MIN_AUDIO_BYTES = 256

_DEFAULT_TIMEOUT_SECONDS = 120.0

# Ordered neural voice pools keyed by base language.
#
# Index 0 is the narrator voice used for single-speaker podcasts. Debate roles
# take later entries (see _ROLE_ORDER) so Expert A / Expert B / Judge are
# genuinely different voices rather than one voice at different speeds, which is
# what the gTTS accent-and-slow-flag approach could only approximate.
_VOICE_POOLS: dict[str, tuple[str, ...]] = {
    "en": (
        "en-US-AriaNeural",
        "en-GB-RyanNeural",
        "en-AU-NatashaNeural",
        "en-US-ChristopherNeural",
    ),
    "es": ("es-ES-ElviraNeural", "es-MX-JorgeNeural", "es-AR-ElenaNeural", "es-US-AlonsoNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural", "fr-CA-SylvieNeural", "fr-CH-FabriceNeural"),
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural", "de-AT-IngridNeural", "de-CH-JanNeural"),
    "it": ("it-IT-ElsaNeural", "it-IT-DiegoNeural", "it-IT-IsabellaNeural"),
    "pt": ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural", "pt-PT-RaquelNeural"),
    "nl": ("nl-NL-ColetteNeural", "nl-NL-MaartenNeural", "nl-BE-DenaNeural"),
    "pl": ("pl-PL-ZofiaNeural", "pl-PL-MarekNeural"),
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "tr": ("tr-TR-EmelNeural", "tr-TR-AhmetNeural"),
    "ar": ("ar-EG-SalmaNeural", "ar-SA-HamedNeural", "ar-AE-FatimaNeural"),
    "hi": ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural"),
    "bn": ("bn-IN-TanishaaNeural", "bn-IN-BashkarNeural"),
    "ta": ("ta-IN-PallaviNeural", "ta-IN-ValluvarNeural"),
    "te": ("te-IN-ShrutiNeural", "te-IN-MohanNeural"),
    "mr": ("mr-IN-AarohiNeural", "mr-IN-ManoharNeural"),
    "gu": ("gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural"),
    "kn": ("kn-IN-SapnaNeural", "kn-IN-GaganNeural"),
    "ml": ("ml-IN-SobhanaNeural", "ml-IN-MidhunNeural"),
    "ur": ("ur-PK-UzmaNeural", "ur-PK-AsadNeural"),
    "zh": ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-TW-HsiaoChenNeural"),
    "ja": ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural"),
    "ko": ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural"),
    "id": ("id-ID-GadisNeural", "id-ID-ArdiNeural"),
    "vi": ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"),
    "th": ("th-TH-PremwadeeNeural", "th-TH-NiwatNeural"),
    "sv": ("sv-SE-SofieNeural", "sv-SE-MattiasNeural"),
    "da": ("da-DK-ChristelNeural", "da-DK-JeppeNeural"),
    "nb": ("nb-NO-PernilleNeural", "nb-NO-FinnNeural"),
    "fi": ("fi-FI-NooraNeural", "fi-FI-HarriNeural"),
    "cs": ("cs-CZ-VlastaNeural", "cs-CZ-AntoninNeural"),
    "el": ("el-GR-AthinaNeural", "el-GR-NestorasNeural"),
    "he": ("he-IL-HilaNeural", "he-IL-AvriNeural"),
    "hu": ("hu-HU-NoemiNeural", "hu-HU-TamasNeural"),
    "ro": ("ro-RO-AlinaNeural", "ro-RO-EmilNeural"),
    "uk": ("uk-UA-PolinaNeural", "uk-UA-OstapNeural"),
    "fa": ("fa-IR-DilaraNeural", "fa-IR-FaridNeural"),
    "sw": ("sw-KE-ZuriNeural", "sw-KE-RafikiNeural"),
    "fil": ("fil-PH-BlessicaNeural", "fil-PH-AngeloNeural"),
    "ms": ("ms-MY-YasminNeural", "ms-MY-OsmanNeural"),
}

# Debate roles, in the order they claim voices from a language's pool.
_ROLE_ORDER = ("host", "expert a", "expert b", "judge")

# Small prosody offsets layered on top of the voice choice. These keep roles
# distinguishable even for languages whose pool is shorter than _ROLE_ORDER and
# therefore has to reuse a voice.
_ROLE_PROSODY: dict[str, tuple[str, str]] = {
    "host": ("+0%", "+0Hz"),
    "expert a": ("-4%", "-8Hz"),
    "expert b": ("+5%", "+10Hz"),
    "judge": ("-7%", "-4Hz"),
}

_NEUTRAL_PROSODY = ("+0%", "+0Hz")


class TTSUnavailable(RuntimeError):
    """Raised when edge-tts cannot produce audio and the caller should fall back."""


def edge_enabled() -> bool:
    """Return whether edge-tts should be attempted before gTTS.

    Set ``UPCURVED_TTS_ENGINE=gtts`` to force the legacy engine, which is useful
    for offline test runs and for users on networks that block the Edge endpoint.
    """
    value = (os.environ.get(ENGINE_ENV_VAR) or "").strip().lower()
    return value not in _DISABLED_VALUES


def normalize_lang(lang: str | None) -> str:
    """Reduce a gTTS-style language code to the base key used by _VOICE_POOLS."""
    code = (lang or "en").strip().lower().replace("_", "-")
    if not code:
        return "en"
    if code.startswith("zh"):
        return "zh"
    if code.startswith("fil") or code.startswith("tl"):
        return "fil"
    return code.split("-")[0] or "en"


def _normalize_role(role: str | None) -> str | None:
    value = (role or "").strip().lower()
    return value or None


def voice_for(lang: str | None, role: str | None = None) -> str | None:
    """Return the neural voice for a language/speaker, or None if unmapped.

    None means "we have no neural voice for this language" -- the caller should
    use gTTS rather than reading foreign text with an English voice.
    """
    pool = _VOICE_POOLS.get(normalize_lang(lang))
    if not pool:
        return None
    normalized = _normalize_role(role)
    if normalized in _ROLE_ORDER:
        return pool[_ROLE_ORDER.index(normalized) % len(pool)]
    return pool[0]


def prosody_for(role: str | None) -> tuple[str, str]:
    """Return the (rate, pitch) offsets for a debate role."""
    return _ROLE_PROSODY.get(_normalize_role(role) or "", _NEUTRAL_PROSODY)


def _run_coro(coro):
    """Run a coroutine whether or not the caller already has a running loop.

    generate_podcast is sync today but is reached from FastAPI request handlers,
    so asyncio.run() can land inside an active loop and raise. Falling back to a
    dedicated thread keeps this callable from either context.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, object] = {}

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread
            box["error"] = exc

    thread = threading.Thread(target=_worker, name="edge-tts", daemon=True)
    thread.start()
    thread.join()
    error = box.get("error")
    if error is not None:
        raise error  # type: ignore[misc]
    return box.get("value")


def _word_boundaries_from_chunks(
    text: str,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert edge-tts WordBoundary events into manim-voiceover's WordBoundary shape.

    edge-tts reports ``offset``/``duration`` in 100-nanosecond ticks, which is already the unit
    manim-voiceover's ``AUDIO_OFFSET_RESOLUTION`` divides by. It does not report where the word sat
    in the input, so ``text_offset`` is recovered by walking the source text and consuming each
    spoken word in order -- the voice speaks the words in sequence, so a forward-only scan cannot
    mismatch, and a word the scan cannot locate (an expanded number, say) is skipped rather than
    guessed at.
    """
    boundaries: list[dict[str, Any]] = []
    cursor = 0
    for chunk in chunks:
        spoken = str(chunk.get("text") or "")
        if not spoken:
            continue
        found = text.find(spoken, cursor)
        if found < 0:
            continue
        cursor = found + len(spoken)
        boundaries.append(
            {
                "audio_offset": int(chunk.get("offset") or 0),
                "duration_milliseconds": int(float(chunk.get("duration") or 0) / 10_000),
                "text_offset": found,
                "word_length": len(spoken),
                "text": spoken,
                "boundary_type": "Word",
            }
        )
    return boundaries


def synthesize_edge(
    text: str,
    out_path: str | Path,
    *,
    lang: str = "en",
    role: str | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    word_boundaries: list[dict[str, Any]] | None = None,
) -> str:
    """Synthesize ``text`` to an MP3 at ``out_path`` and return the voice used.

    Raises TTSUnavailable for every failure mode -- disabled, not installed,
    unmapped language, network error, or empty output -- so callers can treat
    "use gTTS instead" as a single except branch.

    When ``word_boundaries`` is supplied it is filled in place with per-word audio timings. They
    are what makes a caption land on the pause the voice actually took: without them the only
    timing signal is the total duration, and callers have to assume a constant speech rate.
    """
    if not (text or "").strip():
        raise TTSUnavailable("Refusing to synthesize empty text.")

    if not edge_enabled():
        raise TTSUnavailable(f"edge-tts disabled via {ENGINE_ENV_VAR}.")

    voice = voice_for(lang, role)
    if not voice:
        raise TTSUnavailable(f"No edge-tts voice mapped for language '{lang}'.")

    try:
        import edge_tts
    except ImportError as exc:
        raise TTSUnavailable("edge-tts is not installed.") from exc

    rate, pitch = prosody_for(role)
    destination = Path(out_path)
    collected: list[dict[str, Any]] = []

    async def _synthesize() -> None:
        # Boundary metadata is opt-in: Communicate defaults to "SentenceBoundary", which makes the
        # service send no per-word events at all. Older edge-tts builds have no such parameter, so
        # fall back to the default and let the caller cope with an empty timing list.
        try:
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, pitch=pitch, boundary="WordBoundary"
            )
        except TypeError:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

        async def _stream() -> None:
            # stream() rather than save(): save() discards the boundary events entirely.
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                async for chunk in communicate.stream():
                    kind = chunk.get("type")
                    if kind == "audio" and chunk.get("data"):
                        handle.write(chunk["data"])
                    elif kind in ("WordBoundary", "SentenceBoundary"):
                        # Sentence events are accepted too: coarser, but still anchored to real
                        # audio, which is what keeps a caption off the narrator's pauses.
                        collected.append(dict(chunk))

        await asyncio.wait_for(_stream(), timeout=timeout_seconds)

    try:
        _run_coro(_synthesize())
    except Exception as exc:
        _discard(destination)
        detail = str(exc) or type(exc).__name__
        raise TTSUnavailable(f"edge-tts synthesis failed ({detail}).") from exc

    if not destination.exists() or destination.stat().st_size < _MIN_AUDIO_BYTES:
        _discard(destination)
        raise TTSUnavailable("edge-tts returned no audio.")

    if word_boundaries is not None:
        word_boundaries.extend(_word_boundaries_from_chunks(text, collected))

    return voice


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
