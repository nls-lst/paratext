"""video_source: clips sampled to timestamped frames, packaged with their video."""

import json
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from test_packaging import _Out

import paratext.packaging as packaging
from paratext.packaging import package
from paratext.projects import Project
from paratext.sources import video_source
from paratext.video import evenly_spaced

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


def _video(path, seconds=6):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:d={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def test_evenly_spaced_avoids_the_ends():
    assert evenly_spaced(4)(0, 8) == [1.0, 3.0, 5.0, 7.0]
    assert evenly_spaced(2)(10, 20) == [12.5, 17.5]


@needs_ffmpeg
def test_directory_yields_stamped_frames_and_media(tmp_path):
    _video(tmp_path / "a.mp4")
    (tmp_path / "notes.txt").write_text("ignored")
    [s] = list(video_source(frames=evenly_spaced(3)).iter_samples(tmp_path, None))
    assert s.id == "a" and len(s.images) == 3
    assert s.images[0].size == (160, 120 + 20)  # timestamp band below the picture
    assert s.metadata["frame_times"] == [1.0, 3.0, 5.0]
    assert s.metadata["media"]["end"] == pytest.approx(6, abs=0.2)

    plain_source = video_source(frames=evenly_spaced(1), timestamps=False)
    [plain] = list(plain_source.iter_samples(tmp_path, 1))
    assert plain.images[0].size == (160, 120)


@needs_ffmpeg
def test_manifest_clips_one_file_into_several(tmp_path):
    _video(tmp_path / "tape.mp4", seconds=10)
    rows = [
        {"id": "p1", "src": "tape.mp4", "end": 4, "label": "Programme"},
        {"id": "p2", "src": "tape.mp4", "start": 4, "end": 10},
    ]
    manifest = tmp_path / "clips.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows))
    p1, p2 = video_source(frames=evenly_spaced(2)).iter_samples(manifest, None)
    assert p1.metadata["frame_times"] == [1.0, 3.0]
    assert p1.metadata["media"]["label"] == "Programme"
    assert p2.metadata["media"] == {"src": str((tmp_path / "tape.mp4").resolve()),
                                    "start": 4.0, "end": 10.0}


def test_manifest_rows_need_id_and_src(tmp_path):
    manifest = tmp_path / "clips.csv"
    manifest.write_text("id,src\nx,\n")
    with pytest.raises(ValueError, match="row 1: needs an id and a src"):
        list(video_source().iter_samples(manifest, None))


@needs_ffmpeg
def test_packaging_copies_local_video_and_frames(tmp_path, monkeypatch):
    src_dir = tmp_path / "videos"
    src_dir.mkdir()
    _video(src_dir / "a.mp4")
    source = video_source(frames=evenly_spaced(2))
    proj = Project(name="demo", schema_version="v1", prompt="P", schema=_Out, source=source)
    monkeypatch.setattr(packaging, "get_project", lambda name: proj)
    [s] = source.iter_samples(src_dir, None)
    jsonl = tmp_path / "run.jsonl"
    jsonl.write_text(json.dumps({"_provenance": {"project": "demo"}}) + "\n"
                     + json.dumps({"id": s.id, "extraction": {}, "metadata": s.metadata}) + "\n")

    out = tmp_path / "ds"
    package(jsonl, out, "demo", fresh=True)
    [rec] = json.loads((out / "samples.json").read_text())
    assert rec["media"]["src"] == "images/a/video.mp4"
    assert (out / "images/a/video.mp4").stat().st_size == (src_dir / "a.mp4").stat().st_size
    assert rec["images"] == ["images/a/frame_0.jpg", "images/a/frame_1.jpg"]


def test_video_is_served_in_ranges(tmp_path, monkeypatch):
    from paratext.review import server as srv
    from paratext.store import Store

    ds = tmp_path / "ds"
    (ds / "images" / "a").mkdir(parents=True)
    (ds / "samples.json").write_text(json.dumps([{"id": "a"}]))
    (ds / "images" / "a" / "video.mp4").write_bytes(bytes(range(100)))
    monkeypatch.setattr(srv.Handler, "base_data_dir", tmp_path, raising=False)
    monkeypatch.setattr(srv.Handler, "base_store", Store(tmp_path / "a.db"), raising=False)
    monkeypatch.setattr(srv.Handler, "sessions", None, raising=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/images/ds/a/video.mp4"
    try:
        def get(rng):
            req = urllib.request.Request(url, headers={"Range": rng} if rng else {})
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers.get("content-range"), r.read()

        assert get("bytes=10-19") == (206, "bytes 10-19/100", bytes(range(10, 20)))
        assert get("bytes=-5") == (206, "bytes 95-99/100", bytes(range(95, 100)))
        assert get("bytes=90-") == (206, "bytes 90-99/100", bytes(range(90, 100)))
        status, _, body = get(None)
        assert status == 200 and len(body) == 100
        with pytest.raises(urllib.error.HTTPError) as e:
            get("bytes=200-")
        assert e.value.code == 416
    finally:
        httpd.shutdown()
