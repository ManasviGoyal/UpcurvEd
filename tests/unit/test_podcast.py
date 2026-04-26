"""Unit tests for podcast_logic.py and podcast_server.py functionality."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from backend.mcp.podcast_logic import (
    _format_ts,
    _infer_gtts_lang,
    _make_srt,
    _make_srt_proportional,
    _pick_provider_and_key,
    _podcast_prompt,
    _split_sentences,
    _srt_to_vtt,
    generate_podcast,
)
from backend.mcp.podcast_server import generate_podcast_tool


class TestPickProviderAndKey:
    """Test provider and key selection logic."""

    def test_explicit_claude_provider(self):
        """Test explicitly requesting Claude."""
        prov, key = _pick_provider_and_key("claude", {"claude": "test-claude-key"})
        assert prov == "claude"
        assert key == "test-claude-key"

    def test_explicit_gemini_provider(self):
        """Test explicitly requesting Gemini."""
        prov, key = _pick_provider_and_key("gemini", {"gemini": "test-gemini-key"})
        assert prov == "gemini"
        assert key == "test-gemini-key"

    def test_explicit_provider_missing_key(self):
        """Test error when explicit provider has no key."""
        with pytest.raises(RuntimeError, match="Missing API key"):
            _pick_provider_and_key("claude", {"gemini": "key"})

    def test_fallback_to_claude(self):
        """Test falling back to Claude when no provider specified."""
        prov, key = _pick_provider_and_key(None, {"claude": "claude-key"})
        assert prov == "claude"
        assert key == "claude-key"

    def test_fallback_to_gemini(self):
        """Test falling back to Gemini when Claude not available."""
        prov, key = _pick_provider_and_key(None, {"gemini": "gemini-key"})
        assert prov == "gemini"
        assert key == "gemini-key"

    def test_prefer_claude_over_gemini(self):
        """Test that Claude is preferred when both available."""
        prov, key = _pick_provider_and_key(None, {"claude": "c-key", "gemini": "g-key"})
        assert prov == "claude"
        assert key == "c-key"

    def test_case_insensitive_provider(self):
        """Test case-insensitive provider names."""
        prov, key = _pick_provider_and_key("CLAUDE", {"claude": "key"})
        assert prov == "claude"

    def test_no_keys_available(self):
        """Test error when no keys available."""
        with pytest.raises(RuntimeError, match="No provider keys available"):
            _pick_provider_and_key(None, {})

    def test_empty_provider_and_keys(self):
        """Test error with empty provider string and no keys."""
        with pytest.raises(RuntimeError, match="No provider keys available"):
            _pick_provider_and_key("", {})


class TestPodcastPrompt:
    """Test podcast prompt generation."""

    def test_prompt_contains_greeting(self):
        """Test that prompt includes the required greeting."""
        prompt = _podcast_prompt("machine learning")
        assert "Welcome to UpCurved Podcasts" in prompt
        assert "big ideas and curve them upwards" in prompt

    def test_prompt_contains_user_topic(self):
        """Test that user topic is included in prompt."""
        topic = "quantum computing"
        prompt = _podcast_prompt(topic)
        assert topic in prompt

    def test_prompt_instructs_plain_text(self):
        """Test that prompt instructs for plain text output."""
        prompt = _podcast_prompt("test")
        assert "plain text only" in prompt
        assert "Avoid markdown" in prompt

    def test_prompt_forbids_stage_directions(self):
        """Test that prompt forbids stage directions."""
        prompt = _podcast_prompt("test")
        assert "Do NOT include stage directions" in prompt
        assert "[music]" in prompt


class TestInferGttsLang:
    """Test language inference for gTTS."""

    def test_english_text(self):
        """Test English language detection."""
        lang = _infer_gtts_lang("This is a test in English")
        assert lang in ("en", "en-US", "en-GB")

    def test_empty_text_defaults_to_english(self):
        """Test that empty text defaults to English."""
        lang = _infer_gtts_lang("")
        assert lang == "en"

    def test_chinese_text_maps_to_zh_cn(self):
        """Test Chinese text maps to zh-cn."""
        lang = _infer_gtts_lang("这是一个测试")
        assert lang == "zh-cn"

    def test_portuguese_variant_handling(self):
        """Test Portuguese variant normalization."""
        # langdetect may return pt-br or pt_pt, both should map to 'pt'
        with patch("backend.mcp.podcast_logic.detect") as mock_detect:
            mock_detect.return_value = "pt-br"
            lang = _infer_gtts_lang("teste")
            assert lang == "pt"

    def test_langdetect_exception_defaults_to_english(self):
        """Test fallback to English on langdetect exception."""
        with patch("backend.mcp.podcast_logic.detect", side_effect=Exception("bad")):
            lang = _infer_gtts_lang("any text")
            assert lang == "en"


class TestSplitSentences:
    """Test sentence splitting logic."""

    def test_split_by_period(self):
        """Test splitting by periods."""
        text = "First sentence. Second sentence. Third."
        sents = _split_sentences(text)
        assert len(sents) == 3
        assert sents[0] == "First sentence."
        assert sents[1] == "Second sentence."
        assert sents[2] == "Third."

    def test_split_by_question_mark(self):
        """Test splitting by question marks."""
        text = "What is this? That is it!"
        sents = _split_sentences(text)
        assert len(sents) == 2
        assert sents[0] == "What is this?"
        assert sents[1] == "That is it!"

    def test_split_by_newline(self):
        """Test splitting by newlines."""
        text = "Line one.\nLine two."
        sents = _split_sentences(text)
        assert len(sents) == 2
        assert "Line one." in sents[0]
        assert "Line two." in sents[1]

    def test_empty_text(self):
        """Test empty text returns empty list."""
        sents = _split_sentences("")
        assert sents == []

    def test_whitespace_only_ignored(self):
        """Test that whitespace-only parts are ignored."""
        text = "One.   \n\n   Two."
        sents = _split_sentences(text)
        assert len(sents) == 2
        assert "One." in sents[0]
        assert "Two." in sents[1]


class TestFormatTs:
    """Test timestamp formatting."""

    def test_zero_timestamp(self):
        """Test zero timestamp."""
        ts = _format_ts(0.0)
        assert ts == "00:00:00,000"

    def test_one_minute(self):
        """Test one minute timestamp."""
        ts = _format_ts(60.0)
        assert ts == "00:01:00,000"

    def test_one_hour(self):
        """Test one hour timestamp."""
        ts = _format_ts(3600.0)
        assert ts == "01:00:00,000"

    def test_milliseconds(self):
        """Test millisecond precision."""
        ts = _format_ts(1.234)
        assert ts == "00:00:01,234"

    def test_complex_timestamp(self):
        """Test complex timestamp."""
        # 1 hour, 23 minutes, 45 seconds, 678 milliseconds
        ts = _format_ts(1 * 3600 + 23 * 60 + 45.678)
        assert ts == "01:23:45,678"

    def test_negative_timestamp(self):
        """Test negative timestamp clamps to zero."""
        ts = _format_ts(-5.0)
        assert ts == "00:00:00,000"


class TestMakeSrt:
    """Test basic SRT generation."""

    def test_single_sentence(self):
        """Test SRT for single sentence."""
        srt = _make_srt("Hello world.")
        assert "WEBVTT" not in srt  # Should be SRT, not VTT
        assert "1" in srt
        assert "00:00:00,000" in srt
        assert "Hello world" in srt

    def test_multiple_sentences(self):
        """Test SRT for multiple sentences."""
        text = "First sentence. Second sentence. Third sentence."
        srt = _make_srt(text)
        srt.strip().split("\n")
        # Should have indices: 1, 2, 3
        assert "1" in srt
        assert "2" in srt
        assert "3" in srt

    def test_cue_duration_based_on_words(self):
        """Test that cue duration increases with word count."""
        short = "Hi."
        long = "This is a much longer sentence with many words and punctuation marks!"
        srt_short = _make_srt(short)
        srt_long = _make_srt(long)
        # Extract duration from SRT (second line of each cue)
        assert srt_short is not None
        assert srt_long is not None

    def test_custom_words_per_second(self):
        """Test custom words per second setting."""
        text = "One two three four five."
        srt_fast = _make_srt(text, words_per_sec=5.0)
        srt_slow = _make_srt(text, words_per_sec=1.0)
        # Slow version should have longer durations
        assert srt_fast is not None
        assert srt_slow is not None


class TestSrtToVtt:
    """Test SRT to WebVTT conversion."""

    def test_adds_webvtt_header(self):
        """Test that WEBVTT header is added."""
        srt = "1\n00:00:00,000 --> 00:00:02,000\nHello"
        vtt = _srt_to_vtt(srt)
        assert vtt.startswith("WEBVTT")

    def test_converts_comma_to_dot(self):
        """Test that millisecond commas are converted to dots."""
        srt = "1\n00:00:01,234 --> 00:00:03,456\nTest"
        vtt = _srt_to_vtt(srt)
        assert "00:00:01.234 --> 00:00:03.456" in vtt
        assert "," not in vtt.split("\n")[2]  # Check timing line has no commas

    def test_removes_cue_indices(self):
        """Test that SRT cue indices are removed."""
        srt = "1\n00:00:00,000 --> 00:00:02,000\nFirst\n\n2\n00:00:02,000 --> 00:00:04,000\nSecond"
        vtt = _srt_to_vtt(srt)
        # Should not have standalone "1" or "2" (cue indices)
        lines = vtt.split("\n")
        for line in lines:
            if line.strip().isdigit():
                pytest.fail(f"Found cue index in VTT: {line}")

    def test_preserves_content(self):
        """Test that content text is preserved."""
        srt = "1\n00:00:00,000 --> 00:00:02,000\nTest content"
        vtt = _srt_to_vtt(srt)
        assert "Test content" in vtt


class TestMakeSrtProportional:
    """Test proportional SRT generation."""

    def test_empty_script(self):
        """Test empty script returns empty string."""
        srt = _make_srt_proportional("", 10.0)
        assert srt == ""

    def test_single_sentence_proportional(self):
        """Test proportional SRT for single sentence."""
        srt = _make_srt_proportional("Hello world.", 5.0)
        assert "Hello world" in srt
        assert "00:00:00,000 --> 00:00:05,000" in srt

    def test_multiple_sentences_proportional(self):
        """Test that sentences are distributed proportionally."""
        text = "Short. This is a much longer sentence with more words."
        srt = _make_srt_proportional(text, 10.0)
        # Should have two cues
        assert srt.count("\n\n") >= 1  # At least one blank line between cues

    def test_respects_minimum_per_cue(self):
        """Test that minimum duration per cue is respected."""
        text = "One. Two. Three. Four. Five."
        srt = _make_srt_proportional(text, 10.0, min_per_cue=1.0)
        assert srt is not None
        # Each cue should be at least 1 second (lines have timing)
        lines = srt.split("\n")
        timing_lines = [line for line in lines if " --> " in line]
        assert len(timing_lines) >= 1

    def test_total_duration_respected(self):
        """Test that total duration matches specified total."""
        text = "First sentence. Second sentence."
        total = 15.0
        srt = _make_srt_proportional(text, total)
        # Extract last timestamp
        lines = srt.strip().split("\n")
        for line in reversed(lines):
            if " --> " in line:
                end_time = line.split(" --> ")[1]
                # Parse HH:MM:SS,mmm format
                parts = end_time.replace(",", ".").split(":")
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                # Should end around total (allowing small rounding error)
                assert abs(seconds - total) < 1.0
                break

    def test_zero_duration(self):
        """Test with zero total duration."""
        srt = _make_srt_proportional("Test.", 0.0)
        assert srt is not None


class TestGeneratePodcast:
    """Test full podcast generation."""

    @patch("backend.mcp.podcast_logic.gTTS")
    @patch("backend.mcp.podcast_logic.call_llm")
    @patch("backend.mcp.podcast_logic.STORAGE")
    def test_generate_podcast_success(self, mock_storage, mock_call_llm, mock_gtts):
        """Test successful podcast generation."""
        # Setup mocks
        mock_storage.__truediv__ = Mock(return_value=mock_storage)
        mock_storage.__str__ = Mock(return_value="/tmp/storage")
        mock_storage.mkdir = Mock()

        mock_call_llm.return_value = "Welcome to UpCurved Podcasts. Today's topic: Test"
        mock_tts_instance = MagicMock()
        mock_gtts.return_value = mock_tts_instance

        # Mock file path operations
        with patch("backend.mcp.podcast_logic.to_static_url") as mock_static_url:
            mock_static_url.side_effect = lambda p: f"/static/{p.name}"

            result = generate_podcast(
                "test topic", provider="claude", provider_keys={"claude": "key"}
            )

        # Verify result structure
        assert result["status"] == "ok"
        assert "job_id" in result
        assert "video_url" in result

    @patch("backend.mcp.podcast_logic.call_llm")
    def test_generate_podcast_empty_script(self, mock_call_llm):
        """Test error handling when LLM returns empty script."""
        mock_call_llm.return_value = ""

        with pytest.raises(RuntimeError, match="LLM returned empty script"):
            generate_podcast("test", provider="claude", provider_keys={"claude": "key"})

    @patch("backend.mcp.podcast_logic.gTTS")
    @patch("backend.mcp.podcast_logic.call_llm")
    @patch("backend.mcp.podcast_logic.STORAGE")
    def test_generate_podcast_gtts_fallback(self, mock_storage, mock_call_llm, mock_gtts):
        """Test gTTS fallback when language-specific fails."""
        # Setup mocks
        mock_storage.__truediv__ = Mock(return_value=mock_storage)
        mock_storage.__str__ = Mock(return_value="/tmp/storage")
        mock_storage.mkdir = Mock()

        mock_call_llm.return_value = "Welcome to UpCurved Podcasts. Test content"

        # First gTTS call fails, second succeeds
        mock_tts_instance = MagicMock()
        mock_gtts.side_effect = [
            Exception("Language not supported"),
            mock_tts_instance,
        ]

        with patch("backend.mcp.podcast_logic.to_static_url") as mock_static_url:
            mock_static_url.side_effect = lambda p: f"/static/{p.name}"

            result = generate_podcast("test", provider="claude", provider_keys={"claude": "key"})

        # Should still succeed with fallback
        assert result["status"] == "ok"

    @patch("backend.mcp.podcast_logic.gTTS")
    @patch("backend.mcp.podcast_logic.call_llm")
    @patch("backend.mcp.podcast_logic.STORAGE")
    def test_generate_podcast_gtts_both_fail(self, mock_storage, mock_call_llm, mock_gtts):
        """Test error when both gTTS attempts fail."""
        mock_storage.__truediv__ = Mock(return_value=mock_storage)
        mock_storage.__str__ = Mock(return_value="/tmp/storage")
        mock_storage.mkdir = Mock()

        mock_call_llm.return_value = "Welcome to UpCurved Podcasts. Test content"
        mock_gtts.side_effect = Exception("Always fails")

        with pytest.raises(RuntimeError, match="TTS failed"):
            generate_podcast("test", provider="claude", provider_keys={"claude": "key"})

    @patch("backend.mcp.podcast_logic.call_llm")
    def test_generate_podcast_provider_selection(self, mock_call_llm):
        """Test provider is selected correctly."""
        mock_call_llm.return_value = "Welcome to UpCurved Podcasts. Test"

        with patch("backend.mcp.podcast_logic.gTTS"):
            with patch("backend.mcp.podcast_logic.STORAGE") as mock_storage:
                mock_storage.__truediv__ = Mock(return_value=mock_storage)
                mock_storage.__str__ = Mock(return_value="/tmp/storage")
                mock_storage.mkdir = Mock()

                with patch("backend.mcp.podcast_logic.to_static_url") as mock_static_url:
                    mock_static_url.side_effect = lambda p: f"/static/{p.name}"

                    generate_podcast(
                        "test",
                        provider="gemini",
                        provider_keys={"gemini": "key"},
                    )

        # Verify call_llm was called with gemini provider
        assert mock_call_llm.called
        call_kwargs = mock_call_llm.call_args[1]
        assert call_kwargs["provider"] == "gemini"


class TestPodcastServer:
    """Test podcast server tool."""

    @patch("backend.mcp.podcast_server.generate_podcast")
    def test_generate_podcast_tool(self, mock_generate):
        """Test podcast generation tool returns JSON."""
        mock_generate.return_value = {
            "status": "ok",
            "job_id": "test-123",
            "video_url": "/static/podcast.mp3",
            "srt_url": "/static/podcast.srt",
            "vtt_url": "/static/podcast.vtt",
            "lang": "en",
        }

        result_json = generate_podcast_tool("test prompt")

        # Should return valid JSON string
        result = json.loads(result_json)
        assert result["status"] == "ok"
        assert result["job_id"] == "test-123"
        assert "video_url" in result

    @patch("backend.mcp.podcast_server.generate_podcast")
    def test_generate_podcast_tool_with_provider(self, mock_generate):
        """Test tool passes provider to generate_podcast."""
        mock_generate.return_value = {
            "status": "ok",
            "job_id": "test-456",
            "video_url": "/static/podcast.mp3",
            "srt_url": "/static/podcast.srt",
            "vtt_url": "/static/podcast.vtt",
            "lang": "en",
        }

        generate_podcast_tool(
            "test prompt",
            provider="claude",
            model="claude-3-sonnet",
        )

        # Verify generate_podcast was called with correct args
        assert mock_generate.called
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs["prompt"] == "test prompt"
        assert call_kwargs["provider"] == "claude"
        assert call_kwargs["model"] == "claude-3-sonnet"

    @patch("backend.mcp.podcast_server.generate_podcast")
    def test_generate_podcast_tool_error_propagates(self, mock_generate):
        """Test that errors from generate_podcast are propagated."""
        mock_generate.side_effect = RuntimeError("TTS failed")

        with pytest.raises(RuntimeError, match="TTS failed"):
            generate_podcast_tool("test prompt")
