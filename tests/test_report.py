"""The carbon report: CSV rows and the HTML page, from sidecars."""

import csv
import json

from paratext import cli, report, tracking


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
           "zone": "South Scotland", "min_renewable": 70, "paused_s": paused,
           "pauses": [], "intervals": ivs if meter else [],
           "timeline": [[f"{start[:11]}0{h}:00:00Z", 100.0] for h in range(3)] if meter else []}
    seg.update(tracking.totals(seg))
    return seg


def test_rows_and_csv(tmp_path):
    runs_dir = tmp_path / "runs"
    _sidecar(runs_dir, "a", "monographs", [_seg("2026-10-27T00:00:00Z", 100),
                                           _seg("2026-10-28T00:00:00Z", 100, paused=3600)])
    _sidecar(runs_dir, "b", "cards", [_seg("2026-11-02T00:00:00Z", 0, meter=None, records=7)])
    csv_path, html_path, n = report.build(runs_dir, tmp_path / "rep")
    assert n == 2
    rows = list(csv.DictReader(csv_path.open()))
    a = next(r for r in rows if r["project"] == "monographs")
    assert a["kwh"] == "0.6" and a["records"] == "200" and a["sessions"] == "2"
    assert a["wh_per_record"] == "3.0" and a["gco2e"] == "30.0"
    assert a["clean_share"] == "1.0" and a["hours_paused"] == "1.0"
    b = next(r for r in rows if r["project"] == "cards")
    assert b["meter"] == "not measured" and b["kwh"] == "" and b["records"] == "7"
    page = html_path.read_text()
    assert "<svg" in page and "Energy by month" in page and "not measured" in page
    assert "http" not in page.split("<body>")[1].split("<script")[0].replace(
        "https://", "")  # nothing fetched from the network


def test_empty_report_still_renders(tmp_path):
    csv_path, html_path, n = report.build(tmp_path / "none", tmp_path / "rep")
    assert n == 0 and "No measured runs yet" in html_path.read_text()
    assert csv_path.read_text().startswith("project,output")


def test_colour_follows_the_project():
    assert report._colors(["b", "a", "b"]) == {"a": 0, "b": 1}


def test_carbon_command_writes_the_report(tmp_path, capsys):
    assert cli.main(["carbon"]) == 0
    out = capsys.readouterr().out
    assert "not declared" in out and "Report" in out
    assert (report.REPORT_DIR / "carbon.html").is_file()


def test_grid_section_draws_the_forecast(tmp_path):
    from paratext import carbon
    vals = [0.9] * 10 + [0.5] * 4 + [0.9] * 10
    mix = {"wind": 60, "gas": 30, "other": 10}
    series = [carbon.Reading("uk", "South Scotland", 10, v, None,
                             f"2026-10-27T{8 + i // 2:02d}:{30 * (i % 2):02d}Z", mix=mix)
              for i, v in enumerate(vals)]
    _, html_path, _ = report.build(tmp_path / "none", tmp_path / "rep", forecast=series)
    page = html_path.read_text()
    assert "next 12 hours" in page and page.count('class="col"') == 4
    assert 'class="thr"' in page and "Imports &amp;amp; other" in page
    _, html_path, _ = report.build(tmp_path / "none", tmp_path / "rep")
    assert "next 12 hours" not in html_path.read_text()


def test_run_blocks_weight_renewables_by_energy():
    seg = _seg("2026-10-27T00:00:00Z", 100)
    seg["intervals"][0]["renewable_fraction"] = 0.5
    blocks = report._run_blocks(report.Run({}, [seg]))
    assert len(blocks) == 3 and blocks[0]["r"] == 50 and blocks[1]["m"]["rest"] == 20
