# backend/tts/__init__.py
"""Speech synthesis engines shared by UpcurvEd artifact generators."""

from backend.tts.engine import (
    ENGINE_ENV_VAR,
    TTSUnavailable,
    edge_enabled,
    normalize_lang,
    synthesize_edge,
    voice_for,
)

__all__ = [
    "ENGINE_ENV_VAR",
    "TTSUnavailable",
    "edge_enabled",
    "normalize_lang",
    "synthesize_edge",
    "voice_for",
]
