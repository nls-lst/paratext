"""Transcription hook: a project's transcriber feeds text to the model and a
track to the review timeline."""

import json
import shutil
import subprocess

import pytest

from paratext.runner import build_user_message
from paratext.sources import audio_source, video_source
from paratext.transcripts import Segment, as_text, as_track
from paratext.video import evenly_spaced

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)

SEGS = [Segment(0.0, 2.5, " Good morning. ", "A"), Segment(65.0, None, "Aye.")]


def _tone(path, seconds=4):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", str(path)], check=True)
    return path


def test_text_is_timed_from_the_clip_start():
    assert as_text(SEGS) == ("Transcript of the recording:\n"
                             "[00:00] A: Good morning.\n[01:05] Aye.")


def test_track_times_are_absolute_for_the_timeline():
    assert as_track(SEGS, 100.0) == {"name": "Transcript", "items": [
        {"start": 100.0, "end": 102.5, "text": "A: Good morning."},
        {"start": 165.0, "text": "Aye."},
    ]}


def test_text_parts_come_after_images_and_audio():
    parts = build_user_message("P", [], texts=["T"])["content"]
    assert parts == [{"type": "text", "text": "P"}, {"type": "text", "text": "T"}]


@needs_ffmpeg
def test_audio_source_sends_the_transcript_instead_of_the_sound(tmp_path):
    _tone(tmp_path / "tape.wav", seconds=6)
    (tmp_path / "clips.jsonl").write_text(json.dumps(
        {"id": "a", "src": "tape.wav", "start": 2, "end": 6, "catalogue": "T1234"}))
    seen = []

    def fake(wav, clip):
        seen.append((wav[:4], clip))
        return [Segment(0.5, 1.5, "hello")]

    [s] = audio_source(transcribe=fake).iter_samples(tmp_path / "clips.jsonl", None)
    assert seen[0][0] == b"RIFF" and seen[0][1]["extra"] == {"catalogue": "T1234"}
    assert s.audio == [] and s.text == ["Transcript of the recording:\n[00:00] hello"]
    assert s.metadata["media"]["tracks"][0]["items"] == [
        {"start": 2.5, "end": 3.5, "text": "hello"}]
    assert s.metadata["transcript"] == [
        {"start": 0.5, "end": 1.5, "text": "hello", "speaker": None}]

    [both] = audio_source(transcribe=fake, send_audio=True).iter_samples(
        tmp_path / "clips.jsonl", None)
    assert len(both.audio) == 1 and both.text


@needs_ffmpeg
def test_a_failing_transcriber_skips_the_clip_with_a_notice(tmp_path):
    _tone(tmp_path / "a.wav", seconds=1)
    src = audio_source(transcribe=lambda wav, clip: ["not a segment"])
    assert list(src.iter_samples(tmp_path, None)) == []
    assert any("transcribed" in n and "a" in n for n in src.notices)


@needs_ffmpeg
def test_video_source_adds_the_transcript_after_the_frames(tmp_path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:d=4",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-pix_fmt", "yuv420p",
         "-shortest", str(tmp_path / "a.mp4")],
        check=True,
    )
    src = video_source(frames=evenly_spaced(2), transcribe=lambda wav, clip: [Segment(1, 2, "hi")])
    [s] = src.iter_samples(tmp_path, None)
    assert len(s.images) == 2 and s.audio == []
    assert s.text == ["Transcript of the recording:\n[00:01] hi"]
    assert s.metadata["media"]["tracks"][0]["name"] == "Transcript"


@needs_ffmpeg
def test_a_silent_video_is_skipped_when_a_transcript_is_wanted(tmp_path):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=10:d=2", "-pix_fmt", "yuv420p",
                    str(tmp_path / "silent.mp4")], check=True)
    src = video_source(frames=evenly_spaced(1), transcribe=lambda wav, clip: [])
    assert list(src.iter_samples(tmp_path, None)) == []
    assert any("silent" in n for n in src.notices)
