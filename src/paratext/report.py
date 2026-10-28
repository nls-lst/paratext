"""`paratext carbon`'s report: one CSV row per run, and an HTML page of charts.

Both are rebuilt in full from the sidecars in `output/carbon/runs/` every time.
The page is a single file with inline SVG and no network requests, so it opens
offline and prints straight into a sustainability return.
"""

from __future__ import annotations

import csv
import html
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import tracking
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
          ) -> tuple[Path, Path, int]:
    """Write carbon.csv and carbon.html. Returns (csv, html, number of runs).

    `forecast` is the grid's Readings for the next hours, drawn when given."""
    out = out_dir or REPORT_DIR
    runs = collect(runs_dir)
    csv_path, html_path = out / "carbon.csv", out / "carbon.html"
    write_csv(runs, csv_path)
    html_path.write_text(render_html(runs, forecast, min_renewable))
    return csv_path, html_path, len(runs)



# ── formatting ───────────────────────────────────────────────────────────────
def _e(s) -> str:
    return html.escape(str(s))


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


def _tick(v: float, unit: str) -> str:
    """Axis labels: as few digits as the value needs (0, 0.5, 25, 1.5K)."""
    if abs(v) >= 1e4:
        return _num(v, unit)
    return f"{v:,.2f}".rstrip("0").rstrip(".") + unit


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def _colors(projects: list[str]) -> dict[str, int]:
    return {p: min(i, len(SLOTS) - 1) for i, p in enumerate(sorted(set(projects)))}


def _pct(v: float) -> str:
    return "<1%" if 0 < v < 1 else f"{v:.0f}%"


def _hm(t: datetime) -> str:
    return f"{t.astimezone():%H:%M}"


def _day(t: datetime) -> str:
    return f"{t.astimezone():%a}"


def _avg(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ── electricity mix ──────────────────────────────────────────────────────────
# Stacked bottom up. Colours match the ai.nls.uk status widget. The last two
# stand in when a provider gives a renewable share but no mix.
FUELS = [
    ("wind", "Wind"), ("solar", "Solar"), ("hydro", "Hydro"), ("imports", "Imports & other"),
    ("nuclear", "Nuclear"), ("biomass", "Biomass"), ("gas", "Gas"), ("coal", "Coal"),
    ("renewable", "Renewable"), ("rest", "Other sources"),
]
LABELS = dict(FUELS)
FUEL_COLORS = {
    "wind": ("#2a78d6", "#3987e5"), "solar": ("#eda100", "#c98500"),
    "hydro": ("#1baf7a", "#199e70"), "imports": ("#e87ba4", "#d55181"),
    "nuclear": ("#6250d6", "#9085e9"), "biomass": ("#008300", "#3aa63a"),
    "gas": ("#eb6834", "#d95926"), "coal": ("#6b6a65", "#8f8e88"),
    "renewable": ("#1baf7a", "#199e70"), "rest": ("#c3c2b7", "#4a4945"),
}


def _shares(r) -> dict[str, float]:
    """Percent by fuel from a Reading."""
    if r.mix:
        m = dict(r.mix)
        m["imports"] = m.get("imports", 0) + m.pop("other", 0)
        return m
    ren = (r.renewable_fraction or 0) * 100
    return {"renewable": ren, "rest": 100 - ren}


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
                        "_r": [0.0, 0.0], "_g": [0.0, 0.0]})
        b = out[-1]
        b["wh"] += wh
        if iv.get("renewable_fraction") is not None:
            b["_r"][0] += wh * iv["renewable_fraction"] * 100
            b["_r"][1] += wh
        if iv.get("gco2_per_kwh") is not None:
            b["_g"][0] += wh * iv["gco2_per_kwh"]
            b["_g"][1] += wh
    for b in out:
        rw, rn = b.pop("_r")
        gw, gn = b.pop("_g")
        b["r"] = rw / rn if rn else None
        b["g"] = gw / gn if gn else None
        b["m"] = {"renewable": b["r"], "rest": 100 - b["r"]} if b["r"] is not None else {}
    return out


def _block_tip(b: dict) -> str:
    facts = [
        f"{b['r']:.0f}% renewable" if b.get("r") is not None else None,
        f"{b['g']:.0f} g CO₂/kWh" if b.get("g") is not None else None,
        f"{_num(b['wh'], ' Wh')} used" if b.get("wh") is not None else None,
    ]
    tip = (f"<strong>{_day(b['t'])} {_hm(b['t'])}–{_hm(b['end'])}</strong><br>"
           + " · ".join(f for f in facts if f))
    if set(b["m"]) - {"renewable", "rest"}:
        tip += '<div class="tip-mix">' + "".join(
            f'<span><i class="k f-{k}"></i>{_e(LABELS[k])} <b>{_pct(v)}</b></span>'
            for k, v in sorted(b["m"].items(), key=lambda kv: -kv[1])
            if v >= 0.5 and k in LABELS) + "</div>"
    return tip


# ── charts ───────────────────────────────────────────────────────────────────
def mix_columns(blocks: list[dict], threshold: float, label: str, w: int = 640) -> str:
    """A 100% column per block, stacked by fuel, with the renewable threshold dotted."""
    if not blocks:
        return '<p class="empty">No grid readings.</p>'
    h, left, right, top, bottom = 170, 2, 74, 6, 22
    n = len(blocks)
    step = (w - left - right) / n
    bw = step * 0.78

    def y(v: float) -> float:
        return top + (h - top - bottom) * (1 - v / 100)

    cls = "chart wide" if w > 700 else "chart"
    out = [f'<svg class="{cls}" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(label)}">']
    last = -9
    for i, b in enumerate(blocks):
        x = left + step * i + (step - bw) / 2
        marks, acc = [], 0.0
        for k, _ in FUELS:
            v = b["m"].get(k) or 0
            if v < 0.4:
                acc += v
                continue
            y1, y0 = y(acc + v), y(acc)
            marks.append(f'<rect class="f-{k}" x="{x:.1f}" width="{bw:.1f}" y="{y1 + 0.5:.1f}" '
                         f'height="{max(y0 - y1 - 1, 0.5):.1f}" rx="2"/>')
            acc += v
        out.append(f'<g class="col" data-tip="{_e(_block_tip(b))}">{"".join(marks)}'
                   f'<rect class="hit" x="{left + step * i:.1f}" y="0" width="{step:.1f}" '
                   f'height="{h - bottom}"/></g>')
        t = b["t"].astimezone()
        hours = (b["end"] - b["t"]).total_seconds() / 3600
        day = i > 0 and t.date() != blocks[i - 1]["t"].astimezone().date()
        noon = t.hour <= 12 < t.hour + hours
        if n <= 8 or ((i == 0 or day or noon) and i - last > 1):
            tx, anchor = (x, "start") if i == 0 else (x + bw / 2, "middle")
            out.append(f'<text class="tick{" day" if day else ""}" x="{tx:.1f}" y="{h - 5}" '
                       f'text-anchor="{anchor}">{_day(b["t"]) if day else _hm(b["t"])}</text>')
            last = i
    ty = y(threshold)
    out.append(f'<line class="thr" x1="{left}" x2="{w - right}" y1="{ty:.1f}" y2="{ty:.1f}"/>'
               f'<text class="thr-l" x="{w - right + 7}" y="{ty - 2:.1f}">{threshold:.0f}%</text>'
               f'<text class="thr-l thr-s" x="{w - right + 7}" y="{ty + 11:.1f}">renewable</text>')
    out.append("</svg>")
    return "".join(out)


def donut(r) -> str:
    """The grid now: a ring of the mix with the renewable share in the middle, and a list."""
    m = _shares(r)
    parts = [(k, m[k]) for k, _ in FUELS if m.get(k, 0) >= 0.5]
    c = 2 * math.pi * 52
    total = sum(v for _, v in parts) or 100
    arcs, off = [], 0.0
    for k, v in parts:
        ln = v / total * c
        dash = max(ln - (1.5 if len(parts) > 1 else 0), 0.5)
        arcs.append(f'<circle class="arc f-{k}" r="52" cx="70" cy="70" '
                    f'stroke-dasharray="{dash:.2f} {c:.2f}" stroke-dashoffset="{-off:.2f}"/>')
        off += ln
    ren = (r.renewable_fraction or 0) * 100
    items = "".join(f'<li><i class="k f-{k}"></i>{_e(LABELS[k])}<b>{_pct(v)}</b></li>'
                    for k, v in parts)
    g = f'<div class="label">{r.carbon_gco2:.0f} g CO₂ per kWh</div>' \
        if r.carbon_gco2 is not None else ""
    return (f'<svg class="donut" viewBox="0 0 140 140" role="img" '
            f'aria-label="Electricity sources now"><g transform="rotate(-90 70 70)">'
            f'{"".join(arcs)}</g><text class="donut-v" x="70" y="79" '
            f'text-anchor="middle">{ren:.0f}%</text></svg>'
            f'<div><div class="label">Now · {ren:.0f}% renewable</div>'
            f'<ul class="mixlist">{items}</ul>{g}</div>')


def _frame(vmax: float, unit: str, w: int, h: int, left: int, right: int, top: int,
           bottom: int) -> list[str]:
    out = []
    for t in (0, vmax / 2, vmax):
        y = top + (h - top - bottom) * (1 - t / vmax)
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">'
                   f'{_e(_tick(t, unit))}</text>')
    return out


def stacked_columns(data: dict[str, dict[str, float]], colors: dict[str, int], unit: str,
                    label: str) -> str:
    """Columns per month, stacked by project. `data[month][project] = value`."""
    months = sorted(data)
    if not months:
        return '<p class="empty">No measured runs yet.</p>'
    w, h, left, right, top, bottom = 420, 170, 56, 4, 8, 22
    totals = [sum(data[m].values()) for m in months]
    vmax = _nice_max(max(totals))
    slot = (w - left - right) / len(months)
    bw = min(28.0, slot * 0.6)
    scale = (h - top - bottom) / vmax
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(label)}">',
           *_frame(vmax, unit, w, h, left, right, top, bottom)]
    order = sorted(colors, key=colors.get)
    every = math.ceil(len(months) / 6)
    for i, m in enumerate(months):
        x = left + slot * i + (slot - bw) / 2
        y = h - bottom
        present = [p for p in order if data[m].get(p)]
        marks = []
        for p in present:
            seg = data[m][p] * scale
            y -= seg
            marks.append(f'<rect class="s{colors[p] + 1}" x="{x:.1f}" y="{y + 1:.1f}" '
                         f'width="{bw:.1f}" height="{max(seg - 1, 0.5):.1f}" rx="2"/>')
        tip = f"<strong>{_e(_month_label(m))}</strong> · {_e(_num(totals[i], unit))}"
        if len(present) > 1:
            tip += "".join(f'<br><i class="k s{colors[p] + 1}"></i>{_e(p)} '
                           f'<b>{_e(_num(data[m][p], unit))}</b>' for p in present)
        out.append(f'<g class="col" data-tip="{_e(tip)}">{"".join(marks)}'
                   f'<rect class="hit" x="{left + slot * i:.1f}" y="0" width="{slot:.1f}" '
                   f'height="{h - bottom}"/></g>')
        if i % every == 0:
            out.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{h - 5}" '
                       f'text-anchor="middle">{_e(_month_label(m))}</text>')
    out.append("</svg>")
    return "".join(out)


def _month_label(m: str) -> str:
    try:
        return datetime.strptime(m, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return m


def hbars(items: list[tuple[str, float]], unit: str, label: str) -> str:
    if not items:
        return '<p class="empty">No measured runs with records yet.</p>'
    w, row_h, lab_w = 880, 30, 260
    h = row_h * len(items)
    vmax = _nice_max(max(v for _, v in items))
    plot_w = w - lab_w - 70
    out = [f'<svg class="wide" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(label)}">']
    for i, (name, v) in enumerate(items):
        y = i * row_h + (row_h - 16) / 2
        bw = max(v / vmax * plot_w, 1)
        out.append(f'<rect class="s1" x="{lab_w}" y="{y:.1f}" width="{bw:.1f}" height="16" '
                   f'rx="2"/>')
        out.append(f'<text class="label" x="{lab_w - 8}" y="{y + 12:.1f}" '
                   f'text-anchor="end">{_e(_clip(name, 34))}</text>')
        out.append(f'<text class="value" x="{lab_w + bw + 6:.1f}" y="{y + 12:.1f}">'
                   f'{_e(_num(v, unit))}</text>')
    out.append("</svg>")
    return "".join(out)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def timeline(points: list[tuple[datetime, float]], t0: datetime, t1: datetime, unit: str,
             label: str, pauses: list[tuple[datetime, datetime]]) -> str:
    """A line over the run, pauses shaded, a hover target per reading."""
    if len(points) < 2 or t1 <= t0:
        return '<p class="empty">Not enough data in this run yet.</p>'
    w, h, left, right, top, bottom = 880, 150, 50, 74, 8, 22
    vmax = _nice_max(max(v for _, v in points))
    span = (t1 - t0).total_seconds()
    plot_w, plot_h = w - left - right, h - top - bottom

    def xy(t: datetime, v: float) -> tuple[float, float]:
        return (left + plot_w * (t - t0).total_seconds() / span,
                top + plot_h * (1 - min(v, vmax) / vmax))

    out = [f'<svg class="chart wide" viewBox="0 0 {w} {h}" role="img" '
           f'aria-label="{_e(label)}">']
    for a, b in pauses:
        xa, xb = xy(max(a, t0), 0)[0], xy(min(b, t1), 0)[0]
        tip = f"<strong>Paused</strong> {_hm(a)}–{_hm(b)}: grid below the renewable threshold"
        out.append(f'<rect class="pause" data-tip="{_e(tip)}" x="{xa:.1f}" y="{top}" '
                   f'width="{max(xb - xa, 1):.1f}" height="{plot_h}"/>')
    out += _frame(vmax, unit, w, h, left, right, top, bottom)
    coords = [xy(t, v) for t, v in points]
    out.append('<path class="line" d="M' + "L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
               + '"/>')
    hit = max(plot_w / len(points), 2)
    for (t, v), (x, _) in zip(points, coords):
        tip = f"<strong>{_day(t)} {_hm(t)}</strong> · {_e(_num(v, unit))}"
        out.append(f'<rect class="hit" data-tip="{_e(tip)}" x="{x - hit / 2:.1f}" y="{top}" '
                   f'width="{hit:.1f}" height="{plot_h}"/>')
    for frac, anchor in ((0, "start"), (0.5, "middle"), (1, "end")):
        t = t0 + (t1 - t0) * frac
        out.append(f'<text class="tick" x="{xy(t, 0)[0]:.1f}" y="{h - 5}" '
                   f'text-anchor="{anchor}">{_day(t)} {_hm(t)}</text>')
    out.append("</svg>")
    return "".join(out)


# ── page ─────────────────────────────────────────────────────────────────────
def _stat(label: str, value: str, unit: str = "") -> str:
    u = f" <small>{_e(unit)}</small>" if unit else ""
    return (f'<div class="stat"><span class="label">{_e(label)}</span>'
            f'<span class="value">{_e(value)}{u}</span></div>')


def _legend(colors: dict[str, int]) -> str:
    if len(colors) < 2:
        return ""
    items = "".join(f'<span><i class="k s{i + 1}"></i>{_e(p)}</span>'
                    for p, i in sorted(colors.items(), key=lambda kv: kv[1]))
    return f'<div class="legend">{items}</div>'


def render_html(runs: list[Run], forecast: list | None = None,
                min_renewable: float = 70) -> str:
    rows = [r.row() for r in runs]
    measured = [r for r in runs if r.measured]
    colors = _colors([r.project for r in runs])

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
    unmeasured = sum(1 for r in rows if r["kwh"] is None)

    per_record: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["kwh"] is not None and r["records"]:
            k = f"{r['project']} · {r['model']}"
            per_record[k][0] += r["kwh"] * 1000
            per_record[k][1] += r["records"]
    eff = sorted(((k, wh / n) for k, (wh, n) in per_record.items()), key=lambda kv: -kv[1])

    stats = "".join([
        _stat("Energy", _num(kwh), "kWh"),
        _stat("Emissions", _num(sum(g)) if g else "—", "g CO₂e" if g else ""),
        _stat("Records", f"{records:,}"),
        _stat("Renewable", f"{ren_num / ren_den * 100:.0f}%" if ren_den else "—"),
    ])
    note = (f'<p class="note">{unmeasured} run{"s" if unmeasured > 1 else ""} not measured '
            f'(hosted model or no sensor): records counted, energy not.</p>'
            if unmeasured else "")
    month_emissions = (stacked_columns(emissions, colors, " g", "Emissions by month")
                       if emissions else '<p class="empty">Declare a grid in '
                       '<code>[carbon]</code> to count emissions.</p>')
    table_rows = "".join(
        "<tr>" + "".join(f"<td>{_e(v)}</td>" for v in (
            r["project"], r["model"], _when(r["start"]), f"{r['records']:,}",
            _num(r["kwh"], digits=3), _num(r["wh_per_record"]), _num(r["gco2e"]),
            f"{r['renewable_share'] * 100:.0f}%" if r["renewable_share"] is not None else "—",
            f"{r['hours_paused']:g}", r["meter"])) + "</tr>"
        for r in rows
    ) or '<tr><td colspan="10">No runs yet.</td></tr>'

    body = (
        f'<header class="top"><h1>Carbon report</h1>'
        f'<span class="src">{datetime.now().astimezone():%d %b %Y %H:%M}</span></header>'
        f'<div class="stats">{stats}</div>{note}'
        f'{_grid(forecast, min_renewable)}'
        f'{_latest(measured[-1]) if measured else ""}'
        f'<h2>By month</h2><div class="card">{_legend(colors)}<div class="pair">'
        f'<div><h3>Energy</h3>{stacked_columns(energy, colors, " kWh", "Energy by month")}'
        f'</div><div><h3>Emissions</h3>{month_emissions}</div></div></div>'
        f'<h2>Energy per record</h2>'
        f'<div class="card chartwrap">{hbars(eff, " Wh", "Energy per record")}</div>'
        f'<h2>Runs</h2><div class="card tablewrap"><table><thead><tr><th>Project</th>'
        f'<th>Model</th><th>Start</th><th>Records</th><th>kWh</th><th>Wh/record</th>'
        f'<th>g CO₂e</th><th>Renewable</th><th>Paused (h)</th><th>Meter</th></tr></thead>'
        f'<tbody>{table_rows}</tbody></table></div>'
        f'{_METHOD}'
    )
    data = json.dumps(rows).replace("</", "<\\/")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Carbon report</title><style>{_css()}</style></head><body><main>{body}'
        f'<script type="application/json" id="data">'
        f'{data}</script>'
        f'<div id="tip" role="status"></div><script>{_JS}</script></main></body></html>'
    )


def _when(ts: str) -> str:
    t = parse_ts(ts)
    return f"{t.astimezone():%d %b %Y %H:%M}" if t else ""


def _grid(series: list | None, min_renewable: float) -> str:
    """The grid now and over the forecast, as on the ai.nls.uk status widget."""
    blocks = _forecast_blocks(series or [])
    if len(blocks) < 2:
        return ""
    hours = round((blocks[-1]["end"] - blocks[0]["t"]).total_seconds() / 3600)
    chart = mix_columns(blocks, min_renewable, f"Electricity sources, next {hours} hours")
    return (f'<h2>Grid <span class="src">{_e(series[0].zone)} · next {hours} hours</span></h2>'
            f'<div class="card elec">{donut(series[0])}'
            f'<div class="chartwrap">{chart}</div></div>')


def _latest(run: Run) -> str:
    pts: list[tuple[datetime, float]] = []
    pauses: list[tuple[datetime, datetime]] = []
    for s in run.measured:
        k = s.get("overhead", 1.0)
        for ts, w in s.get("timeline", []):
            t = parse_ts(ts)
            if t:
                pts.append((t, w * k))
        for a, b in s.get("pauses", []):
            ta, tb = parse_ts(a), parse_ts(b)
            if ta and tb:
                pauses.append((ta, tb))
    row = run.row()
    name = Path(run.doc.get("output", "")).stem or run.project
    facts = " · ".join(_e(f) for f in (name, run.doc.get("model", ""),
                                      f"{row['records']:,} records") if f)
    if not pts:
        return f'<h2>Latest run <span class="src">{facts}</span></h2>' \
               '<div class="card"><p class="empty">No power readings yet.</p></div>'
    t0 = parse_ts(run.segments[0].get("start")) or pts[0][0]
    t1 = parse_ts(run.segments[-1].get("end")) or pts[-1][0]
    threshold = run.measured[0].get("min_renewable", 70)
    shaded = '<p class="note">Shaded: paused for a dirty grid.</p>' if pauses else ""
    return (f'<h2>Latest run <span class="src">{facts}</span></h2><div class="card">'
            f'<h3>Power</h3><div class="chartwrap">'
            f'{timeline(pts, t0, t1, " W", "Power draw", pauses)}</div>{shaded}'
            f'<h3>Grid while it ran</h3><div class="chartwrap">'
            f'{mix_columns(_run_blocks(run), threshold, "Grid renewables during the run", 880)}'
            f'</div></div>')


_METHOD = """<details class="card method"><summary>How it's measured</summary><dl>
<dt>Energy</dt><dd>Hardware power sensors, every 10 seconds (the meter column). Processor
only: set <code>overhead</code> to cover the rest of the machine.</dd>
<dt>Not measured</dt><dd>A hosted model, or no readable sensor. Never estimated.</dd>
<dt>Emissions</dt><dd>Location-based: energy in each grid interval × that interval's carbon
intensity.</dd>
<dt>Renewable</dt><dd>Wind, solar and hydro, weighted by the energy used.</dd>
</dl></details>"""


def _css() -> str:
    light = ";".join(
        [f"--s{i + 1}:{a}" for i, (a, _) in enumerate(SLOTS)]
        + [f"--f-{k}:{a}" for k, (a, _) in FUEL_COLORS.items()])
    dark = ";".join(
        [f"--s{i + 1}:{b}" for i, (_, b) in enumerate(SLOTS)]
        + [f"--f-{k}:{b}" for k, (_, b) in FUEL_COLORS.items()])
    dark_vars = (f"color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;"
                 f"--ink2:#c3c2b7;--muted:#8f8e88;--line:#2c2c2a;--ring:rgba(255,255,255,.12);"
                 f"{dark}")
    classes = "".join(
        f".f-{k}{{fill:var(--f-{k});background:var(--f-{k})}}.arc.f-{k}{{stroke:var(--f-{k})}}"
        for k in FUEL_COLORS) + "".join(
        f".s{i}{{fill:var(--s{i});background:var(--s{i})}}" for i in range(1, len(SLOTS) + 1))
    return (
        f":root{{color-scheme:light;--page:#f9f9f7;--surface:#fff;--ink:#0b0b0b;--ink2:#52514e;"
        f"--muted:#898781;--line:#e6e5df;--ring:rgba(11,11,11,.10);{light}}}"
        f"@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{dark_vars}}}}}"
        f":root[data-theme=dark]{{{dark_vars}}}{classes}{_CSS}"
    )


_CSS = """
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
main{max-width:920px;margin:0 auto;padding:28px 16px 56px}
.top,h2{display:flex;align-items:baseline;justify-content:space-between;gap:4px 16px;
flex-wrap:wrap}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:28px 0 8px}
h3{font-size:12px;font-weight:600;color:var(--ink2);margin:4px 0 6px}
h3:not(:first-child){margin-top:16px}
.src{font-size:12px;font-weight:400;color:var(--muted)}
.label,.note,.empty{font-size:12px;color:var(--ink2)}.note{margin:8px 0 0}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px 16px;margin-top:16px}
@media (max-width:520px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
.stat{display:grid}.value{font-size:22px;font-weight:700;line-height:1.3}
.value small{font-size:12px;font-weight:400;color:var(--ink2)}
.elec{display:grid;grid-template-columns:92px auto minmax(0,1fr);gap:18px;align-items:center}
@media (max-width:700px){.elec{grid-template-columns:92px 1fr}.elec .chartwrap{grid-column:1/-1}}
.donut{width:92px;height:92px}circle.arc{fill:none;stroke-width:22}
.donut-v{font-size:26px;font-weight:700;fill:var(--ink)}
.mixlist{list-style:none;margin:3px 0;padding:0;font-size:12px}
.mixlist li{display:flex;align-items:center;min-width:140px;line-height:1.55}
.mixlist b{margin-left:auto;padding-left:14px}
.k{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;flex:none}
.chartwrap{overflow-x:auto}.chartwrap svg{min-width:480px}.chartwrap svg.wide{min-width:640px}
svg{width:100%;height:auto;display:block}
.tick{fill:var(--muted);font-size:11.5px}.tick.day{font-weight:700}
.grid{stroke:var(--line)}.label{fill:var(--ink2)}
.value{fill:var(--ink)}svg .value{font-size:12px;font-weight:600}svg .label{font-size:12px}
.col{transition:opacity .12s}.col.dim{opacity:.35}.hit{fill:transparent}
rect.hit[data-tip]:hover{fill:var(--ink);opacity:.05}
.thr{stroke:var(--ink);opacity:.7;stroke-width:1.5;stroke-dasharray:2 4;stroke-linecap:round;
pointer-events:none}
.thr-l{fill:var(--ink2);font-size:11.5px;font-weight:700}.thr-s{font-weight:400}
.line{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round;
pointer-events:none}
.pause{fill:var(--muted);opacity:.14}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media (max-width:620px){.pair{grid-template-columns:1fr}}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12px;color:var(--ink2);margin-bottom:6px}
.legend span{display:flex;align-items:center}
#tip{display:none;position:absolute;pointer-events:none;z-index:2;white-space:nowrap;
background:color-mix(in srgb,var(--surface) 80%,transparent);-webkit-backdrop-filter:blur(3px);
backdrop-filter:blur(3px);border:1px solid var(--ring);border-radius:8px;padding:5px 9px;
font-size:11.5px;line-height:1.35;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.tip-mix{display:grid;grid-template-columns:auto auto;column-gap:14px;margin-top:3px}
.tip-mix span{display:flex;align-items:center}.tip-mix b{margin-left:4px}
.tablewrap{overflow-x:auto;padding:4px 8px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
tr:last-child td{border-bottom:0}th{color:var(--ink2);font-weight:600}
.method{margin-top:28px}summary{cursor:pointer;font-weight:600;font-size:13px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;font-size:12px;
margin:10px 0 0}dt{font-weight:600}dd{margin:0;color:var(--ink2)}code{font-size:12px}
@media print{body{background:#fff}.card{break-inside:avoid;box-shadow:none}}
"""

_JS = """(()=>{const tip=document.getElementById("tip");
document.querySelectorAll("svg.chart").forEach(svg=>{
const items=[...svg.querySelectorAll("[data-tip]")];
const hide=()=>{tip.style.display="none";items.forEach(o=>o.classList.remove("dim"))};
items.forEach(g=>{const show=()=>{
items.forEach(o=>o.classList.toggle("dim",o!==g&&o.classList.contains("col")));
tip.innerHTML=g.dataset.tip;tip.style.display="block";
const b=g.getBoundingClientRect(),s=svg.getBoundingClientRect(),w=tip.offsetWidth;
const x=b.right+8+w>innerWidth-8?Math.max(8,b.left-w-8):b.right+8;
tip.style.left=x+scrollX+"px";tip.style.top=s.top+scrollY+"px"};
g.addEventListener("pointerenter",show);g.addEventListener("pointerdown",show)});
svg.addEventListener("pointerleave",hide)})})();"""
