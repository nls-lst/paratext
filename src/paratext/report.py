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
from datetime import datetime, timezone
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


def _ticks(vmax: float, n: int = 4) -> list[float]:
    return [vmax * i / n for i in range(n + 1)]


def _colors(projects: list[str]) -> dict[str, int]:
    return {p: min(i, len(SLOTS) - 1) for i, p in enumerate(sorted(set(projects)))}


# ── charts ───────────────────────────────────────────────────────────────────
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 720, 240, 56, 16, 12, 28


def _frame(vmax: float, unit: str) -> list[str]:
    out = []
    for t in _ticks(vmax):
        y = PAD_T + (H - PAD_T - PAD_B) * (1 - t / vmax)
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end">'
                   f'{_e(_tick(t, unit))}</text>')
    base = H - PAD_B
    out.append(f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{base}" y2="{base}"/>')
    return out


def _bar_path(x: float, y: float, w: float, h: float, round_top: bool) -> str:
    r = min(4.0, w / 2, h) if round_top else 0
    if r <= 0:
        return f"M{x:.1f},{y + h:.1f}V{y:.1f}H{x + w:.1f}V{y + h:.1f}Z"
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def stacked_columns(data: dict[str, dict[str, float]], colors: dict[str, int], unit: str,
                    label: str) -> str:
    """Columns per month, stacked by project. `data[month][project] = value`."""
    months = sorted(data)
    if not months:
        return '<p class="empty">No measured runs yet.</p>'
    totals = [sum(data[m].values()) for m in months]
    vmax = _nice_max(max(totals))
    plot_w = W - PAD_L - PAD_R
    slot = plot_w / len(months)
    bw = min(24.0, slot * 0.6)
    scale = (H - PAD_T - PAD_B) / vmax
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(label)}">', *_frame(vmax, unit)]
    order = sorted(colors, key=colors.get)
    for i, m in enumerate(months):
        x = PAD_L + slot * i + (slot - bw) / 2
        y = H - PAD_B
        present = [p for p in order if data[m].get(p)]
        for j, p in enumerate(present):
            v = data[m][p]
            h = v * scale
            gap = 2 if j else 0
            seg_h = max(h - gap, 0.5)
            y -= h
            d = _bar_path(x, y, bw, seg_h, j == len(present) - 1)
            out.append(
                f'<path class="s{colors[p] + 1}" d="{d}">'
                f'<title>{_e(m)} · {_e(p)}: {_e(_num(v, unit))}</title></path>'
            )
        if len(months) <= 12 or i % math.ceil(len(months) / 12) == 0:
            out.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{H - 8}" '
                       f'text-anchor="middle">{_e(_month_label(m))}</text>')
        top = H - PAD_B - totals[i] * scale
        if i == len(months) - 1:
            out.append(f'<text class="value" x="{x + bw / 2:.1f}" y="{top - 6:.1f}" '
                       f'text-anchor="middle">{_e(_num(totals[i], unit))}</text>')
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
    row_h, lab_w = 34, 230
    h = row_h * len(items) + 8
    vmax = _nice_max(max(v for _, v in items))
    plot_w = W - lab_w - 70
    out = [f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{_e(label)}">']
    out.append(f'<line class="axis" x1="{lab_w}" x2="{lab_w}" y1="0" y2="{h - 8}"/>')
    for i, (name, v) in enumerate(items):
        y = i * row_h + (row_h - 20) / 2
        w = max(v / vmax * plot_w, 1)
        r = min(4, w)
        d = (f"M{lab_w},{y:.1f}H{lab_w + w - r:.1f}Q{lab_w + w:.1f},{y:.1f} "
             f"{lab_w + w:.1f},{y + r:.1f}V{y + 20 - r:.1f}Q{lab_w + w:.1f},{y + 20:.1f} "
             f"{lab_w + w - r:.1f},{y + 20:.1f}H{lab_w}Z")
        out.append(f'<path class="s1" d="{d}">'
                   f'<title>{_e(name)}: {_e(_num(v, unit))}</title></path>')
        out.append(f'<text class="label" x="{lab_w - 8}" y="{y + 14:.1f}" '
                   f'text-anchor="end">{_e(_clip(name, 34))}</text>')
        out.append(f'<text class="value" x="{lab_w + w + 6:.1f}" y="{y + 14:.1f}">'
                   f'{_e(_num(v, unit))}</text>')
    out.append("</svg>")
    return "".join(out)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def timeline(points: list[tuple[datetime, float]], t0: datetime, t1: datetime, unit: str,
             label: str, pauses: list[tuple[datetime, datetime]], vmax: float | None = None,
             area: bool = False, step: bool = False, threshold: float | None = None,
             shade_title: str = "Paused for a dirty grid") -> str:
    if len(points) < 2 or t1 <= t0:
        return '<p class="empty">Not enough data in this run yet.</p>'
    vmax = vmax or _nice_max(max(v for _, v in points))
    span = (t1 - t0).total_seconds()
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    def xy(t: datetime, v: float) -> tuple[float, float]:
        x = PAD_L + plot_w * (t - t0).total_seconds() / span
        y = PAD_T + plot_h * (1 - min(v, vmax) / vmax)
        return x, y

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(label)}">']
    for a, b in pauses:
        xa, _ = xy(max(a, t0), 0)
        xb, _ = xy(min(b, t1), 0)
        out.append(f'<rect class="pause" x="{xa:.1f}" y="{PAD_T}" width="{max(xb - xa, 1):.1f}" '
                   f'height="{plot_h}"><title>{_e(shade_title)}</title></rect>')
    out += _frame(vmax, unit)
    if threshold is not None:
        _, ty = xy(t0, threshold)
        out.append(f'<line class="threshold" x1="{PAD_L}" x2="{W - PAD_R}" y1="{ty:.1f}" '
                   f'y2="{ty:.1f}"/><text class="tick" x="{W - PAD_R - 4}" y="{ty - 5:.1f}" '
                   f'text-anchor="end">{_e(_tick(threshold, unit))} threshold</text>')
    coords = []
    for i, (t, v) in enumerate(points):
        x, y = xy(t, v)
        if step and coords:
            coords.append((x, coords[-1][1]))
        coords.append((x, y))
    if step:
        coords.append((xy(t1, 0)[0], coords[-1][1]))
    line = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    if area:
        base = H - PAD_B
        out.append(f'<path class="wash" d="{line}L{coords[-1][0]:.1f},{base}'
                   f'L{coords[0][0]:.1f},{base}Z"/>')
    out.append(f'<path class="line" d="{line}"/>')
    # Hover targets: one invisible column per point, wider than the mark.
    hit = max(plot_w / len(points), 2)
    for t, v in points:
        x, _ = xy(t, v)
        out.append(f'<rect class="hit" x="{x - hit / 2:.1f}" y="{PAD_T}" width="{hit:.1f}" '
                   f'height="{plot_h}"><title>{t:%d %b %H:%M} UTC · {_e(_num(v, unit))}</title>'
                   f'</rect>')
    ex, ey = coords[-1]
    out.append(f'<circle class="dot" cx="{ex:.1f}" cy="{ey:.1f}" r="4"/>')
    for frac in (0, 0.5, 1):
        t = t0 + (t1 - t0) * frac
        anchor = {0: "start", 0.5: "middle", 1: "end"}[frac]
        x, _ = xy(t, 0)
        out.append(f'<text class="tick" x="{x:.1f}" y="{H - 8}" text-anchor="{anchor}">'
                   f'{t:%d %b %H:%M}</text>')
    out.append("</svg>")
    return "".join(out)


# ── page ─────────────────────────────────────────────────────────────────────
def _tile(label: str, value: str, note: str = "") -> str:
    n = f'<div class="note">{_e(note)}</div>' if note else ""
    return f'<div class="tile"><div class="tlabel">{_e(label)}</div>' \
           f'<div class="tvalue">{_e(value)}</div>{n}</div>'


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
    clean_num = clean_den = 0.0
    for r in runs:
        for _, wh, _, iv, s in r.intervals():
            if iv.get("renewable_fraction") is None or wh <= 0:
                continue
            clean_den += wh
            if iv["renewable_fraction"] * 100 >= s.get("min_renewable", 70):
                clean_num += wh
    unmeasured = sum(1 for r in rows if r["kwh"] is None)

    energy: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    emissions: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in measured:
        for t, wh, ge, _, _ in r.intervals():
            m = t.strftime("%Y-%m")
            energy[m][r.project] += wh / 1000
            if ge is not None:
                emissions[m][r.project] += ge

    per_record: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["kwh"] is not None and r["records"]:
            k = f"{r['project']} · {r['model']}"
            per_record[k][0] += r["kwh"] * 1000
            per_record[k][1] += r["records"]
    eff = sorted(((k, wh / n) for k, (wh, n) in per_record.items()), key=lambda kv: -kv[1])

    latest = measured[-1] if measured else None
    latest_html = '<p class="empty">No measured runs yet.</p>'
    if latest:
        latest_html = _latest(latest)

    tiles = "".join([
        _tile("Energy", _num(kwh, " kWh"), f"{len(measured)} measured run(s)"),
        _tile("Emissions", _num(sum(g), " gCO₂e") if g else "—",
              "location-based" if g else "no grid declared"),
        _tile("Records", f"{records:,}", f"{len(rows)} run(s)"),
        _tile("On a clean grid", f"{clean_num / clean_den * 100:.0f}%" if clean_den else "—",
              "share of measured energy"),
    ])
    note = (f'<p class="muted">{unmeasured} run(s) not measured (hosted endpoint or no '
            f'sensor): their records are counted, their energy is not.</p>'
            if unmeasured else "")

    table_rows = "".join(
        "<tr>" + "".join(f"<td>{_e(v)}</td>" for v in (
            r["project"], r["model"], r["start"][:16].replace("T", " "), f"{r['records']:,}",
            _num(r["kwh"], digits=3), _num(r["wh_per_record"]), _num(r["gco2e"]),
            f"{r['renewable_share'] * 100:.0f}%" if r["renewable_share"] is not None else "—",
            f"{r['hours_paused']:g}", r["meter"])) + "</tr>"
        for r in rows
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return _PAGE.format(
        generated=generated,
        tiles=tiles,
        note=note,
        legend=_legend(colors),
        energy=stacked_columns(energy, colors, " kWh", "Energy by month"),
        emissions=(stacked_columns(emissions, colors, " g", "Emissions by month")
                   if emissions else '<p class="empty">No emissions: declare a grid in '
                   '<code>[carbon]</code> to compute them.</p>'),
        efficiency=hbars(eff, " Wh", "Energy per record"),
        latest=latest_html,
        forecast=_forecast(forecast, min_renewable),
        table_rows=table_rows or '<tr><td colspan="10">No runs yet.</td></tr>',
        css=_CSS,
        data=json.dumps(rows).replace("</", "<\\/"),
    )


def _forecast(series: list | None, min_renewable: float) -> str:
    """The grid's next hours: renewables against the threshold, dirty spells shaded."""
    pts = [(t, r.renewable_fraction * 100) for r in series or []
           if r.renewable_fraction is not None and (t := parse_ts(r.ts))]
    if len(pts) < 2:
        return ""
    step = pts[1][0] - pts[0][0]
    t0, t1 = pts[0][0], pts[-1][0] + step
    dirty: list[tuple[datetime, datetime]] = []
    for t, v in pts:
        if v >= min_renewable:
            continue
        if dirty and dirty[-1][1] == t:
            dirty[-1] = (dirty[-1][0], t + step)
        else:
            dirty.append((t, t + step))
    hours = (t1 - t0).total_seconds() / 3600
    dirty_h = sum((b - a).total_seconds() for a, b in dirty) / 3600
    zone = series[0].zone
    words = (f"Clean for all of the next {hours:.0f} hours." if not dirty else
             f"Below {min_renewable:.0f}% renewable for {dirty_h:.0f} of the next "
             f"{hours:.0f} hours (shaded). Runs with <code>wait = true</code> would pause "
             f"then.")
    chart = timeline(pts, t0, t1, "%", "Grid renewables forecast", dirty, vmax=100, area=True,
                     step=True, threshold=min_renewable,
                     shade_title=f"Below {min_renewable:.0f}% renewable")
    return (f'<h2>Grid forecast</h2><p class="muted">{_e(zone)}, from when this report was '
            f'generated. Times in UTC. {words}</p><div class="card">{chart}</div>')


def _latest(run: Run) -> str:
    pts: list[tuple[datetime, float]] = []
    renew: list[tuple[datetime, float]] = []
    pauses: list[tuple[datetime, datetime]] = []
    for s in run.measured:
        k = s.get("overhead", 1.0)
        for ts, w in s.get("timeline", []):
            t = parse_ts(ts)
            if t:
                pts.append((t, w * k))
        for iv in s.get("intervals", []):
            t = parse_ts(iv.get("from"))
            if t and iv.get("renewable_fraction") is not None:
                renew.append((t, iv["renewable_fraction"] * 100))
        for a, b in s.get("pauses", []):
            ta, tb = parse_ts(a), parse_ts(b)
            if ta and tb:
                pauses.append((ta, tb))
    if not pts:
        return '<p class="empty">This run has no power readings yet.</p>'
    t0 = parse_ts(run.segments[0].get("start")) or pts[0][0]
    t1 = parse_ts(run.segments[-1].get("end")) or pts[-1][0]
    head = (f'<p class="muted">{_e(run.project)} · {_e(run.doc.get("model", ""))} · '
            f'{_e(run.doc.get("output", ""))}</p>')
    power = timeline(pts, t0, t1, " W", "Power draw", pauses)
    grid = (timeline(renew, t0, t1, "%", "Grid renewables", pauses, vmax=100, area=True,
                     step=True)
            if renew else '<p class="empty">No grid readings for this run.</p>')
    return (f'{head}<h3>Power draw</h3>{power}<h3>Grid renewables</h3>{grid}'
            f'<p class="muted">Shaded spans are pauses for a dirty grid.</p>')


_CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;
--s8:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
--surface:#1a1a19;--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--s7:#9085e9;--s8:#e66767}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:40px 0 4px}
h3{font-size:14px;margin:20px 0 4px;color:var(--ink2)}
.muted,.note,.empty{color:var(--ink2);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
margin-top:24px}
.tile,.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
padding:16px}
.card{margin-top:12px;overflow-x:auto}.card svg{min-width:560px}
.tlabel{font-size:13px;color:var(--ink2)}
.tvalue{font-size:30px;font-weight:600;margin:2px 0}
svg{width:100%;height:auto;display:block}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.label{fill:var(--ink2);font-size:12px}.value{fill:var(--ink);font-size:12px;font-weight:600}
.line{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.wash{fill:var(--s1);opacity:.1}.dot{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.pause{fill:var(--muted);opacity:.12}
.threshold{stroke:var(--ink2);stroke-width:1;stroke-dasharray:4 3}.hit{fill:transparent}
.hit:hover{fill:var(--ink);opacity:.05}
path.s1{fill:var(--s1)}path.s2{fill:var(--s2)}path.s3{fill:var(--s3)}path.s4{fill:var(--s4)}
path.s5{fill:var(--s5)}path.s6{fill:var(--s6)}path.s7{fill:var(--s7)}path.s8{fill:var(--s8)}
path[class^=s]:hover{opacity:.8}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;color:var(--ink2);margin:8px 0}
.k{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.k.s1{background:var(--s1)}.k.s2{background:var(--s2)}.k.s3{background:var(--s3)}
.k.s4{background:var(--s4)}.k.s5{background:var(--s5)}.k.s6{background:var(--s6)}
.k.s7{background:var(--s7)}.k.s8{background:var(--s8)}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--ink2);font-weight:600}
code{font-size:13px}
@media print{body{background:#fff}.tile,.card{break-inside:avoid}}
"""

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carbon report</title><style>{css}</style></head>
<body><main>
<h1>Carbon report</h1>
<p class="muted">Energy and emissions of paratext runs. Generated {generated}.</p>
<div class="tiles">{tiles}</div>
{note}
{forecast}
<h2>Energy by month</h2>
<div class="card">{legend}{energy}</div>
<h2>Emissions by month</h2>
<div class="card">{legend}{emissions}</div>
<h2>Energy per record</h2>
<p class="muted">By project and model: lower is more efficient.</p>
<div class="card">{efficiency}</div>
<h2>Latest run</h2>
<div class="card">{latest}</div>
<h2>Runs</h2>
<div class="card tablewrap"><table>
<thead><tr><th>Project</th><th>Model</th><th>Start (UTC)</th><th>Records</th><th>kWh</th>
<th>Wh/record</th><th>gCO₂e</th><th>Renewable</th><th>Hours paused</th><th>Meter</th></tr>
</thead><tbody>{table_rows}</tbody></table></div>
<h2>Method</h2>
<div class="card">
<p><strong>Energy</strong> is read from hardware power sensors on the machine that ran the
model, every 10 seconds: AMD <code>amdgpu</code> (on an APU this is socket power, covering CPU
and GPU), Intel/AMD RAPL CPU counters, and NVIDIA NVML GPU counters. The meter column says
which were used. Sensors see the processor only, not disks, fans or power-supply losses; the
<code>overhead</code> multiplier in the CSV (default 1.0) is applied to cover the rest when a
site sets one.</p>
<p><strong>Not measured</strong> means no figure was taken: the model ran on a hosted
endpoint, which this machine's sensors cannot see, or the machine has no readable sensor.
paratext does not estimate energy; those runs are listed with their records and no
energy.</p>
<p><strong>Emissions</strong> are location-based: energy in each grid interval (30 minutes
for the UK) multiplied by that interval's carbon intensity for the declared grid zone, from
the provider shown in the CSV. UK regional intensities are forecasts; the
<code>intensity_basis</code> column records which kind was used.</p>
<p><strong>Clean grid</strong> is the share of measured energy used while renewables (wind,
solar, hydro) were at or above the run's threshold, 70% unless configured.</p>
</div>
<script type="application/json" id="data">{data}</script>
</main></body></html>
"""
