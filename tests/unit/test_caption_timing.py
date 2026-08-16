"""Captions must follow the narrator's real word timings, not a constant character rate."""

import json

from backend.runner import caption_timing as ct

TICKS = 10_000_000


def _boundary(text, text_offset, start_s, duration_s):
    return {
        "audio_offset": int(start_s * TICKS),
        "duration_milliseconds": int(duration_s * 1000),
        "text_offset": text_offset,
        "word_length": len(text),
        "text": text,
        "boundary_type": "Word",
    }


# "Now watch closely." then a full second of silence, then "The answer is four."
# Both halves have ~19 characters, so manim's character-proportional split puts the second cue at
# 2.0s -- a whole second before the voice resumes at 3.0s.
UTTERANCE = "Now watch closely. The answer is four."
WORDS = [
    _boundary("Now", 0, 0.00, 0.30),
    _boundary("watch", 4, 0.30, 0.40),
    _boundary("closely", 10, 0.70, 0.60),
    _boundary("The", 19, 3.00, 0.25),
    _boundary("answer", 23, 3.25, 0.45),
    _boundary("is", 30, 3.70, 0.15),
    _boundary("four", 33, 3.85, 0.45),
]

MANIM_SRT = """1
00:00:00,000 --> 00:00:01,950
Now watch closely.

2
00:00:02,000 --> 00:00:04,300
The answer is four.
"""


def _spoken():
    return {ct.normalize_caption_text(UTTERANCE): ct._spoken_words(WORDS)}


def test_second_cue_moves_to_when_the_voice_actually_resumes(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0")
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), _spoken())

    assert len(cues) == 2
    first, second = cues
    assert round(first.start, 3) == 0.0
    assert round(first.end, 3) == 1.3          # ends when "closely" finishes, not at 1.95
    assert round(second.start, 3) == 3.0       # was 2.0: the pause is now a gap, not caption time
    assert round(second.end, 3) == 4.3


def test_lead_pulls_a_cue_forward_into_the_preceding_silence(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0.15")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0")
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), _spoken())

    # "The" is spoken at 3.0s after a 1.7s pause, so the cue can appear 150ms early.
    assert round(cues[1].start, 3) == 2.85
    assert round(cues[1].end, 3) == 4.3


def test_hold_keeps_a_caption_on_screen_through_the_pause(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0.6")
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), _spoken())

    # Without a hold the first caption vanished at 1.3s and left 1.7s of blank screen.
    assert round(cues[0].end, 3) == 1.9
    assert cues[0].end < cues[1].start


def test_hold_is_cut_short_by_the_next_cue(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "30")
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), _spoken())

    # A hold far longer than the pause must stop just before the next caption, never overlap it.
    assert cues[0].end < cues[1].start
    assert round(cues[1].start - cues[0].end, 3) == 0.001
    # The final caption has nothing after it, so it takes the full hold.
    assert round(cues[-1].end, 3) == 34.3


def test_hold_never_shortens_a_cue(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0.6")
    plain = [ct.Cue(0.0, 5.0, "a"), ct.Cue(5.05, 6.0, "b")]
    held = ct._apply_hold(plain, 0.6)

    # The gap here is smaller than the hold; the cue must not be pulled back before its own end.
    assert held[0].end >= plain[0].end
    assert held[0].end < held[1].start


def test_hold_is_configurable_and_rejects_junk(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "1.2")
    assert ct.caption_hold_seconds() == 1.2
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "-3")
    assert ct.caption_hold_seconds() == 0.0
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "nope")
    assert ct.caption_hold_seconds() == 0.6
    monkeypatch.delenv("UPCURVED_CAPTION_HOLD_SECONDS")
    assert ct.caption_hold_seconds() == 0.6


def test_lead_never_eats_into_the_previous_cue(monkeypatch):
    # A lead longer than the pause must clamp to the previous cue's end, not overlap it.
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "5")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0")
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), _spoken())

    assert round(cues[0].start, 3) == 0.0
    assert round(cues[1].start, 3) == round(cues[0].end, 3) == 1.3
    assert cues[1].start < cues[1].end


def test_lead_never_goes_negative(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "5")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0")
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), _spoken())
    assert cues[0].start >= 0.0


def test_lead_is_configurable_and_rejects_junk(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0.4")
    assert ct.caption_lead_seconds() == 0.4
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "-1")
    assert ct.caption_lead_seconds() == 0.0
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "abc")
    assert ct.caption_lead_seconds() == 0.15
    monkeypatch.delenv("UPCURVED_CAPTION_LEAD_SECONDS")
    assert ct.caption_lead_seconds() == 0.15


def test_cue_text_is_never_altered():
    original = ct.parse_cues(MANIM_SRT)
    cues = ct.retime_cues(original, _spoken())
    assert [cue.text for cue in cues] == [cue.text for cue in original]


def test_block_start_offsets_onto_the_scene_timeline(monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0")
    # Same utterance, but the voiceover begins 10s into the scene.
    shifted = MANIM_SRT.replace("00:00:00,000", "00:00:10,000").replace(
        "00:00:02,000", "00:00:12,000"
    )
    cues = ct.retime_cues(ct.parse_cues(shifted), _spoken())
    assert round(cues[0].start, 3) == 10.0
    assert round(cues[1].start, 3) == 13.0


def test_missing_timings_keep_manim_times():
    cues = ct.retime_cues(ct.parse_cues(MANIM_SRT), {})
    assert [(round(c.start, 3), round(c.end, 3)) for c in cues] == [(0.0, 1.95), (2.0, 4.3)]


def test_gtts_style_entry_without_boundaries_is_ignored(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps([{"input_text": UTTERANCE, "original_audio": "a.mp3"}]),
        encoding="utf-8",
    )
    assert ct.load_spoken_words(cache) == {}


def test_cache_round_trip_produces_retimed_files(tmp_path, monkeypatch):
    monkeypatch.setenv("UPCURVED_CAPTION_LEAD_SECONDS", "0")
    monkeypatch.setenv("UPCURVED_CAPTION_HOLD_SECONDS", "0")
    media = tmp_path / "media"
    (media / "voiceovers").mkdir(parents=True)
    (media / "voiceovers" / "cache.json").write_text(
        json.dumps(
            [{"input_text": UTTERANCE, "original_audio": "a.mp3", "word_boundaries": WORDS}]
        ),
        encoding="utf-8",
    )
    srt_path = tmp_path / "video.srt"
    srt_path.write_text(MANIM_SRT, encoding="utf-8")

    srt_text, vtt_text = ct.retimed_subtitles(srt_path, media)

    assert "00:00:03,000 --> 00:00:04,300" in srt_text
    assert "00:00:03.000 --> 00:00:04.300" in vtt_text
    assert vtt_text.startswith("WEBVTT\n\n")
    assert "The answer is four." in vtt_text
    # SRT keeps its index lines; WebVTT must not carry them.
    assert srt_text.lstrip().startswith("1\n")
    assert "\n1\n" not in vtt_text


def test_corrupt_cache_degrades_quietly(tmp_path):
    media = tmp_path / "media"
    (media / "voiceovers").mkdir(parents=True)
    (media / "voiceovers" / "cache.json").write_text("{not json", encoding="utf-8")
    srt_path = tmp_path / "video.srt"
    srt_path.write_text(MANIM_SRT, encoding="utf-8")

    srt_text, _ = ct.retimed_subtitles(srt_path, media)
    assert "00:00:02,000 --> 00:00:04,300" in srt_text


def test_word_boundaries_are_built_from_edge_tts_chunks():
    from backend.tts.engine import _word_boundaries_from_chunks

    chunks = [
        {"type": "WordBoundary", "offset": 0, "duration": 3_000_000, "text": "Now"},
        {"type": "WordBoundary", "offset": 30_000_000, "duration": 4_000_000, "text": "watch"},
    ]
    built = _word_boundaries_from_chunks("Now watch closely.", chunks)

    assert [b["text_offset"] for b in built] == [0, 4]
    assert [b["word_length"] for b in built] == [3, 5]
    assert built[0]["duration_milliseconds"] == 300
    assert built[1]["audio_offset"] == 30_000_000


def test_unlocatable_spoken_word_is_skipped_not_guessed():
    from backend.tts.engine import _word_boundaries_from_chunks

    # The voice expands "5" to "five", which does not appear in the source text.
    chunks = [
        {"type": "WordBoundary", "offset": 0, "duration": 3_000_000, "text": "Take"},
        {"type": "WordBoundary", "offset": 30_000_000, "duration": 3_000_000, "text": "five"},
        {"type": "WordBoundary", "offset": 60_000_000, "duration": 3_000_000, "text": "steps"},
    ]
    built = _word_boundaries_from_chunks("Take 5 steps", chunks)

    assert [b["text"] for b in built] == ["Take", "steps"]
