# tests/unit/test_tts_engine.py
"""Tests for the edge-tts engine and its gTTS fallback contract."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.tts import engine


@pytest.fixture(autouse=True)
def enable_edge(monkeypatch):
    """conftest pins the suite to gTTS; these tests exercise the edge path."""
    monkeypatch.setenv(engine.ENGINE_ENV_VAR, "edge")


class TestEngineToggle:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv(engine.ENGINE_ENV_VAR, raising=False)
        assert engine.edge_enabled() is True

    @pytest.mark.parametrize("value", ["gtts", "GTTS", "off", "none", "disabled", "0", "false"])
    def test_disable_values(self, monkeypatch, value):
        monkeypatch.setenv(engine.ENGINE_ENV_VAR, value)
        assert engine.edge_enabled() is False


class TestNormalizeLang:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("en", "en"),
            ("en-US", "en"),
            ("EN_us", "en"),
            ("zh-cn", "zh"),
            ("zh-TW", "zh"),
            ("pt", "pt"),
            ("tl", "fil"),
            ("", "en"),
            (None, "en"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert engine.normalize_lang(raw) == expected


class TestVoiceFor:
    def test_narrator_uses_first_voice(self):
        assert engine.voice_for("en") == "en-US-AriaNeural"

    def test_debate_roles_are_distinct(self):
        roles = ["Host", "Expert A", "Expert B", "Judge"]
        voices = [engine.voice_for("en", role) for role in roles]
        assert len(set(voices)) == len(roles)

    def test_role_lookup_is_case_insensitive(self):
        assert engine.voice_for("en", "EXPERT A") == engine.voice_for("en", "expert a")

    def test_unknown_role_falls_back_to_narrator(self):
        assert engine.voice_for("en", "Narrator") == engine.voice_for("en")

    def test_short_pool_wraps_without_error(self):
        # Hindi has two voices but four roles; wrapping must not raise.
        voices = [engine.voice_for("hi", r) for r in ("host", "expert a", "expert b", "judge")]
        assert all(v and v.startswith("hi-IN-") for v in voices)

    def test_unmapped_language_returns_none(self):
        """gTTS covers far more languages, so unmapped must defer rather than
        read foreign text with an English voice."""
        assert engine.voice_for("mt") is None

    def test_short_pool_roles_differ_by_prosody(self):
        assert engine.prosody_for("expert a") != engine.prosody_for("expert b")


class TestSynthesizeEdge:
    def test_rejects_empty_text(self, tmp_path):
        with pytest.raises(engine.TTSUnavailable, match="empty text"):
            engine.synthesize_edge("   ", tmp_path / "out.mp3")

    def test_raises_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv(engine.ENGINE_ENV_VAR, "gtts")
        with pytest.raises(engine.TTSUnavailable, match="disabled"):
            engine.synthesize_edge("hello", tmp_path / "out.mp3")

    def test_raises_for_unmapped_language(self, tmp_path):
        with pytest.raises(engine.TTSUnavailable, match="No edge-tts voice"):
            engine.synthesize_edge("hello", tmp_path / "out.mp3", lang="mt")

    def test_missing_package_raises_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "edge_tts", None)
        with patch.dict(sys.modules):
            del sys.modules["edge_tts"]
            monkeypatch.setattr(
                "builtins.__import__",
                _import_raiser("edge_tts"),
            )
            with pytest.raises(engine.TTSUnavailable, match="not installed"):
                engine.synthesize_edge("hello", tmp_path / "out.mp3")

    def test_successful_synthesis_returns_voice(self, tmp_path, monkeypatch):
        out = tmp_path / "out.mp3"
        module = _fake_edge_tts(out, payload=b"\x00" * 4096)
        monkeypatch.setitem(sys.modules, "edge_tts", module)

        voice = engine.synthesize_edge("hello there", out, lang="en", role="Expert B")

        assert voice == engine.voice_for("en", "Expert B")
        assert out.exists()
        rate, pitch = engine.prosody_for("Expert B")
        assert module.calls == [("hello there", voice, rate, pitch)]

    def test_empty_output_is_treated_as_failure(self, tmp_path, monkeypatch):
        out = tmp_path / "out.mp3"
        monkeypatch.setitem(sys.modules, "edge_tts", _fake_edge_tts(out, payload=b""))

        with pytest.raises(engine.TTSUnavailable, match="no audio"):
            engine.synthesize_edge("hello", out)
        assert not out.exists()

    def test_network_error_is_wrapped(self, tmp_path, monkeypatch):
        out = tmp_path / "out.mp3"
        monkeypatch.setitem(
            sys.modules, "edge_tts", _fake_edge_tts(out, error=OSError("connection reset"))
        )

        with pytest.raises(engine.TTSUnavailable, match="connection reset"):
            engine.synthesize_edge("hello", out)

    def test_works_from_inside_a_running_event_loop(self, tmp_path, monkeypatch):
        """generate_podcast is sync but reachable from async request handlers."""
        import asyncio

        out = tmp_path / "out.mp3"
        monkeypatch.setitem(sys.modules, "edge_tts", _fake_edge_tts(out, payload=b"\x00" * 4096))

        async def _driver():
            return engine.synthesize_edge("hello", out)

        assert asyncio.run(_driver()) == engine.voice_for("en")

    def test_word_boundaries_must_be_requested_explicitly(self, tmp_path, monkeypatch):
        """Communicate defaults to SentenceBoundary, which sends no per-word events at all."""
        out = tmp_path / "out.mp3"
        module = _fake_edge_tts(out, payload=b"\x00" * 4096)
        monkeypatch.setitem(sys.modules, "edge_tts", module)

        engine.synthesize_edge("hello there", out)

        assert module.kwargs_seen[0].get("boundary") == "WordBoundary"

    def test_collected_boundaries_are_returned_to_the_caller(self, tmp_path, monkeypatch):
        out = tmp_path / "out.mp3"
        module = _fake_edge_tts(
            out,
            payload=b"\x00" * 4096,
            boundaries=[
                {"type": "WordBoundary", "offset": 0, "duration": 3_000_000, "text": "hello"},
                {
                    "type": "WordBoundary",
                    "offset": 30_000_000,
                    "duration": 2_000_000,
                    "text": "there",
                },
            ],
        )
        monkeypatch.setitem(sys.modules, "edge_tts", module)

        collected: list[dict] = []
        engine.synthesize_edge("hello there", out, word_boundaries=collected)

        assert [b["text"] for b in collected] == ["hello", "there"]
        assert [b["text_offset"] for b in collected] == [0, 6]
        assert collected[1]["audio_offset"] == 30_000_000

    def test_sentence_boundaries_are_accepted_too(self, tmp_path, monkeypatch):
        out = tmp_path / "out.mp3"
        module = _fake_edge_tts(
            out,
            payload=b"\x00" * 4096,
            boundaries=[
                {
                    "type": "SentenceBoundary",
                    "offset": 0,
                    "duration": 9_000_000,
                    "text": "hello there",
                },
            ],
        )
        monkeypatch.setitem(sys.modules, "edge_tts", module)

        collected: list[dict] = []
        engine.synthesize_edge("hello there", out, word_boundaries=collected)

        assert [b["text"] for b in collected] == ["hello there"]

    def test_older_edge_tts_without_boundary_kwarg_still_synthesizes(self, tmp_path, monkeypatch):
        out = tmp_path / "out.mp3"
        module = _fake_edge_tts(
            out, payload=b"\x00" * 4096, reject_boundary_kwarg=True
        )
        monkeypatch.setitem(sys.modules, "edge_tts", module)

        collected: list[dict] = []
        voice = engine.synthesize_edge("hello there", out, word_boundaries=collected)

        assert voice == engine.voice_for("en")
        assert out.exists()
        assert collected == []


def _import_raiser(blocked: str):
    real_import = __import__

    def _fake(name, *args, **kwargs):
        if name == blocked:
            raise ImportError(f"No module named '{blocked}'")
        return real_import(name, *args, **kwargs)

    return _fake


def _fake_edge_tts(
    out_path,
    *,
    payload: bytes = b"",
    error: Exception | None = None,
    boundaries: list[dict] | None = None,
    reject_boundary_kwarg: bool = False,
):
    """Build a stand-in edge_tts module recording Communicate(...) arguments.

    Mirrors the real ``stream()`` API rather than ``save()``: synthesize_edge streams so it can
    collect the boundary metadata that ``save()`` throws away.
    """
    calls: list[tuple[str, str, str, str]] = []
    kwargs_seen: list[dict] = []

    class Communicate:
        def __init__(self, text, voice, rate="+0%", pitch="+0Hz", **kwargs):
            if reject_boundary_kwarg and "boundary" in kwargs:
                raise TypeError("unexpected keyword argument 'boundary'")
            calls.append((text, voice, rate, pitch))
            kwargs_seen.append(dict(kwargs))

        async def stream(self):
            if error is not None:
                raise error
            if payload:
                yield {"type": "audio", "data": payload}
            for boundary in boundaries or []:
                yield boundary

    module = SimpleNamespace(Communicate=Communicate)
    module.calls = calls
    module.kwargs_seen = kwargs_seen
    return module


class TestPodcastIntegration:
    """The podcast path must prefer edge-tts and fall back cleanly."""

    def test_single_voice_prefers_edge(self, tmp_path, monkeypatch):
        from backend.mcp import podcast_logic

        out = tmp_path / "podcast.mp3"
        monkeypatch.setattr(
            podcast_logic.tts_engine, "synthesize_edge", MagicMock(return_value="en-US-AriaNeural")
        )
        fake_gtts = MagicMock()
        monkeypatch.setattr(podcast_logic, "gTTS", fake_gtts)

        podcast_logic._synthesize_single_voice("hello", "en", out)

        fake_gtts.assert_not_called()

    def test_single_voice_falls_back_to_gtts(self, tmp_path, monkeypatch):
        from backend.mcp import podcast_logic

        out = tmp_path / "podcast.mp3"
        monkeypatch.setattr(
            podcast_logic.tts_engine,
            "synthesize_edge",
            MagicMock(side_effect=engine.TTSUnavailable("blocked")),
        )
        fake_gtts = MagicMock()
        monkeypatch.setattr(podcast_logic, "gTTS", fake_gtts)

        podcast_logic._synthesize_single_voice("hello", "en", out)

        fake_gtts.assert_called_once_with(text="hello", lang="en")

    def test_gtts_errors_propagate_to_the_outer_retry_ladder(self, tmp_path, monkeypatch):
        from backend.mcp import podcast_logic

        monkeypatch.setattr(
            podcast_logic.tts_engine,
            "synthesize_edge",
            MagicMock(side_effect=engine.TTSUnavailable("blocked")),
        )
        monkeypatch.setattr(podcast_logic, "gTTS", MagicMock(side_effect=ValueError("bad lang")))

        with pytest.raises(ValueError, match="bad lang"):
            podcast_logic._synthesize_single_voice("hello", "xx", tmp_path / "out.mp3")
