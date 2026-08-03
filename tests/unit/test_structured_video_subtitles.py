"""Tests for final structured-video subtitle assembly."""

from backend.agent import structured_video


def test_subtitle_fallback_uses_complete_audio_script_without_heading(tmp_path, monkeypatch):
    clips = [tmp_path / "scene-1.mp4"]
    clips[0].write_bytes(b"not-needed-for-unit-test")
    monkeypatch.setattr(structured_video, "_media_duration_seconds", lambda path, fallback: 12.0)
    plan = {
        "scenes": [
            {
                "title": "Internal scene heading",
                "narration": "Here is the main explanation.",
                "steps": ["Visible point one", "Visible point two"],
                "step_narrations": [
                    "First, explain the first subpoint.",
                    "Finally, explain the second subpoint.",
                ],
                "duration_sec": 12,
            }
        ]
    }
    srt_path = tmp_path / "video.srt"
    vtt_path = tmp_path / "video.vtt"

    structured_video._write_subtitles_from_scenes(plan, clips, srt_path, vtt_path)

    srt = srt_path.read_text(encoding="utf-8")
    vtt = vtt_path.read_text(encoding="utf-8")
    for expected in (
        "Here is the main explanation.",
        "First, explain the first subpoint.",
        "Finally, explain the second subpoint.",
    ):
        assert expected in srt
        assert expected in vtt
    assert "Internal scene heading" not in srt
    assert "Internal scene heading" not in vtt
    assert "00:00:00,000 -->" in srt
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 -->")


def test_subtitles_merge_actual_scene_vtt_and_offset_next_scene(tmp_path, monkeypatch):
    first_clip = tmp_path / "first.mp4"
    second_clip = tmp_path / "second.mp4"
    first_clip.write_bytes(b"first")
    second_clip.write_bytes(b"second")
    first_clip.with_suffix(".vtt").write_text(
        "WEBVTT\n\n00:00:00.500 --> 00:00:02.000\nExact words sent to TTS.\n",
        encoding="utf-8",
    )
    second_clip.with_suffix(".vtt").write_text(
        "WEBVTT\n\n00:00:00.250 --> 00:00:01.500\nSecond scene audio.\n",
        encoding="utf-8",
    )
    durations = {first_clip: 5.0, second_clip: 3.0}
    monkeypatch.setattr(
        structured_video,
        "_media_duration_seconds",
        lambda path, fallback: durations[path],
    )
    plan = {
        "scenes": [
            {"title": "Wrong heading one", "narration": "Plan text one."},
            {"title": "Wrong heading two", "narration": "Plan text two."},
        ]
    }
    srt_path = tmp_path / "final.srt"
    vtt_path = tmp_path / "final.vtt"

    structured_video._write_subtitles_from_scenes(
        plan, [first_clip, second_clip], srt_path, vtt_path
    )

    srt = srt_path.read_text(encoding="utf-8")
    vtt = vtt_path.read_text(encoding="utf-8")
    assert "Exact words sent to TTS." in vtt
    assert "Plan text one." not in vtt
    assert "Wrong heading" not in vtt
    assert "00:00:05.250 --> 00:00:06.500" in vtt
    assert "00:00:05,250 --> 00:00:06,500" in srt
