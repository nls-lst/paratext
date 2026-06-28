"""JSONL append, resume, provenance, error sidecar."""

import json

from paratext import io


def test_provenance_roundtrip(tmp_path):
    p = tmp_path / "out.jsonl"
    io.write_provenance_header(p, {"project": "x", "prompt_hash": "abc"})
    prov = io.read_provenance(p)
    assert prov["project"] == "x"
    assert prov["prompt_hash"] == "abc"
    assert "git_commit" in prov and "timestamp" in prov


def test_provenance_header_not_overwritten(tmp_path):
    p = tmp_path / "out.jsonl"
    io.write_provenance_header(p, {"project": "a"})
    io.write_provenance_header(p, {"project": "b"})  # file exists -> no-op
    assert io.read_provenance(p)["project"] == "a"


def test_resume_ids_skip_provenance(tmp_path):
    p = tmp_path / "out.jsonl"
    io.write_provenance_header(p, {"project": "x"})
    io.append_jsonl(p, {"id": "a", "extraction": {}})
    io.append_jsonl(p, {"id": "b", "extraction": {}})
    assert io.read_processed_ids(p) == {"a", "b"}


def test_iter_records_skips_provenance(tmp_path):
    p = tmp_path / "out.jsonl"
    io.write_provenance_header(p, {"project": "x"})
    io.append_jsonl(p, {"id": "a"})
    recs = list(io.iter_records(p))
    assert len(recs) == 1 and recs[0]["id"] == "a"


def test_append_error_writes_sidecar(tmp_path):
    p = tmp_path / "out.jsonl"
    io.append_error(p, "s1", "boom")
    err = tmp_path / "out_errors.jsonl"
    assert err.exists()
    rec = json.loads(err.read_text().splitlines()[0])
    assert rec["id"] == "s1" and rec["error"] == "boom"
