# backend/tts/manim_service.py
"""A manim-voiceover SpeechService backed by edge-tts, falling back to gTTS.

Generated scenes are sanitized to import this as ``EdgeTTSService as GTTSService``
so the model can keep emitting the manim-voiceover idiom it knows while the
narration actually uses neural voices.

Unlike the podcast path, this falls back per utterance instead of aborting: a
render costs an LLM call plus minutes of Manim time, so one failed segment must
not throw that away. The engine choice is latched after the first failure so a
sustained outage does not retry edge-tts on every line.
"""
from __future__ import annotations

from pathlib import Path

from manim_voiceover._typing import VoiceoverData
from manim_voiceover.helper import remove_bookmarks
from manim_voiceover.services.base import (
    PathLike,
    SpeechService,
    initialize_speech_service,
    path_to_string,
)

from backend.tts.engine import TTSUnavailable, synthesize_edge, voice_for

try:  # pragma: no cover - exercised only when manim actually renders
    from manim import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("app.backend.tts.manim_service")


class EdgeTTSService(SpeechService):
    """Speech service using Microsoft Edge neural voices, with a gTTS fallback.

    The constructor mirrors ``GTTSService`` (``lang`` / ``tld``) so sanitized
    scene code needs no changes beyond the import line.
    """

    def __init__(
        self,
        lang: str = "en",
        tld: str = "com",
        voice: str | None = None,
        **kwargs: object,
    ) -> None:
        initialize_speech_service(self, kwargs)
        self.lang = lang
        # Accepted for GTTSService signature compatibility; only the gTTS
        # fallback can act on a top level domain.
        self.tld = tld
        self.voice = voice
        self._edge_available = True

    def _resolved_voice(self) -> str | None:
        return self.voice or voice_for(self.lang)

    def generate_from_text(
        self,
        text: str,
        cache_dir: PathLike | None = None,
        path: PathLike | None = None,
        **kwargs: object,
    ) -> VoiceoverData:
        if cache_dir is None:
            cache_dir = self.cache_dir

        input_text = remove_bookmarks(text)
        voice = self._resolved_voice()

        # The cache key records the engine, so switching engines invalidates old
        # audio instead of silently replaying it.
        edge_key = {"input_text": input_text, "service": "edge-tts", "voice": voice}
        gtts_key = {"input_text": input_text, "service": "gtts", "lang": self.lang}
        input_data = edge_key if (voice and self._edge_available) else gtts_key

        cached_result = self.get_cached_result(input_data, cache_dir)
        if cached_result is not None:
            return cached_result

        if path is None:
            audio_path = self.get_audio_basename(input_data) + ".mp3"
        else:
            audio_path = path_to_string(path)
        destination = Path(cache_dir) / audio_path

        used_edge = False
        if voice and self._edge_available:
            try:
                synthesize_edge(input_text, destination, lang=self.lang)
                used_edge = True
            except TTSUnavailable as exc:
                # Latch off so the rest of the render does not re-attempt a
                # service that is blocked or down.
                self._edge_available = False
                logger.warning(f"edge-tts unavailable ({exc}); narrating with gTTS instead")

        if not used_edge:
            self._synthesize_gtts(input_text, destination)
            # Re-key so a transient outage does not cache gTTS audio under the
            # edge-tts key and poison later renders.
            input_data = gtts_key
            if path is None:
                audio_path = self._recache(destination, cache_dir, input_data)

        return {
            "input_text": text,
            "input_data": input_data,
            "original_audio": audio_path,
        }

    def _synthesize_gtts(self, input_text: str, destination: Path) -> None:
        from gtts import gTTS

        try:
            gTTS(input_text, lang=self.lang, tld=self.tld).save(str(destination))
        except Exception:
            # Mirror GTTSService's own last resort: drop the regional domain.
            gTTS(input_text, lang=self.lang).save(str(destination))

    def _recache(self, destination: Path, cache_dir: PathLike, input_data: dict) -> str:
        """Rename an already written file to match the gTTS cache key."""
        renamed = self.get_audio_basename(input_data) + ".mp3"
        target = Path(cache_dir) / renamed
        if target != destination:
            try:
                destination.replace(target)
            except OSError:
                return path_to_string(destination.name)
        return renamed
