"""Audio as model input: audio_source, a video's soundtrack, and the player."""

import base64
import json
import shutil
import subprocess
import wave
from io import BytesIO

import pytest
from test_packaging import _Out

import paratext.packaging as packaging
from paratext.media import MediaError, normalise_media
from paratext.packaging import package
from paratext.projects import Audio, Project
from paratext.runner import build_user_message
from paratext.sources import audio_source, video_source
from paratext.video import evenly_spaced

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


def _tone(path, seconds=4):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-ar", "44100", str(path)],
        check=True,
    )
    return path


def _video_with_sound(path, seconds=4):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-pix_fmt", "yuv420p", "-shortest", str(path)],
        check=True,
    )
    return path


def _wav_seconds(data: bytes) -> tuple[float, int, int]:
    with wave.open(BytesIO(data)) as w:
        return w.getnframes() / w.getframerate(), w.getframerate(), w.getnchannels()


def test_audio_follows_the_images_as_input_audio_parts():
    msg = build_user_message("P", [], audio=[Audio(b"RIFFxx", "wav")])
    assert msg["content"] == [
        {"type": "text", "text": "P"},
        {"type": "input_audio",
         "input_audio": {"data": base64.b64encode(b"RIFFxx").decode(), "format": "wav"}},
    ]
    assert build_user_message("P", [])["content"] == [{"type": "text", "text": "P"}]


@needs_ffmpeg
def test_directory_yields_16k_mono_wav_and_audio_media(tmp_path):
    _tone(tmp_path / "talk.mp3")
    (tmp_path / "notes.txt").write_text("ignored")
    [s] = list(audio_source().iter_samples(tmp_path, None))
    assert s.id == "talk" and s.images == []
    secs, rate, channels = _wav_seconds(s.audio[0].data)
    assert (rate, channels) == (16000, 1) and secs == pytest.approx(4, abs=0.1)
    assert s.metadata["media"]["kind"] == "audio"
    assert s.metadata["media"]["end"] == pytest.approx(4, abs=0.1)


@needs_ffmpeg
def test_manifest_clips_one_recording_into_several(tmp_path):
    _tone(tmp_path / "tape.wav", seconds=6)
    rows = [{"id": "a", "src": "tape.wav", "end": 2, "label": "Intro"},
            {"id": "b", "src": "tape.wav", "start": 2, "end": 6}]
    (tmp_path / "clips.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    a, b = audio_source(sample_rate=8000).iter_samples(tmp_path / "clips.jsonl", None)
    assert _wav_seconds(a.audio[0].data)[:2] == (pytest.approx(2, abs=0.05), 8000)
    assert _wav_seconds(b.audio[0].data)[0] == pytest.approx(4, abs=0.05)
    assert a.metadata["media"]["label"] == "Intro"


@needs_ffmpeg
def test_an_undecodable_clip_is_skipped_with_a_notice(tmp_path):
    (tmp_path / "broken.wav").write_bytes(b"not audio")
    _tone(tmp_path / "fine.wav", seconds=1)
    src = audio_source()
    assert [s.id for s in src.iter_samples(tmp_path, None)] == ["fine"]
    assert any("broken" in n for n in src.notices)


@needs_ffmpeg
def test_video_soundtrack_rides_with_the_frames(tmp_path):
    _video_with_sound(tmp_path / "a.mp4")
    [s] = video_source(frames=evenly_spaced(2), soundtrack=True).iter_samples(tmp_path, None)
    assert len(s.images) == 2
    assert _wav_seconds(s.audio[0].data)[0] == pytest.approx(4, abs=0.15)
    [quiet] = video_source(frames=evenly_spaced(2)).iter_samples(tmp_path, None)
    assert quiet.audio == []


def test_media_kind_follows_the_file_unless_given():
    assert normalise_media({"src": "talk.MP3"})["kind"] == "audio"
    assert normalise_media({"src": "reel.mp4"})["kind"] == "video"
    assert normalise_media({"src": "stream.m3u8", "kind": "audio"})["kind"] == "audio"
    with pytest.raises(MediaError, match="kind"):
        normalise_media({"src": "x.wav", "kind": "radio"})


@needs_ffmpeg
def test_packaging_copies_a_local_recording_for_the_player(tmp_path, monkeypatch):
    src_dir = tmp_path / "sound"
    src_dir.mkdir()
    _tone(src_dir / "a.wav", seconds=1)
    source = audio_source()
    proj = Project(name="demo", schema_version="v1", prompt="P", schema=_Out, source=source)
    monkeypatch.setattr(packaging, "get_project", lambda name: proj)
    [s] = source.iter_samples(src_dir, None)
    jsonl = tmp_path / "run.jsonl"
    jsonl.write_text(json.dumps({"_provenance": {"project": "demo"}}) + "\n"
                     + json.dumps({"id": s.id, "extraction": {}, "metadata": s.metadata}) + "\n")
    out = tmp_path / "ds"
    package(jsonl, out, "demo", fresh=True)
    [rec] = json.loads((out / "samples.json").read_text())
    assert rec["media"]["src"] == "images/a/audio.wav" and rec["media"]["kind"] == "audio"
    assert rec["images"] == []
    assert (out / "images/a/audio.wav").is_file()
