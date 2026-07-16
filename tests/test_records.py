"""Shared gold-record selection (paratext.records.select_records)."""

import json

from PIL import Image

from paratext.records import select_records
from paratext.review.server import Store


def _mk_round(tmp_path, *, multi_image=False):
    d = tmp_path / "cards-r1"
    (d / "images").mkdir(parents=True)
    samples = []
    for sid in ("a", "b", "c"):
        imgs = []
        for k in range(2 if multi_image else 1):
            rel = f"images/{sid}-{k}.jpg"
            Image.new("RGB", (8, 8), "white").save(d / rel)
            imgs.append(rel)
        samples.append({"id": sid, "document_id": sid, "images": imgs, "prompt_hash": "h",
                        "model_output": {"image_type": "card", "heading": f"H-{sid}"}})
    (d / "samples.json").write_text(json.dumps(samples))
    (d / "provenance.json").write_text(json.dumps({"model": "m", "schema_version": "v1"}))
    store = Store(d / "annotations.db")
    store.upsert("cards-r1", "a", {"model_correct": "good_enough"})
    store.upsert("cards-r1", "b", {"model_correct": "not_accurate"})
    # "c" left unreviewed
    return d, store


def test_select_verified_only(tmp_path):
    d, _ = _mk_round(tmp_path)
    sel = select_records(d, "cards")
    assert [r.sid for r in sel.records] == ["a"]  # good_enough only
    rec = sel.records[0]
    assert rec.status == "verified" and rec.label["heading"] == "H-a"
    assert sel.excluded == {"not_accurate": 1, "unreviewed": 1}
    assert sel.round == 1 and rec.images  # image paths carried, not rejected


def test_select_corrected_overlay(tmp_path):
    d, store = _mk_round(tmp_path)
    store.upsert_gold("cards-r1", "b", {"output": {"heading": "Fixed"}, "fields": ["heading"]})
    sel = select_records(d, "cards")
    by = {r.sid: r for r in sel.records}
    assert set(by) == {"a", "b"}  # b promoted from not_accurate to corrected gold
    assert by["b"].status == "corrected" and by["b"].label["heading"] == "Fixed"
    assert by["b"].verdict == "not_accurate"  # original model verdict preserved
    assert by["b"].label["image_type"] == "card"  # untouched field falls back to model


def test_select_keeps_multi_image(tmp_path):
    # Unlike HF export, the shared selector does NOT reject multi-image records.
    d, _ = _mk_round(tmp_path, multi_image=True)
    sel = select_records(d, "cards")
    assert len(sel.records[0].images) == 2
