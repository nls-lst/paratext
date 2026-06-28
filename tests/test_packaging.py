"""Packaging keep/drop rules — the bundled `cards` starter project."""

import json

from PIL import Image
from pydantic import BaseModel

import paratext.packaging as packaging
from paratext.packaging import package
from paratext.projects import Curation, Project


def _tiny_jpg(path):
    Image.new("RGB", (10, 10), "white").save(path, "JPEG")


def test_cards_keeps_cards_drops_non_cards(tmp_path):
    img = tmp_path / "c.jpg"
    _tiny_jpg(img)
    jsonl = tmp_path / "run.jsonl"
    meta = {"image_path": str(img)}
    lines = [
        {"_provenance": {"project": "cards", "prompt": "P", "prompt_hash": "h"}},
        {"id": "a", "extraction": {"image_type": "card"}, "metadata": meta},
        {"id": "b", "extraction": {"image_type": "verso"}, "metadata": meta},
        {"id": "c", "extraction": {"image_type": "blank"}, "metadata": meta},
    ]
    jsonl.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    out = tmp_path / "ds"
    kept, skipped = package(jsonl, out, "cards", fresh=True)

    assert kept == 1  # only the `card` is kept
    assert skipped == {"verso": 1, "blank": 1}
    records = json.loads((out / "samples.json").read_text())
    assert {r["id"] for r in records} == {"a"}
    # prompt text + hash are stamped onto every record from provenance
    assert all(r["prompt"] == "P" and r["prompt_hash"] == "h" for r in records)

    # packaging also emits the display/review contract
    view = json.loads((out / "view.json").read_text())
    assert view["schema"] == "cards" and view["layout"] == "split"


class _Out(BaseModel):
    kind: str = "x"


def test_generic_loop_keep_drop_quarantine(tmp_path, monkeypatch):
    """The project-agnostic packager routes records by the curate() hook:
    keep -> samples.json, drop -> skipped only, quarantine -> ephemera file."""

    def curate(rec):
        return Curation(rec["extraction"]["kind"], rec["extraction"].get("reason"))

    proj = Project(
        name="demo",
        schema_version="v1",
        prompt="P",
        schema=_Out,
        iter_samples=lambda *a: iter(()),
        curate=curate,
        materialise_images=lambda rec, out, mx: [],  # no images needed
        ground_truth=lambda rec: {"g": rec["id"]} if rec["id"] == "k" else None,
    )
    monkeypatch.setattr(packaging, "get_project", lambda name: proj)

    lines = [
        {"_provenance": {"project": "demo", "prompt": "P", "prompt_hash": "h"}},
        {"id": "k", "extraction": {"kind": "keep"}},
        {"id": "d", "extraction": {"kind": "drop", "reason": "verso"}},
        {"id": "q", "extraction": {"kind": "quarantine", "reason": "poster"}},
    ]
    jsonl = tmp_path / "run.jsonl"
    jsonl.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    out = tmp_path / "ds"
    kept, skipped = package(jsonl, out, "demo", fresh=True)

    assert kept == 1
    assert skipped == {"verso": 1, "poster": 1}
    records = json.loads((out / "samples.json").read_text())
    assert [r["id"] for r in records] == ["k"]
    assert records[0]["ground_truth"] == {"g": "k"}  # gt hook attached
    ephemera = json.loads((out / "samples-ephemera.json").read_text())
    assert [r["id"] for r in ephemera] == ["q"]
