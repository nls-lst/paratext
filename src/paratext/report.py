"""`paratext carbon`'s report: one CSV row per run, and a Word file of charts.

Both are rebuilt in full from the sidecars in `output/carbon/runs/` every time.
The charts are native Word charts, so they can be edited or pasted into a
sustainability return. A PDF copy is made when LibreOffice is installed.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from . import tracking, wordfile
from .carbon import parse_ts

REPORT_DIR = Path("output/carbon")

CSV_COLUMNS = [
    "project", "output", "model", "start", "end", "sessions", "records", "kwh",
    "wh_per_record", "gco2e", "renewable_share", "clean_share", "hours_paused",
    "endpoint", "meter", "overhead", "zone", "intensity_basis",
]

# Categorical slots in fixed order (light, dark); colour follows the project.
SLOTS = [
    ("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"),
    ("#eda100", "#c98500"), ("#e87ba4", "#d55181"), ("#008300", "#008300"),
    ("#6250d6", "#9085e9"), ("#e34948", "#e66767"),
]


@dataclass
class Run:
    doc: dict
    segments: list[dict] = field(default_factory=list)
    path: Path | None = None  # the sidecar

    @property
    def name(self) -> str:
        return self.path.stem if self.path else self.title

    @property
    def title(self) -> str:
        return Path(self.doc.get("output", "")).stem or self.project

    @property
    def mtime(self) -> float:
        return self.path.stat().st_mtime if self.path else 0.0

    @property
    def project(self) -> str:
        return self.doc.get("project") or "?"

    @property
    def measured(self) -> list[dict]:
        return [s for s in self.segments if s.get("meter")]

    def intervals(self):
        """(datetime, wh, gco2e, segment) per interval, overhead applied."""
        for s in self.measured:
            k = s.get("overhead", 1.0)
            for iv in s.get("intervals", []):
                t = parse_ts(iv.get("from"))
                if t is None:
                    continue
                wh = iv["wh"] * k
                g = iv.get("gco2_per_kwh")
                yield t, wh, (wh / 1000 * g if g is not None else None), iv, s

    def row(self) -> dict:
        segs = self.segments
        meas = self.measured
        records = sum(s.get("records", 0) for s in segs)
        wh = sum(s.get("wh") or 0 for s in meas) if meas else None
        gs = [s["gco2e"] for s in meas if s.get("gco2e") is not None]
        rated = [(wh_, iv["renewable_fraction"]) for _, wh_, _, iv, _ in self.intervals()
                 if iv.get("renewable_fraction") is not None and wh_ > 0]
        rated_wh = sum(w for w, _ in rated)
        clean = [(wh_, iv["renewable_fraction"] * 100 >= s.get("min_renewable", 70))
                 for _, wh_, _, iv, s in self.intervals()
                 if iv.get("renewable_fraction") is not None and wh_ > 0]
        meters_ = sorted({s["meter"] for s in meas})
        bases = sorted({s["intensity_basis"] for s in meas if s.get("intensity_basis")})
        overheads = sorted({s.get("overhead", 1.0) for s in meas})
        zones = sorted({s["zone"] for s in segs if s.get("zone")})
        endpoints = sorted({s.get("endpoint", "local") for s in segs})
        return {
            "project": self.project,
            "output": self.doc.get("output", ""),
            "model": self.doc.get("model", ""),
            "start": segs[0].get("start", "") if segs else "",
            "end": segs[-1].get("end", "") if segs else "",
            "sessions": len(segs),
            "records": records,
            "kwh": round(wh / 1000, 4) if wh is not None else None,
            "wh_per_record": round(wh / records, 3) if wh is not None and records else None,
            "gco2e": round(sum(gs), 2) if gs else None,
            "renewable_share": (round(sum(w * f for w, f in rated) / rated_wh, 3)
                                if rated_wh else None),
            "clean_share": (round(sum(w for w, ok in clean if ok) / sum(w for w, _ in clean), 3)
                            if clean else None),
            "hours_paused": round(sum(s.get("paused_s", 0) for s in segs) / 3600, 2),
            "endpoint": "+".join(endpoints),
            "meter": "+".join(meters_) if meters_ else "not measured",
            "overhead": "/".join(f"{o:g}" for o in overheads) if overheads else "",
            "zone": "/".join(zones),
            "intensity_basis": "/".join(bases),
        }


def collect(runs_dir: Path | None = None) -> list[Run]:
    runs = []
    for p in sorted((runs_dir or tracking.RUNS_DIR).glob("*.json")):
        doc = tracking.load_sidecar(p)
        if not doc or doc.get("schema") != tracking.SCHEMA:
            continue
        runs.append(Run(doc, doc.get("segments", []), p))
    runs.sort(key=lambda r: r.segments[0].get("start", "") if r.segments else "")
    return runs


def write_csv(runs: list[Run], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in runs:
            w.writerow({k: ("" if v is None else v) for k, v in r.row().items()})


class Built(NamedTuple):
    csv: Path
    projects: list[Path]  # one report per project, PDF where made
    runs: list[Path]  # one report per run, newest last
    rebuilt: int  # run reports rebuilt this time
    pdf: bool  # whether LibreOffice made PDFs


def build(runs_dir: Path | None = None, out_dir: Path | None = None) -> Built:
    """Write carbon.csv, a report per project, and a report per run.

    Runs with nothing measured are in the CSV only. Project reports are rebuilt every
    time; a run's report only when its sidecar is newer."""
    out = out_dir or REPORT_DIR
    runs_dir = runs_dir or tracking.RUNS_DIR
    runs = collect(runs_dir)
    csv_path = out / "carbon.csv"
    write_csv(runs, csv_path)
    fresh: list[Path] = []
    by_project: dict[str, list[Run]] = defaultdict(list)
    for r in runs:
        by_project[r.project].append(r)
    projects = []
    for name, rs in sorted(by_project.items()):
        if any(r.measured for r in rs):
            projects.append(project_report(name, rs).save(out / f"{_slug(name)}.docx"))
    fresh += projects
    run_docs = []
    for r in (r for r in runs if r.measured):
        path = runs_dir / f"{r.name}.docx"
        if not path.is_file() or path.stat().st_mtime < r.mtime:
            run_report(r).save(path)
            fresh.append(path)
        run_docs.append(path)
    pdfs = set(wordfile.to_pdf(fresh))
    made = bool(pdfs) or not fresh

    def best(p: Path) -> Path:
        pdf = p.with_suffix(".pdf")
        return pdf if pdf in pdfs or (p not in fresh and pdf.is_file()) else p

    return Built(csv_path, [best(p) for p in projects], [best(p) for p in run_docs],
                 len(fresh) - len(projects), made)


def _slug(s: str) -> str:
    return re.sub(r"[^\w.-]+", "-", s).strip("-") or "project"


# ── formatting ───────────────────────────────────────────────────────────────
def _num(v: float | None, unit: str = "", digits: int = 2) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e6:
        s = f"{v / 1e6:.1f}M"
    elif a >= 1e4:
        s = f"{v / 1e3:.1f}K"
    elif a >= 100:
        s = f"{v:,.0f}"
    elif a >= 10:
        s = f"{v:.1f}"
    else:
        s = f"{v:.{digits}f}"
    return f"{s}{unit}"


def _pct(v: float) -> str:
    return "<1%" if 0 < v < 1 else f"{v:.0f}%"


def _hm(t: datetime) -> str:
    return f"{t.astimezone():%H:%M}"


def _day(t: datetime) -> str:
    return f"{t.astimezone():%a}"


def _avg(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _colors(projects: list[str]) -> dict[str, int]:
    return {p: min(i, len(SLOTS) - 1) for i, p in enumerate(sorted(set(projects)))}


def _month_label(m: str) -> str:
    try:
        return datetime.strptime(m, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return m


# ── model names, as on the ai.nls.uk status widget ───────────────────────────
_QUANT = re.compile(r"^(I?Q\d\w*|F16|BF16|F32|MXFP4\w*)$", re.I)
_SIZE = re.compile(r"^\d+(\.\d+)?[BM]$", re.I)
_ACTIVE = re.compile(r"^A\d+(\.\d+)?[BM]$", re.I)


def _bits(quant: str) -> str | None:
    q = quant.upper()
    if q == "F32":
        return "32-bit"
    if q in ("F16", "BF16"):
        return "16-bit"
    if q.startswith("MXFP4"):
        return "4-bit"
    digits = "".join(ch for ch in q.split("_")[0] if ch.isdigit())
    return f"{digits}-bit" if digits else None


def model_name(mid: str) -> str:
    """`user.Qwen3.6-35B-A3B-GGUF-Q8_0` → `Qwen3.6 · 35B (3B active) · 8-bit`."""
    if not mid:
        return ""
    repo, _, quant = mid.removeprefix("user.").partition(":")
    tokens = [t for t in repo.rpartition("/")[2].split("-") if t.upper() != "GGUF"]
    if not quant and len(tokens) > 1 and _QUANT.match(tokens[-1]):
        quant = tokens.pop()
    size = None
    for i, t in enumerate(tokens):
        if i and _SIZE.match(t):
            size = t.upper()
            if i + 1 < len(tokens) and _ACTIVE.match(tokens[i + 1]):
                size += f" ({tokens.pop(i + 1)[1:].upper()} active)"
            tokens.pop(i)
            break
    parts = ["-".join(tokens), size, _bits(quant) if quant else None]
    return " · ".join(p for p in parts if p)


# ── where the energy came from ───────────────────────────────────────────────
# Stacked bottom up. Colours match the status widget. "renewable" and "rest"
# stand in when the grid gave a renewable share but no mix.
FUELS = [
    ("wind", "Wind", "2A78D6"), ("solar", "Solar", "EDA100"), ("hydro", "Hydro", "1BAF7A"),
    ("imports", "Imports & other", "E87BA4"), ("nuclear", "Nuclear", "6250D6"),
    ("biomass", "Biomass", "008300"), ("gas", "Gas", "EB6834"), ("coal", "Coal", "6B6A65"),
    ("renewable", "Renewable", "1BAF7A"), ("rest", "Other sources", "C3C2B7"),
    ("unknown", "No grid data", "E1E0D9"),
]


def _split(iv: dict) -> dict[str, float]:
    """An interval's grid as fractions by source, summing to 1."""
    if iv.get("mix"):
        m = dict(iv["mix"])
        m["imports"] = m.get("imports", 0) + m.pop("other", 0)
    elif iv.get("renewable_fraction") is not None:
        m = {"renewable": iv["renewable_fraction"], "rest": 1 - iv["renewable_fraction"]}
    else:
        m = {"unknown": 1}
    total = sum(m.values()) or 1
    return {k: v / total for k, v in m.items()}


def _by_source(items) -> dict[str, float]:
    """Wh by source, from (wh, interval) pairs."""
    out: dict[str, float] = defaultdict(float)
    for wh, iv in items:
        for k, f in _split(iv).items():
            out[k] += wh * f
    return out


def _blocks(run: Run) -> tuple[list[dict], float]:
    """The run's energy per hour by source in at most 24 equal blocks; also the block size."""
    ivs = sorted(((t, wh, iv, s) for t, wh, _, iv, s in run.intervals()), key=lambda x: x[0])
    if not ivs:
        return [], 0
    span_h = (ivs[-1][0] - ivs[0][0]).total_seconds() / 3600 + 0.5
    size = next((h for h in (0.5, 1, 3, 6, 12, 24) if span_h / h <= 24), 48)
    out: list[dict] = []
    for t, wh, iv, seg in ivs:
        sec = t.timestamp()
        start = datetime.fromtimestamp(sec - sec % (size * 3600), timezone.utc)
        if not out or out[-1]["t"] != start:
            out.append({"t": start, "items": [], "h": 0.0})
        out[-1]["items"].append((wh, iv))
        out[-1]["h"] += _hours_run(t, seg)
    for b in out:
        h = b.pop("h") or size
        b["wh"] = {k: v / h for k, v in _by_source(b.pop("items")).items()}
    return out, size


def _time_labels(times: list[datetime], most: int = 8) -> list[str]:
    """Every nth time, with the day when it changes; LibreOffice ignores label skipping."""
    step, last, out = math.ceil(len(times) / most), None, []
    for i, t in enumerate(times):
        if i % step:
            out.append("")
            continue
        out.append(_hm(t) if _day(t) == last else f"{_day(t)} {_hm(t)}")
        last = _day(t)
    return out


def _hours_run(t: datetime, seg: dict) -> float:
    """How much of the half hour from t the segment was running."""
    lo = max(t, parse_ts(seg.get("start")) or t)
    hi = min(t + timedelta(minutes=30), parse_ts(seg.get("end")) or t + timedelta(minutes=30))
    return max((hi - lo).total_seconds(), 0) / 3600


def _source_chart(cats: list[str], parts: list[dict[str, float]], unit: str,
                  scale: float) -> dict:
    total = sum(sum(p.values()) for p in parts) or 1
    keys = {k for k in {k for p in parts for k in p}
            if sum(p.get(k, 0) for p in parts) / total >= 0.005}
    top = wordfile.nice_max(max((sum(p.values()) for p in parts), default=0) / scale)
    return {
        "type": "col", "stacked": True, "gap": 30 if len(cats) > 3 else 300, "legend": True,
        "ymax": top, "ystep": top / 2, "yfmt": f'0.##" {unit}"',
        "categories": cats,
        "series": [{"name": label, "color": color,
                    "values": [round(p.get(k, 0) / scale, 3) for p in parts]}
                   for k, label, color in FUELS if k in keys],
    }


def _energy_unit(wh: float) -> tuple[str, float]:
    return ("kWh", 1000.0) if wh >= 1000 else ("Wh", 1.0)


def _mix_block(doc: wordfile.Doc, wh: dict[str, float]) -> str:
    """The ring and list: total energy by source, renewable share in the list head."""
    W = wordfile
    total = sum(wh.values())
    if total <= 0:
        return ""
    parts = [(label, color, wh[k]) for k, label, color in FUELS if wh.get(k, 0) / total >= 0.005]
    ring = doc.chart({"type": "doughnut", "categories": [p[0] for p in parts],
                      "series": [{"name": "Energy", "colors": [p[1] for p in parts],
                                  "values": [round(p[2], 2) for p in parts]}]}, 3.4, 3.4)
    unit, scale = _energy_unit(max(p[2] for p in parts))
    rows = [[W.para(W.run("■ ", color=c), label, style="TableText"),
             W.para(W.run(f"{v / scale:.{2 if scale > 1 else 0}f} {unit}", bold=True),
                    style="TableText", align="right"),
             W.para(W.run(_pct(v / total * 100), color=W.INK2), style="TableText",
                    align="right")] for label, c, v in parts]
    return W.table([[ring, W.table(rows, [2.8, 1.8, 1.2], lines=False)]], [4.2, 6.0],
                   lines=False)


# ── document ─────────────────────────────────────────────────────────────────
def _stat(label: str, value: str, unit: str = "") -> str:
    W = wordfile
    return (W.para(W.run(label, size=8.5, color=W.INK2), after=0)
            + W.para(W.run(value, bold=True, size=16),
                     W.run(f" {unit}" if unit else "", size=8.5, color=W.INK2), after=0))


def _stats(rows: list[dict], renewable: float | None) -> str:
    kwh = [r["kwh"] for r in rows if r["kwh"] is not None]
    g = [r["gco2e"] for r in rows if r["gco2e"] is not None]
    records = sum(r["records"] for r in rows)
    measured_records = sum(r["records"] for r in rows if r["kwh"] is not None)
    per = sum(kwh) * 1000 / measured_records if kwh and measured_records else None
    return wordfile.table([[
        _stat("Energy", _num(sum(kwh)) if kwh else "—", "kWh" if kwh else ""),
        _stat("Emissions", _num(sum(g)) if g else "—", "g CO₂e" if g else ""),
        _stat("Records", f"{records:,}"),
        _stat("Per record", _num(per) if per is not None else "—", "Wh" if per else ""),
        _stat("Renewable", f"{renewable * 100:.0f}%" if renewable is not None else "—"),
    ]], [3.4] * 5, lines=False)


def _renewable(runs: list[Run]) -> float | None:
    rated = [(wh, iv["renewable_fraction"]) for r in runs for _, wh, _, iv, _ in r.intervals()
             if iv.get("renewable_fraction") is not None and wh > 0]
    total = sum(w for w, _ in rated)
    return sum(w * f for w, f in rated) / total if total else None


def _head(doc: wordfile.Doc, title: str, *notes: str) -> None:
    doc.add(wordfile.para(title, style="Title"),
            *[wordfile.para(n, style="Note", after=0) for n in notes],
            wordfile.para(style="Gap", after=200))


def _duration(seconds: float) -> str:
    h, m = divmod(round(seconds / 60), 60)
    return f"{h} h {m} min" if h else f"{m} min"


def run_report(run: Run) -> wordfile.Doc:
    """One page for one run: its figures, where its energy came from, and how."""
    W = wordfile
    row = run.row()
    segs = run.segments
    t0, t1 = parse_ts(row["start"]), parse_ts(row["end"])
    span = f"{_when(row['start'], year=True)} – {_when(row['end'], year=True)}"
    if t0 and t1:
        span += f" · {_duration((t1 - t0).total_seconds())}"
    doc = W.Doc(f"Carbon report: {run.title}")
    _head(doc, run.title, f"{run.project} · {model_name(run.doc.get('model', ''))}", span)
    doc.add(_stats([row], _renewable([run])))
    doc.add(W.para("Where the energy came from", style="Heading1"),
            _mix_block(doc, _by_source((wh, iv) for _, wh, _, iv, _ in run.intervals())))
    blocks, size = _blocks(run)
    if blocks:
        every = {0.5: ", averaged every half hour", 1: ""}.get(
            size, f", averaged every {size:g} hours")
        unit, scale = _energy_unit(max(sum(b["wh"].values()) for b in blocks))
        doc.add(W.para(f"Energy per hour{every}", style="Heading2"), doc.chart(
            _source_chart(_time_labels([b["t"] for b in blocks]),
                          [b["wh"] for b in blocks], unit, scale), 17, 6))
    notes = sorted({s.get("meter_note") or s.get("meter") or "" for s in run.measured} - {""})
    details = [
        ["Output", run.doc.get("output", "")],
        ["Model", run.doc.get("model", "")],
        ["Sessions", f"{len(segs)}"],
        ["Meter", " + ".join(notes)],
        ["Grid", " · ".join(x for x in (row["zone"], _provider(segs), row["intensity_basis"])
                            if x) or "not declared"],
    ]
    if row["overhead"] not in ("", "1"):
        details.append(["Overhead", f"× {row['overhead']}"])
    doc.add(W.para("Details", style="Heading1"), W.table(
        [[W.para(W.run(k, color=W.INK2), style="TableText"), v] for k, v in details],
        [2.6, 14.4]))
    return doc


def _provider(segs: list[dict]) -> str:
    names = {"uk": "Carbon Intensity API", "energy-charts": "Energy-Charts",
             "electricitymaps": "Electricity Maps"}
    return " / ".join(sorted({names.get(s["provider"], s["provider"])
                              for s in segs if s.get("provider")}))


def project_report(project: str, runs: list[Run]) -> wordfile.Doc:
    """One project over time: totals, energy and emissions by month, and its runs."""
    W = wordfile
    rows = [r.row() for r in runs]
    first, last = rows[0]["start"], rows[-1]["end"]
    doc = W.Doc(f"Carbon report: {project}")
    _head(doc, project, f"{len(rows)} run{'s' if len(rows) != 1 else ''} · "
                        f"{_when(first, year=True, time=False)} – "
                        f"{_when(last, year=True, time=False)}")
    doc.add(_stats(rows, _renewable(runs)))
    unmeasured = sum(1 for r in rows if r["kwh"] is None)
    if unmeasured:
        doc.add(W.para(f"{unmeasured} run{'s' if unmeasured > 1 else ''} not measured "
                       f"(hosted model or no sensor): records counted, energy not.",
                       style="Note"))

    energy: dict[str, list] = defaultdict(list)
    emissions: dict[str, float] = defaultdict(float)
    for r in runs:
        for t, wh, ge, iv, _ in r.intervals():
            m = f"{t.astimezone():%Y-%m}"
            energy[m].append((wh, iv))
            if ge is not None:
                emissions[m] += ge
    months = sorted(energy)
    if months:
        by_month = [_by_source(energy[m]) for m in months]
        unit, scale = _energy_unit(max(sum(p.values()) for p in by_month))
        cats = [_month_label(m) for m in months]
        cells = [W.para("Energy", style="Heading2")
                 + doc.chart(_source_chart(cats, by_month, unit, scale), 8.3, 5.4)]
        if emissions:
            top = W.nice_max(max(emissions.values()))
            cells.append(W.para("Emissions", style="Heading2") + doc.chart({
                "type": "col", "gap": 30 if len(cats) > 3 else 300, "ymax": top,
                "ystep": top / 2, "yfmt": '0.##" g"', "categories": cats,
                "legend": True,
                "series": [{"name": "g CO₂e", "color": "6B6A65",
                            "values": [round(emissions.get(m, 0), 2) for m in months]}],
            }, 8.3, 5.4))
        doc.add(W.para("By month", style="Heading1"),
                W.table([cells], [8.5] * len(cells), lines=False))

    per: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["kwh"] is not None and r["records"]:
            per[model_name(r["model"])][0] += r["kwh"] * 1000
            per[model_name(r["model"])][1] += r["records"]
    if len(per) > 1:
        items = sorted(((k, wh / n) for k, (wh, n) in per.items()), key=lambda kv: -kv[1])
        doc.add(W.para("Energy per record, by model", style="Heading1"), doc.chart({
            "type": "bar", "gap": 60, "labels": '0.00" Wh"',
            "categories": [k for k, _ in items],
            "series": [{"name": "Wh per record", "color": "2A78D6",
                        "values": [round(v, 3) for _, v in items]}],
        }, 17, 1.2 + 0.8 * len(items)))

    paused = any(row["hours_paused"] for row in rows)
    head = ["Run", "Model", "Start", "Records", "kWh", "Wh/record", "g CO₂e", "Renewable"]
    widths = [2.6, 5.0, 1.5, 1.6, 1.2, 1.8, 1.3, 2.0]
    if paused:
        head.append("Paused h")
        widths = [2.4, 4.3, 1.4, 1.5, 1.1, 1.8, 1.3, 1.7, 1.5]
    body = [[
        r.title, model_name(row["model"]), _when(row["start"], time=False),
        f"{row['records']:,}",
        _num(row["kwh"], digits=3) if row["kwh"] is not None else "not measured",
        _num(row["wh_per_record"]), _num(row["gco2e"]),
        f"{row['renewable_share'] * 100:.0f}%" if row["renewable_share"] is not None else "—",
        *([f"{row['hours_paused']:g}"] if paused else []),
    ] for r, row in zip(runs, rows)]
    doc.add(W.para("Runs", style="Heading1"), W.table(
        [head, *body], widths, header=True,
        align=["left", "left", "left"] + ["right"] * (len(head) - 3)))
    return doc


def _when(ts: str, year: bool = False, time: bool = True) -> str:
    t = parse_ts(ts)
    if not t:
        return ""
    fmt = "%d %b" + (" %Y" if year else "") + (" %H:%M" if time else "")
    return t.astimezone().strftime(fmt)
