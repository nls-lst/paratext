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
        runs.append(Run(doc, doc.get("segments", [])))
    runs.sort(key=lambda r: r.segments[0].get("start", "") if r.segments else "")
    return runs


def write_csv(runs: list[Run], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in runs:
            w.writerow({k: ("" if v is None else v) for k, v in r.row().items()})


def build(runs_dir: Path | None = None, out_dir: Path | None = None, *,
          forecast: list | None = None, min_renewable: float = 70
          ) -> tuple[Path, Path, Path | None, int]:
    """Write carbon.csv, carbon.docx and carbon.pdf.

    Returns (csv, docx, pdf or None without LibreOffice, number of runs).
    `forecast` is the grid's Readings for the next hours, drawn when given."""
    out = out_dir or REPORT_DIR
    runs = collect(runs_dir)
    csv_path, docx_path = out / "carbon.csv", out / "carbon.docx"
    write_csv(runs, csv_path)
    render(runs, forecast, min_renewable).save(docx_path)
    return csv_path, docx_path, wordfile.to_pdf(docx_path), len(runs)


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


# ── grid blocks ──────────────────────────────────────────────────────────────
# Stacked bottom up. Colours match the status widget. The last two stand in
# when a provider gives a renewable share but no mix.
FUELS = [
    ("wind", "Wind", "2A78D6"), ("solar", "Solar", "EDA100"), ("hydro", "Hydro", "1BAF7A"),
    ("imports", "Imports & other", "E87BA4"), ("nuclear", "Nuclear", "6250D6"),
    ("biomass", "Biomass", "008300"), ("gas", "Gas", "EB6834"), ("coal", "Coal", "6B6A65"),
    ("renewable", "Renewable", "1BAF7A"), ("rest", "Other sources", "C3C2B7"),
]


def _shares(r) -> dict[str, float]:
    """Percent by fuel from a Reading, summing to 100."""
    if r.mix:
        m = dict(r.mix)
        m["imports"] = m.get("imports", 0) + m.pop("other", 0)
    else:
        ren = (r.renewable_fraction or 0) * 100
        m = {"renewable": ren, "rest": 100 - ren}
    total = sum(m.values()) or 1
    return {k: v * 100 / total for k, v in m.items()}


def _forecast_blocks(series: list) -> list[dict]:
    """Three-hour blocks of the forecast: mean mix, renewables and intensity."""
    rs = [r for r in series if parse_ts(r.ts)]
    if not rs:
        return []
    step = (parse_ts(rs[1].ts) - parse_ts(rs[0].ts)) if len(rs) > 1 else timedelta(minutes=30)
    per = max(1, round(timedelta(hours=3) / step))
    out = []
    for i in range(0, len(rs), per):
        sl = rs[i:i + per]
        ms = [_shares(r) for r in sl]
        keys = {k for m in ms for k in m}
        out.append({
            "t": parse_ts(sl[0].ts), "end": parse_ts(sl[-1].ts) + step,
            "m": {k: sum(m.get(k, 0) for m in ms) / len(ms) for k in keys},
            "r": _avg([r.renewable_fraction * 100 for r in sl
                       if r.renewable_fraction is not None]),
            "g": _avg([r.carbon_gco2 for r in sl]),
        })
    return out


def _run_blocks(run: Run) -> list[dict]:
    """A run's grid intervals in at most 24 blocks, weighted by the energy used."""
    ivs = sorted(((t, wh, iv) for t, wh, _, iv, _ in run.intervals()), key=lambda x: x[0])
    if not ivs:
        return []
    span_h = (ivs[-1][0] - ivs[0][0]).total_seconds() / 3600 + 0.5
    size = next((h for h in (0.5, 1, 3, 6, 12, 24) if span_h / h <= 24), 48)
    out: list[dict] = []
    for t, wh, iv in ivs:
        sec = t.timestamp()
        start = datetime.fromtimestamp(sec - sec % (size * 3600), timezone.utc)
        if not out or out[-1]["t"] != start:
            out.append({"t": start, "end": start + timedelta(hours=size), "wh": 0.0,
                        "_r": [0.0, 0.0]})
        b = out[-1]
        b["wh"] += wh
        if iv.get("renewable_fraction") is not None:
            b["_r"][0] += wh * iv["renewable_fraction"] * 100
            b["_r"][1] += wh
    for b in out:
        rw, rn = b.pop("_r")
        b["r"] = rw / rn if rn else None
        b["m"] = {"renewable": b["r"], "rest": 100 - b["r"]} if b["r"] is not None else {}
    return out


def _mix_chart(blocks: list[dict], threshold: float) -> dict:
    keys = {k for b in blocks for k, v in b["m"].items() if v and v >= 0.4}
    return {
        "type": "col", "stacked": True, "gap": 30, "ymax": 100, "ystep": 50,
        "yfmt": '0"%"', "legend": True, "skip": math.ceil(len(blocks) / 6),
        "categories": [f"{_day(b['t'])} {_hm(b['t'])}" for b in blocks],
        "series": [{"name": label, "color": color,
                    "values": [round(b["m"].get(k) or 0, 1) for b in blocks]}
                   for k, label, color in FUELS if k in keys],
        "threshold": {"name": f"{threshold:.0f}% renewable", "value": threshold},
    }


# ── document ─────────────────────────────────────────────────────────────────
def _stat(label: str, value: str, unit: str = "") -> str:
    return (wordfile.para(wordfile.run(label, size=8.5, color=wordfile.INK2), after=0)
            + wordfile.para(wordfile.run(value, bold=True, size=17),
                            wordfile.run(f" {unit}" if unit else "", size=8.5,
                                         color=wordfile.INK2), after=0))


def _heading(text: str, aside: str = "") -> str:
    h = wordfile.para(text, style="Heading1")
    return h + (wordfile.para(aside, style="Note", keep_next=True) if aside else "")


def render(runs: list[Run], forecast: list | None = None,
           min_renewable: float = 70) -> wordfile.Doc:
    W = wordfile
    doc = W.Doc("Carbon report")
    rows = [r.row() for r in runs]
    measured = [r for r in runs if r.measured]

    kwh = sum(r["kwh"] for r in rows if r["kwh"] is not None)
    g = [r["gco2e"] for r in rows if r["gco2e"] is not None]
    records = sum(r["records"] for r in rows)
    ren_num = ren_den = 0.0
    energy: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    emissions: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in measured:
        for t, wh, ge, iv, _ in r.intervals():
            m = t.strftime("%Y-%m")
            energy[m][r.project] += wh / 1000
            if ge is not None:
                emissions[m][r.project] += ge
            if iv.get("renewable_fraction") is not None and wh > 0:
                ren_num += wh * iv["renewable_fraction"]
                ren_den += wh

    doc.add(W.para("Carbon report", style="Title"),
            W.para(f"{datetime.now().astimezone():%d %B %Y %H:%M}", style="Note", after=240))
    doc.add(W.table([[
        _stat("Energy", _num(kwh), "kWh"),
        _stat("Emissions", _num(sum(g)) if g else "—", "g CO₂e" if g else ""),
        _stat("Records", f"{records:,}"),
        _stat("Renewable", f"{ren_num / ren_den * 100:.0f}%" if ren_den else "—"),
    ]], [4.25] * 4, lines=False))
    unmeasured = sum(1 for r in rows if r["kwh"] is None)
    if unmeasured:
        doc.add(W.para(f"{unmeasured} run{'s' if unmeasured > 1 else ''} not measured "
                       f"(hosted model or no sensor): records counted, energy not.",
                       style="Note"))

    _grid(doc, forecast, min_renewable)
    if measured:
        _latest(doc, measured[-1])
    _months(doc, energy, emissions, _colors([r.project for r in runs]))
    _per_record(doc, rows)
    _runs_table(doc, rows)
    return doc


def _grid(doc: wordfile.Doc, series: list | None, min_renewable: float) -> None:
    W = wordfile
    blocks = _forecast_blocks(series or [])
    if len(blocks) < 2:
        return
    hours = round((blocks[-1]["end"] - blocks[0]["t"]).total_seconds() / 3600)
    now = series[0]
    m = _shares(now)
    parts = [(k, label, color, m[k]) for k, label, color in FUELS if m.get(k, 0) >= 0.5]
    ren = (now.renewable_fraction or 0) * 100
    ring = doc.chart({"type": "doughnut", "categories": [p[1] for p in parts],
                      "series": [{"name": "Now", "values": [round(p[3], 1) for p in parts],
                                  "colors": [p[2] for p in parts]}]}, 3.2, 3.2)
    lines = [W.para(W.run(f"Now · {ren:.0f}% renewable", bold=True), style="TableText")]
    lines += [W.para(W.run("■ ", color=c), f"{label}  ", W.run(_pct(v), bold=True),
                     style="TableText") for _, label, c, v in parts]
    if now.carbon_gco2 is not None:
        lines.append(W.para(W.run(f"{now.carbon_gco2:.0f} g CO₂ per kWh", color=W.INK2),
                            style="TableText"))
    doc.add(_heading("Grid", f"{now.zone} · next {hours} hours"),
            W.table([[ring, "".join(lines)]], [3.8, 13.2], lines=False),
            doc.chart(_mix_chart(blocks, min_renewable), 17, 6.2))


def _power_points(run: Run, n: int = 240) -> list[tuple[datetime, float]]:
    pts = []
    for s in run.measured:
        k = s.get("overhead", 1.0)
        for ts, w in s.get("timeline", []):
            if t := parse_ts(ts):
                pts.append((t, w * k))
    if len(pts) <= n:
        return pts
    size = math.ceil(len(pts) / n)
    return [(pts[i][0], sum(w for _, w in pts[i:i + size]) / len(pts[i:i + size]))
            for i in range(0, len(pts), size)]


def _latest(doc: wordfile.Doc, run: Run) -> None:
    W = wordfile
    row = run.row()
    name = Path(run.doc.get("output", "")).stem or run.project
    aside = " · ".join(p for p in (name, model_name(run.doc.get("model", "")),
                                   f"{row['records']:,} records") if p)
    paused = row["hours_paused"]
    if paused:
        aside += f" · paused {paused:g} h for a dirty grid"
    doc.add(_heading("Latest run", aside))
    pts = _power_points(run)
    if len(pts) > 1:
        vmax = W.nice_max(max(w for _, w in pts))
        doc.add(W.para("Power", style="Heading2"), doc.chart({
            "type": "line", "ymax": vmax, "ystep": vmax / 2, "yfmt": '0" W"',
            "skip": math.ceil(len(pts) / 4),
            "categories": [f"{_day(t)} {_hm(t)}" for t, _ in pts],
            "series": [{"name": "Power (W)", "color": "2A78D6",
                        "values": [round(w, 1) for _, w in pts]}],
        }, 17, 4.6))
    blocks = _run_blocks(run)
    if blocks:
        threshold = run.measured[0].get("min_renewable", 70)
        doc.add(W.para("Grid while it ran", style="Heading2"),
                doc.chart(_mix_chart(blocks, threshold), 17, 5.2))


def _months(doc: wordfile.Doc, energy: dict, emissions: dict, colors: dict) -> None:
    W = wordfile
    months = sorted(energy)
    if not months:
        return
    order = sorted(colors, key=colors.get)

    def spec(data: dict, unit: str) -> dict:
        top = W.nice_max(max(sum(data[m].values()) for m in months))
        return {
            "type": "col", "stacked": True, "gap": 300 if len(months) < 4 else 80,
            "ymax": top, "ystep": top / 2,
            "yfmt": f'0.##" {unit}"', "legend": len(order) > 1,
            "categories": [_month_label(m) for m in months],
            "series": [{"name": p, "color": SLOTS[colors[p]][0].lstrip("#").upper(),
                        "values": [round(data[m].get(p, 0), 3) for m in months]}
                       for p in order],
        }

    cells = [W.para("Energy", style="Heading2") + doc.chart(spec(energy, "kWh"), 8.3, 5)]
    if emissions:
        cells.append(W.para("Emissions", style="Heading2")
                     + doc.chart(spec(emissions, "g"), 8.3, 5))
    doc.add(_heading("By month"), W.table([cells], [8.5] * len(cells), lines=False))


def _per_record(doc: wordfile.Doc, rows: list[dict]) -> None:
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["kwh"] is not None and r["records"]:
            k = f"{r['project']} · {model_name(r['model'])}"
            acc[k][0] += r["kwh"] * 1000
            acc[k][1] += r["records"]
    if not acc:
        return
    items = sorted(((k, wh / n) for k, (wh, n) in acc.items()), key=lambda kv: -kv[1])
    doc.add(_heading("Energy per record"), doc.chart({
        "type": "bar", "gap": 60, "labels": '0.00" Wh"',
        "categories": [k for k, _ in items],
        "series": [{"name": "Wh per record", "color": "2A78D6",
                    "values": [round(v, 3) for _, v in items]}],
    }, 17, 1.2 + 0.8 * len(items)))


def _runs_table(doc: wordfile.Doc, rows: list[dict]) -> None:
    W = wordfile
    head = ["Run", "Model", "Start", "Records", "kWh", "Wh/record", "g CO₂e", "Renewable",
            "Paused (h)"]
    body = [[
        Path(r["output"]).stem or r["project"], model_name(r["model"]), _when(r["start"]),
        f"{r['records']:,}", _num(r["kwh"], digits=3) if r["kwh"] is not None
        else "not measured", _num(r["wh_per_record"]), _num(r["gco2e"]),
        f"{r['renewable_share'] * 100:.0f}%" if r["renewable_share"] is not None else "—",
        f"{r['hours_paused']:g}",
    ] for r in rows]
    if not body:
        doc.add(_heading("Runs"), W.para("No runs yet.", style="Note"))
        return
    doc.add(_heading("Runs"), W.table(
        [head, *body], [2.5, 3.4, 2.1, 1.6, 1.2, 1.6, 1.2, 1.8, 1.6], header=True,
        align=["left", "left", "left"] + ["right"] * 6))


def _when(ts: str) -> str:
    t = parse_ts(ts)
    return f"{t.astimezone():%d %b %H:%M}" if t else ""
