"""The carbon report: CSV rows and the Word file, from sidecars."""

import csv
import json
import zipfile

import pytest

from paratext import cli, report, tracking, wordfile


@pytest.fixture(autouse=True)
def _no_libreoffice(monkeypatch):
    monkeypatch.setattr(wordfile, "to_pdf", lambda paths: [])


def _sidecar(dirpath, name, project, segs):
    dirpath.mkdir(parents=True, exist_ok=True)
    doc = {"schema": tracking.SCHEMA, "output": f"output/{name}.jsonl", "project": project,
           "model": "qwen", "segments": segs}
    (dirpath / f"{name}.json").write_text(json.dumps(doc))


def _seg(start, wh_per_iv, g=50, ren=0.8, records=100, meter="amdgpu-apu", paused=0):
    ivs = [{"from": f"{start[:11]}{h:02d}:00:00Z", "wh": wh_per_iv, "gco2_per_kwh": g,
            "renewable_fraction": ren, "basis": "forecast"} for h in range(3)]
    seg = {"start": start, "end": f"{start[:11]}03:00:00Z", "records": records,
           "endpoint": "local" if meter else "hosted", "meter": meter, "overhead": 1.0,
           "zone": "South Scotland", "min_renewable": 70, "wait": True, "paused_s": paused,
           "pauses": [], "intervals": ivs if meter else [],
           "timeline": [[f"{start[:11]}0{h}:00:00Z", 100.0] for h in range(3)] if meter else []}
    seg.update(tracking.totals(seg))
    return seg


def _parts(docx):
    with zipfile.ZipFile(docx) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_rows_csv_and_reports(tmp_path):
    runs_dir = tmp_path / "runs"
    _sidecar(runs_dir, "a", "monographs", [_seg("2026-10-27T00:00:00Z", 100),
                                           _seg("2026-10-28T00:00:00Z", 100, paused=3600)])
    _sidecar(runs_dir, "b", "cards", [_seg("2026-11-02T00:00:00Z", 0, meter=None, records=7)])
    built = report.build(runs_dir, tmp_path / "rep")
    assert len(built.runs) == 2 and built.rebuilt == 2 and not built.pdf
    rows = list(csv.DictReader(built.csv.open()))
    a = next(r for r in rows if r["project"] == "monographs")
    assert a["kwh"] == "0.6" and a["records"] == "200" and a["sessions"] == "2"
    assert a["wh_per_record"] == "3.0" and a["gco2e"] == "30.0"
    assert a["clean_share"] == "1.0" and a["hours_paused"] == "1.0"
    b = next(r for r in rows if r["project"] == "cards")
    assert b["meter"] == "not measured" and b["kwh"] == "" and b["records"] == "7"
    assert sorted(p.name for p in built.projects) == ["cards.docx", "monographs.docx"]
    project = _parts(tmp_path / "rep" / "monographs.docx")
    assert "By month" in project["word/document.xml"].decode()
    charts = [p for p in project if p.startswith("word/charts/chart")]
    assert charts and len(charts) == len([p for p in project if p.startswith("word/embed")])
    run = _parts(runs_dir / "a.docx")["word/document.xml"].decode()
    assert "Where the energy came from" in run and "Waiting" not in run
    assert "Not measured" in _parts(runs_dir / "b.docx")["word/document.xml"].decode()


def test_finished_run_reports_are_not_rebuilt(tmp_path):
    runs_dir = tmp_path / "runs"
    _sidecar(runs_dir, "a", "monographs", [_seg("2026-10-27T00:00:00Z", 100)])
    assert report.build(runs_dir, tmp_path / "rep").rebuilt == 1
    assert report.build(runs_dir, tmp_path / "rep").rebuilt == 0


def test_energy_is_split_by_the_grid_mix():
    ivs = [(100, {"mix": {"wind": 60, "gas": 30, "other": 10}}),
           (50, {"renewable_fraction": 0.8}), (10, {})]
    got = report._by_source(ivs)
    assert got["wind"] == 60 and got["imports"] == 10 and got["renewable"] == 40
    assert got["rest"] == pytest.approx(10) and got["unknown"] == 10


def test_empty_report_still_renders(tmp_path):
    built = report.build(tmp_path / "none", tmp_path / "rep")
    assert built.runs == [] and built.projects == []
    assert built.csv.read_text().startswith("project,output")


def test_colour_follows_the_project():
    assert report._colors(["b", "a", "b"]) == {"a": 0, "b": 1}


@pytest.mark.parametrize("mid, name", [
    ("user.Qwen3.6-35B-A3B-GGUF-Q8_0", "Qwen3.6 · 35B (3B active) · 8-bit"),
    ("unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_M", "Qwen3.6 · 35B (3B active) · 4-bit"),
    ("Qwen/Qwen3-VL-8B-Instruct", "Qwen3-VL-Instruct · 8B"),
    ("gpt-4o", "gpt-4o"),
    ("", ""),
])
def test_model_names_read_like_the_status_widget(mid, name):
    assert report.model_name(mid) == name


def test_carbon_command_writes_the_report(tmp_path, capsys):
    assert cli.main(["carbon"]) == 0
    out = capsys.readouterr().out
    assert "not declared" in out and "Reports" in out
    assert (report.REPORT_DIR / "carbon.csv").is_file()
