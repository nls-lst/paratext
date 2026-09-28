"""A sample's media: validated and defaulted at packaging (paratext.media)."""

import json

import pytest
from test_packaging import _Out

import paratext.packaging as packaging
from paratext.media import MediaError, normalise_media
from paratext.packaging import package
from paratext.projects import Project


def test_defaults_and_type_inference():
    assert normalise_media({"src": "https://x/clip.m3u8?t=1"}) == {
        "src": "https://x/clip.m3u8?t=1", "type": "hls", "start": 0, "tracks": []}
    assert normalise_media({"src": "clip.mp4"})["type"] == "file"


def test_tracks_keep_notes_and_open_ended_items():
    m = normalise_media({
        "src": "a.mp4", "start": 10, "end": 40, "label": "Programme",
        "tracks": [{"name": "NLS", "note": "times are approximate",
                    "items": [{"start": 10, "text": "Opening"}]}],
    })
    assert m["label"] == "Programme"
    assert m["tracks"] == [{"name": "NLS", "note": "times are approximate",
                            "items": [{"start": 10, "text": "Opening"}]}]


@pytest.mark.parametrize("bad, msg", [
    ({}, "src"),
    ({"src": "a.mp4", "approx": True}, "unknown"),
    ({"src": "a.mp4", "start": 5, "end": 5}, "after start"),
    ({"src": "a.mp4", "start": -1}, "non-negative"),
    ({"src": "a.mp4", "tracks": [{"name": "K", "items": []}]}, "need an end"),
    ({"src": "a.mp4", "end": 9, "tracks": [{"items": []}]}, "name"),
])
def test_rejects_bad_media(bad, msg):
    with pytest.raises(MediaError, match=msg):
        normalise_media(bad)


def _package(tmp_path, monkeypatch, media):
    proj = Project(
        name="demo", schema_version="v1", prompt="P", schema=_Out,
        iter_samples=lambda *a: iter(()),
        materialise_images=lambda rec, out, mx: [],
    )
    monkeypatch.setattr(packaging, "get_project", lambda name: proj)
    lines = [
        {"_provenance": {"project": "demo", "prompt": "P", "prompt_hash": "h"}},
        {"id": "v1", "extraction": {}, "metadata": {"media": media}},
    ]
    jsonl = tmp_path / "run.jsonl"
    jsonl.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    package(jsonl, tmp_path / "ds", "demo", fresh=True)
    return json.loads((tmp_path / "ds" / "samples.json").read_text())[0]


def test_packaging_carries_media_from_sample_metadata(tmp_path, monkeypatch):
    rec = _package(tmp_path, monkeypatch, {"src": "v.m3u8", "end": 30})
    assert rec["media"] == {"src": "v.m3u8", "type": "hls", "start": 0, "end": 30, "tracks": []}


def test_packaging_names_the_sample_with_bad_media(tmp_path, monkeypatch):
    with pytest.raises(MediaError, match="sample v1: media needs a src"):
        _package(tmp_path, monkeypatch, {"poster": "p.jpg"})
