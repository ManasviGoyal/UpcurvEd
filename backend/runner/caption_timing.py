"""Re-time manim-voiceover subcaptions using the narrator's real word timings.

``VoiceoverScene.add_wrapped_subcaption`` splits narration into fixed-length chunks and gives each
one a slice of the audio proportional to its *character count*. That models speech as a constant
number of characters per second, so every pause the voice takes -- a comma, a sentence break --
costs time but almost no characters, and the captions run steadily ahead of the audio inside each
voiceover block.

edge-tts reports the audio offset of every word, and ``EdgeTTSService`` now stores those in
manim-voiceover's ``cache.json``. This module keeps manim's caption *text* exactly as-is and only
replaces the *times*, so each cue starts when its first word is actually spoken and ends when its
last word finishes -- which leaves the pauses in the gaps between cues, where they belong.

Everything here is pure and file-format level so it can be tested without rendering a video.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, NamedTuple

# manim-voiceover reports word offsets in 100-nanosecond ticks (its AUDIO_OFFSET_RESOLUTION).
_TICKS_PER_SECOND = 10_000_000


def caption_lead_seconds() -> float:
    """How far ahead of the spoken word a cue should appear.

    Anchoring a cue exactly on word onset is *accurate* but reads late, because the viewer only
    starts reading once the sound has already begun. Broadcast practice is to lead the audio
    slightly. The lead is only ever taken out of preceding silence, so it can never overlap the
    previous cue or reveal the next line before the current one has finished being spoken.
    """
    try:
        value = float(os.getenv("UPCURVED_CAPTION_LEAD_SECONDS", "0.15"))
    except ValueError:
        return 0.15
    return max(0.0, value)
_BOOKMARK_RE = re.compile(r"<bookmark\s*mark\s*=\s*['\"][^'\"]*['\"]\s*/>")
_SRT_TIME_RE = re.compile(
    r"(?P<start>\d{2,}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(?P<end>\d{2,}:\d{2}:\d{2}[.,]\d{3})"
)


class Cue(NamedTuple):
    start: float
    end: float
    text: str


class SpokenWord(NamedTuple):
    text_offset: int
    text_end: int
    start: float
    end: float


def normalize_caption_text(value: str) -> str:
    """Collapse whitespace and drop bookmarks, matching what manim puts in the SRT."""
    return " ".join(_BOOKMARK_RE.sub("", str(value or "")).split())


def timestamp_seconds(value: str) -> float:
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def format_timestamp(seconds: float, *, separator: str) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def parse_cues(text: str) -> list[Cue]:
    """Read cues out of an SRT or WebVTT body, ignoring index lines and headers."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    cues: list[Cue] = []
    index = 0
    while index < len(lines):
        match = _SRT_TIME_RE.match(lines[index].strip())
        if not match:
            index += 1
            continue
        start = timestamp_seconds(match.group("start"))
        end = timestamp_seconds(match.group("end"))
        index += 1
        payload: list[str] = []
        while index < len(lines) and lines[index].strip():
            payload.append(lines[index].strip())
            index += 1
        body = "\n".join(payload).strip()
        if body:
            cues.append(Cue(start, end, body))
    return cues


def load_spoken_words(cache_json: Path) -> dict[str, list[SpokenWord]]:
    """Map normalized utterance text to its spoken word timings from cache.json."""
    try:
        entries = json.loads(cache_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(entries, list):
        return {}

    spoken: dict[str, list[SpokenWord]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        boundaries = entry.get("word_boundaries")
        key = normalize_caption_text(entry.get("input_text") or "")
        if not key or not isinstance(boundaries, list):
            continue
        words = _spoken_words(boundaries)
        if words:
            spoken[key] = words
    return spoken


def _spoken_words(boundaries: list[Any]) -> list[SpokenWord]:
    words: list[SpokenWord] = []
    for boundary in boundaries:
        if not isinstance(boundary, dict):
            continue
        try:
            offset = int(boundary.get("audio_offset") or 0)
            text_offset = int(boundary.get("text_offset"))
            length = int(boundary.get("word_length") or 0)
        except (TypeError, ValueError):
            continue
        duration_ms = boundary.get("duration_milliseconds") or 0
        start = offset / _TICKS_PER_SECOND
        try:
            end = start + float(duration_ms) / 1000.0
        except (TypeError, ValueError):
            end = start
        words.append(SpokenWord(text_offset, text_offset + length, start, max(start, end)))
    words.sort(key=lambda word: word.start)
    return words


def _match_block(cues: list[Cue], start_index: int, available: dict[str, list[SpokenWord]]):
    """Find the run of cues starting at ``start_index`` that spells out one whole utterance.

    Cue chunks are consecutive pieces of a single utterance, so growing the joined text until it
    equals a known utterance identifies the block without relying on cache ordering.
    """
    joined = ""
    for end_index in range(start_index, len(cues)):
        chunk = normalize_caption_text(cues[end_index].text)
        joined = f"{joined} {chunk}".strip() if joined else chunk
        words = available.get(joined)
        if words:
            return end_index, joined, words
    return None


def caption_hold_seconds() -> float:
    """How long a cue stays on screen after its last word.

    Ending a cue exactly on the final word is faithful to the audio but leaves the screen blank
    through every pause -- most visibly at a scene boundary, where the silence is longest and the
    caption vanishes well before the next one arrives. Holding briefly closes that gap. The hold
    is always cut short by the next cue, so it can never overlap the following line.
    """
    try:
        value = float(os.getenv("UPCURVED_CAPTION_HOLD_SECONDS", "0.6"))
    except ValueError:
        return 0.6
    return max(0.0, value)


def _apply_hold(cues: list[Cue], hold: float) -> list[Cue]:
    """Extend each cue toward the next one, by at most ``hold``."""
    if hold <= 0 or not cues:
        return cues
    held: list[Cue] = []
    for position, cue in enumerate(cues):
        limit = cue.end + hold
        if position + 1 < len(cues):
            # Stop just shy of the next cue so the two never touch or overlap.
            limit = min(limit, cues[position + 1].start - 0.001)
        held.append(Cue(cue.start, max(cue.end, limit), cue.text))
    return held


def retime_cues(cues: list[Cue], spoken: dict[str, list[SpokenWord]]) -> list[Cue]:
    """Replace cue times with real word times, leaving cue text untouched.

    Any block without usable timings keeps manim's original times, so a gTTS fallback utterance or
    a stale cache degrades to current behaviour rather than producing nonsense.
    """
    if not cues or not spoken:
        return list(cues)

    lead = caption_lead_seconds()
    available = dict(spoken)
    output: list[Cue] = []
    index = 0
    while index < len(cues):
        matched = _match_block(cues, index, available)
        if matched is None:
            output.append(cues[index])
            index += 1
            continue

        end_index, utterance, words = matched
        # add_wrapped_subcaption starts its first chunk at offset 0, so the block's first cue
        # start is the moment this utterance's audio begins on the scene timeline.
        block_start = cues[index].start
        available.pop(utterance, None)

        cursor = 0
        for cue in cues[index : end_index + 1]:
            chunk = normalize_caption_text(cue.text)
            found = utterance.find(chunk, cursor)
            if found < 0:
                output.append(cue)
                continue
            cursor = found + len(chunk)
            covered = [
                word for word in words if word.text_offset < cursor and word.text_end > found
            ]
            if not covered:
                output.append(cue)
                continue
            onset = block_start + covered[0].start
            end = block_start + max(word.end for word in covered)
            # Take the lead out of the silence before the word, never out of the previous cue.
            floor = output[-1].end if output else 0.0
            start = max(onset - lead, floor, 0.0)
            output.append(Cue(start, max(start + 0.001, end), cue.text))
        index = end_index + 1
    return _apply_hold(output, caption_hold_seconds())


def render_srt(cues: list[Cue]) -> str:
    lines: list[str] = []
    for number, cue in enumerate(cues, start=1):
        lines.extend(
            [
                str(number),
                f"{format_timestamp(cue.start, separator=',')} --> "
                f"{format_timestamp(cue.end, separator=',')}",
                cue.text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + ("\n" if cues else "")


def render_vtt(cues: list[Cue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.extend(
            [
                f"{format_timestamp(cue.start, separator='.')} --> "
                f"{format_timestamp(cue.end, separator='.')}",
                cue.text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + ("\n" if cues else "\n\n")


def find_voiceover_cache(media_dir: Path) -> Path | None:
    """Locate manim-voiceover's cache.json under a render's media directory."""
    for candidate in sorted(media_dir.rglob("cache.json")):
        return candidate
    return None


def retimed_subtitles(srt_path: Path, media_dir: Path) -> tuple[str, str] | None:
    """Return (srt, vtt) text re-timed from word boundaries, or None if nothing can be improved."""
    try:
        cues = parse_cues(srt_path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None
    if not cues:
        return None

    cache_json = find_voiceover_cache(media_dir)
    spoken = load_spoken_words(cache_json) if cache_json else {}
    retimed = retime_cues(cues, spoken)
    return render_srt(retimed), render_vtt(retimed)
