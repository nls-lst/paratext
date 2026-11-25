"""Transcripts of a clip's sound, made by a function the project supplies.

``audio_source`` and ``video_source`` take ``transcribe=``: a function from the
clip's sound (16 kHz mono WAV bytes) and its manifest row to timed segments, with
times counted from the start of the clip. Paratext doesn't ship a speech model:
the function can call a local one, a server, or read a transcript made elsewhere.

The transcript reaches the model as text after the prompt, so a model without
audio input can still describe a recording. It's also kept in the record
(``metadata.transcript``) and drawn as a track on the review player's timeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable


@dataclass
class Segment:
    """One stretch of speech: seconds from the start of the clip, its text and,
    when the transcriber knows it, who spoke."""

    start: float
    end: float | None
    text: str
    speaker: str | None = None


# (wav_bytes, clip) -> segments. `clip` is the manifest row: id, src, start, end,
# label, and any other columns under "extra" (a catalogue id, terms to listen for).
Transcriber = Callable[[bytes, dict], list[Segment]]


def _clock(t: float) -> str:
    t = max(0, round(t))
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def as_text(segments: list[Segment]) -> str:
    """The transcript as the model reads it: one line per segment, with its time
    from the start of the clip, as the timestamps on video frames are."""
    lines = []
    for s in segments:
        who = f"{s.speaker}: " if s.speaker else ""
        lines.append(f"[{_clock(s.start)}] {who}{s.text.strip()}")
    return "Transcript of the recording:\n" + "\n".join(lines)


def as_track(segments: list[Segment], clip_start: float, name: str = "Transcript") -> dict:
    """A media track for the review player. Its times are absolute, like the
    timeline's, so the clip start is added back."""
    items = []
    for s in segments:
        item = {"start": clip_start + s.start, "text": s.text.strip()}
        if s.end is not None:
            item["end"] = clip_start + s.end
        if s.speaker:
            item["text"] = f"{s.speaker}: {item['text']}"
        items.append(item)
    return {"name": name, "items": items}


def transcribe_clip(transcribe: Transcriber, wav: bytes, clip: dict, start: float) -> dict:
    """Run the project's transcriber and shape what the sources need: the text
    for the model, the track for review, and the segments for the record."""
    segments = transcribe(wav, clip)
    if not all(isinstance(s, Segment) for s in segments):
        raise TypeError("transcribe must return a list of paratext.transcripts.Segment")
    return {
        "text": as_text(segments),
        "track": as_track(segments, start),
        "segments": [asdict(s) for s in segments],
    }
