"""HF export: gold selection, negatives, multi-image guard, license gate, card."""

import json

import pytest
from PIL import Image

from paratext import hf_export
from paratext.cli import _steer_license
from paratext.review.server import Store


def test_steer_license_defaults_to_cc0(monkeypatch):
    cfg = hf_export.ExportConfig()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")  # accept default
    _steer_license(cfg, "cards")
    assert cfg.license == "cc0-1.0"


def test_steer_license_skip_leaves_blank(monkeypatch):
    cfg = hf_export.ExportConfig()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "s")
    _steer_license(cfg, "cards")
    assert cfg.license is None


def test_steer_license_non_tty_no_prompt(monkeypatch):
    cfg = hf_export.ExportConfig()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError))
    _steer_license(cfg, "cards")  # must not call input()
    assert cfg.license is None


def _mk_dataset(tmp_path, images_per_sample=1):
    """A packaged round dir with 3 samples + an annotations.db (uses the bundled
    `cards` project's schema)."""
    d = tmp_path / "cards-r2"
    (d / "images").mkdir(parents=True)
    samples = []
    for sid in ("a", "b", "c"):
        imgs = []
        for k in range(images_per_sample):
            rel = f"images/{sid}/img{k}.jpg"
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), "white").save(d / rel, "JPEG")
            imgs.append(rel)
        samples.append(
            {
                "id": sid,
                "document_id": sid,
                "model_output": {"image_type": "index_card", "heading": f"H-{sid}"},
                "images": imgs,
                "prompt_hash": "deadbeef",
            }
        )
    (d / "samples.json").write_text(json.dumps(samples))
    (d / "provenance.json").write_text(
        json.dumps({"model": "test-vlm", "schema_version": "v9", "prompt_hash": "deadbeef",
                    "prompt": "extract stuff"})
    )
    store = Store(d / "annotations.db")
    store.upsert("cards-r2", "a", {"model_correct": "good_enough"})
    store.upsert("cards-r2", "b", {"model_correct": "not_accurate", "notes": "wrong heading"})
    # "c" left unreviewed
    return d


def _rows_of(out_dir):
    lines = (out_dir / "metadata.jsonl").read_text().splitlines()
    return {json.loads(x)["_sample_id"]: json.loads(x) for x in lines}


def test_gold_is_good_enough_only(tmp_path):
    # No gold_labels rows → export behaves exactly as before (graceful degradation).
    d = _mk_dataset(tmp_path)
    cfg = hf_export.ExportConfig()
    summary = hf_export.build(d, "cards", cfg, tmp_path / "out")
    assert summary.gold == 1
    assert summary.corrected == 0
    assert summary.negatives == 0
    assert summary.excluded == {"not_accurate": 1, "unreviewed": 1}

    rows = [json.loads(x) for x in (tmp_path / "out" / "metadata.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    r = rows[0]
    assert r["_sample_id"] == "a" and r["_label_status"] == "verified"
    assert r["heading"] == "H-a"  # model output becomes the gold label
    assert r["_model"] == "test-vlm" and r["_schema_version"] == "v9"
    assert (tmp_path / "out" / r["file_name"]).is_file()  # image copied


def test_corrected_row_becomes_gold(tmp_path):
    d = _mk_dataset(tmp_path)
    # A human corrects the not_accurate sample "b" into a gold answer.
    store = Store(d / "annotations.db")
    store.upsert_gold("cards-r2", "b", {
        "output": {"image_type": "verso", "heading": "Corrected H", "text": "t"},
        "fields": ["image_type", "heading", "text"],
    })
    summary = hf_export.build(d, "cards", hf_export.ExportConfig(), tmp_path / "out")
    # a=verified good_enough, b=corrected → 2 gold, 1 corrected, no not_accurate exclusion.
    assert summary.gold == 2 and summary.corrected == 1 and summary.negatives == 0
    assert summary.excluded == {"unreviewed": 1}

    rows = _rows_of(tmp_path / "out")
    b = rows["b"]
    assert b["_label_status"] == "corrected"
    assert b["_verdict"] == "not_accurate"  # original model verdict preserved
    assert sorted(b["_corrected_fields"]) == ["heading", "image_type", "text"]
    assert b["image_type"] == "verso" and b["heading"] == "Corrected H"  # gold label
    # The good_enough row stays verified with the model output as its label.
    assert rows["a"]["_label_status"] == "verified" and rows["a"]["heading"] == "H-a"


def test_corrected_needs_tweaks_row(tmp_path):
    d = _mk_dataset(tmp_path)
    store = Store(d / "annotations.db")
    store.upsert("cards-r2", "c", {"model_correct": "needs_tweaks"})
    store.upsert_gold("cards-r2", "c", {
        "output": {"image_type": "card", "heading": "Fixed"}, "fields": ["heading"]})
    summary = hf_export.build(d, "cards", hf_export.ExportConfig(), tmp_path / "out")
    # a good_enough + c corrected = 2 gold; b still an excluded not_accurate.
    assert summary.gold == 2 and summary.corrected == 1
    rows = _rows_of(tmp_path / "out")
    assert rows["c"]["_label_status"] == "corrected" and rows["c"]["heading"] == "Fixed"
    # Overlay falls back to model_output for fields the human didn't set.
    assert rows["c"]["text"] is None


def test_include_negatives(tmp_path):
    d = _mk_dataset(tmp_path)
    cfg = hf_export.ExportConfig(include_negatives=True)
    summary = hf_export.build(d, "cards", cfg, tmp_path / "out")
    assert summary.gold == 1 and summary.negatives == 1
    rows = [json.loads(x) for x in (tmp_path / "out" / "metadata.jsonl").read_text().splitlines()]
    neg = next(r for r in rows if r["_label_status"] == "rejected")
    assert neg["heading"] is None  # nulled label
    assert neg["_review_note"] == "wrong heading"


def test_multi_image_project_rejected(tmp_path):
    d = _mk_dataset(tmp_path, images_per_sample=2)
    with pytest.raises(SystemExit, match="multi-image"):
        hf_export.build(d, "cards", hf_export.ExportConfig(), tmp_path / "out")


def test_public_without_license_not_blocked(tmp_path, monkeypatch):
    # A missing licence no longer blocks publishing — the card falls back to
    # `license: other` and run() warns instead of refusing.
    monkeypatch.setattr(hf_export, "EXPORT_ROOT", tmp_path / "export")
    d = _mk_dataset(tmp_path)
    cfg = hf_export.ExportConfig(public=True, license=None, repo="x/y")
    summary = hf_export.run(d, "cards", cfg, dry_run=True)
    card = (summary.build_dir / "README.md").read_text()
    assert "license: other" in card


def test_normalise_license_expands_shorthands():
    assert hf_export.normalise_license("cc0") == "cc0-1.0"
    assert hf_export.normalise_license("Apache") == "apache-2.0"
    assert hf_export.normalise_license("cc-by-4.0") == "cc-by-4.0"  # already canonical
    assert hf_export.normalise_license("  MIT ") == "mit"
    assert hf_export.normalise_license("weird-thing") == "weird-thing"  # unknown: passthrough
    assert hf_export.normalise_license(None) is None


def test_shorthand_license_canonical_in_card(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_export, "EXPORT_ROOT", tmp_path / "export")
    d = _mk_dataset(tmp_path)
    cfg = hf_export.ExportConfig(license="cc0")  # shorthand
    summary = hf_export.run(d, "cards", cfg, dry_run=True)
    card = (summary.build_dir / "README.md").read_text()
    assert "license: cc0-1.0" in card  # normalised for the Hub


def test_unrecognised_license_soft_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hf_export, "EXPORT_ROOT", tmp_path / "export")
    d = _mk_dataset(tmp_path)
    cfg = hf_export.ExportConfig(license="my-custom-licence")
    hf_export.run(d, "cards", cfg, dry_run=True)  # not blocked
    assert "isn't a recognised HF licence id" in capsys.readouterr().out


def test_dry_run_builds_card(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_export, "EXPORT_ROOT", tmp_path / "export")
    d = _mk_dataset(tmp_path)
    cfg = hf_export.ExportConfig(license="cc-by-4.0")
    summary = hf_export.run(d, "cards", cfg, dry_run=True)
    assert summary.build_dir == tmp_path / "export" / "cards-r2"
    card = (summary.build_dir / "README.md").read_text()
    assert "license: cc-by-4.0" in card
    assert "extract stuff" in card  # prompt inlined
    assert "`image_type`" in card  # schema field table


def test_card_renders_energy(tmp_path):
    d = _mk_dataset(tmp_path)
    prov = json.loads((d / "provenance.json").read_text())
    prov["energy"] = {"provider": "uk", "zone": "South Scotland", "carbon_gco2": 5,
                      "renewable_fraction": 0.85, "scheduled_window": True,
                      "ts": "2026-07-02T01:00Z"}
    (d / "provenance.json").write_text(json.dumps(prov))
    hf_export.build(d, "cards", hf_export.ExportConfig(license="cc-by-4.0"), tmp_path / "out")
    card = (tmp_path / "out" / "README.md").read_text()
    assert "Environmental provenance" in card
    assert "South Scotland" in card and "85% renewable" in card
    assert "scheduled to a low-carbon window" in card
