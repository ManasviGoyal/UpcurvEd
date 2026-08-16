"""The watermark must survive an ffmpeg build with no text renderer.

imageio-ffmpeg ships a static FFmpeg 7 without libharfbuzz, and FFmpeg 7 dropped `drawtext` unless
harfbuzz is present. Every packaged build therefore failed the whole render with
"No such filter: 'drawtext'" at the Final Video Assembly stage.
"""

import subprocess

import pytest

from backend.agent import structured_video as sv

FILTERS_WITH_DRAWTEXT = """Filters:
  T.. drawbox           V->V       Draw a colored box on the input video.
  TS. drawtext          V->V       Draw text on top of video frames using libfreetype library.
  TB. overlay           VV->V      Overlay a video source on top of the input.
"""

FILTERS_WITHOUT_DRAWTEXT = """Filters:
  T.. drawbox           V->V       Draw a colored box on the input video.
  TB. overlay           VV->V      Overlay a video source on top of the input.
"""


def _fake_filters(output, returncode=0):
    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, output, "")

    return _run


@pytest.fixture(autouse=True)
def _clear_filter_cache():
    # Tests that replace _ffmpeg_has_filter leave a plain function here, which has no cache to
    # clear -- so look the attribute up rather than assuming the lru_cache wrapper is still bound.
    def _clear():
        clear = getattr(sv._ffmpeg_has_filter, "cache_clear", None)
        if clear is not None:
            clear()

    _clear()
    yield
    _clear()


def test_detects_drawtext_when_present(monkeypatch):
    monkeypatch.setattr(sv.subprocess, "run", _fake_filters(FILTERS_WITH_DRAWTEXT))
    assert sv._ffmpeg_has_filter("/fake/ffmpeg", "drawtext") is True


def test_detects_missing_drawtext(monkeypatch):
    monkeypatch.setattr(sv.subprocess, "run", _fake_filters(FILTERS_WITHOUT_DRAWTEXT))
    assert sv._ffmpeg_has_filter("/fake/ffmpeg", "drawtext") is False
    # overlay is a core filter and must still be seen in the same listing.
    sv._ffmpeg_has_filter.cache_clear()
    assert sv._ffmpeg_has_filter("/fake/ffmpeg", "overlay") is True


def test_substring_filter_names_do_not_false_match(monkeypatch):
    monkeypatch.setattr(sv.subprocess, "run", _fake_filters(FILTERS_WITHOUT_DRAWTEXT))
    # "drawbox" is present; "draw" must not be reported as a filter of its own.
    assert sv._ffmpeg_has_filter("/fake/ffmpeg", "draw") is False


def test_unrunnable_ffmpeg_reports_no_filter(monkeypatch):
    def _boom(cmd, **kwargs):
        raise OSError("cannot execute")

    monkeypatch.setattr(sv.subprocess, "run", _boom)
    assert sv._ffmpeg_has_filter("/fake/ffmpeg", "drawtext") is False


def test_overlay_png_is_rendered_without_a_font_file(tmp_path):
    png = tmp_path / "watermark.png"
    width, height = sv._write_watermark_overlay_png(png)

    assert png.exists()
    assert png.stat().st_size > 0
    assert width > height > 0

    from PIL import Image

    with Image.open(png) as image:
        assert image.mode == "RGBA"
        assert image.size == (width, height)
        # Semi-transparent box, not opaque and not fully clear.
        assert 0 < image.getpixel((0, 0))[3] < 255


def test_watermark_falls_back_to_overlay_when_drawtext_is_absent(tmp_path, monkeypatch):
    recorded = {}

    monkeypatch.setattr(sv, "_find_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(sv, "_ffmpeg_has_filter", lambda *_: False)

    video = tmp_path / "video.mp4"
    video.write_bytes(b"original")
    logs = tmp_path / "logs"

    def _run(cmd, **kwargs):
        recorded["cmd"] = cmd
        # Stand in for ffmpeg writing its output file.
        video.with_name("video_watermarked.mp4").write_bytes(b"watermarked")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sv.subprocess, "run", _run)
    sv._apply_final_watermark(video, logs)

    cmd = recorded["cmd"]
    assert "-filter_complex" in cmd
    assert any("overlay=" in str(part) for part in cmd)
    assert not any("drawtext" in str(part) for part in cmd)
    # Audio must be carried across, and optionally so silent clips do not fail.
    assert "0:a?" in cmd
    assert video.read_bytes() == b"watermarked"
    assert not (logs / "watermark_overlay.png").exists()


def test_watermark_uses_drawtext_when_available(tmp_path, monkeypatch):
    recorded = {}

    monkeypatch.setattr(sv, "_find_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(sv, "_ffmpeg_has_filter", lambda *_: True)

    video = tmp_path / "video.mp4"
    video.write_bytes(b"original")
    logs = tmp_path / "logs"
    logs.mkdir()

    def _run(cmd, **kwargs):
        recorded["cmd"] = cmd
        video.with_name("video_watermarked.mp4").write_bytes(b"watermarked")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sv.subprocess, "run", _run)
    sv._apply_final_watermark(video, logs)

    cmd = recorded["cmd"]
    assert any("drawtext=" in str(part) for part in cmd)
    assert "-filter_complex" not in cmd
    assert not (logs / "watermark_overlay.png").exists()


def test_failure_still_raises_with_ffmpeg_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_find_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(sv, "_ffmpeg_has_filter", lambda *_: False)

    video = tmp_path / "video.mp4"
    video.write_bytes(b"original")

    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "Filter not found")

    monkeypatch.setattr(sv.subprocess, "run", _run)

    with pytest.raises(RuntimeError, match="ffmpeg watermark failed"):
        sv._apply_final_watermark(video, tmp_path / "logs")
