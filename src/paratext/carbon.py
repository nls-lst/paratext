"""Carbon-aware scheduling — wait for a clean grid before running extraction.

Opt-in via `paratext run --green` (or `extract --green`); thresholds and the grid
zone live in a top-level `[carbon]` table in `paratext.toml`. Providers:

- **uk** (default) — the UK Carbon Intensity API (carbonintensity.org.uk): no
  auth, national *or* per-DNO-region readings, and a 48h forecast for "run in the
  greenest window" scheduling. Regional matters a lot: South Scotland is often
  ~85% wind while GB-wide is ~35%.
- **electricitymaps** — global coverage via a free API token (config `token` or
  `PARATEXT_CARBON_TOKEN`); latest reading only (no forecast on the free tier).

The grid zone is *declared*, not detected (a box is reachable both locally and
remotely, so we can't infer where compute runs). See docs/hf-export-spec.md.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config

# Fuels counted as renewable in the UK generation mix (biomass excluded — its
# renewability is contested). Tune here if your accounting differs.
RENEWABLE_FUELS = ("wind", "solar", "hydro")

# When --green is set but no threshold is configured, wait for at least this
# renewable share. Deliberately modest so it's satisfiable on most grids.
DEFAULT_MIN_RENEWABLE = 70.0

UK_BASE = "https://api.carbonintensity.org.uk"
EM_BASE = "https://api.electricitymaps.com/v3"

# The 14 GB DNO regions, so a friendly slug works in config instead of an id.
UK_REGION_SLUGS = {
    "north-scotland": 1,
    "south-scotland": 2,
    "north-west-england": 3,
    "north-east-england": 4,
    "yorkshire": 5,
    "north-wales": 6,
    "south-wales": 7,
    "west-midlands": 8,
    "east-midlands": 9,
    "east-england": 10,
    "south-west-england": 11,
    "south-england": 12,
    "london": 13,
    "south-east-england": 14,
}


@dataclass
class Reading:
    provider: str
    zone: str
    carbon_gco2: float | None
    renewable_fraction: float | None  # 0..1
    index: str | None
    ts: str | None

    def is_clean(self, min_renewable: float | None, max_carbon: float | None) -> bool:
        """True if every configured constraint is satisfied (AND)."""
        ok = True
        if min_renewable is not None:
            ok = ok and self.renewable_fraction is not None and (
                self.renewable_fraction * 100 >= min_renewable
            )
        if max_carbon is not None:
            ok = ok and self.carbon_gco2 is not None and self.carbon_gco2 <= max_carbon
        return ok

    def summary(self) -> str:
        parts = []
        if self.renewable_fraction is not None:
            parts.append(f"{self.renewable_fraction * 100:.0f}% renewable")
        if self.carbon_gco2 is not None:
            parts.append(f"{self.carbon_gco2:.0f} gCO2/kWh")
        if self.index:
            parts.append(self.index)
        return f"{self.zone}: " + (", ".join(parts) if parts else "no data")

    def to_provenance(self, scheduled_window: bool = False) -> dict:
        return {
            "provider": self.provider,
            "zone": self.zone,
            "carbon_gco2": self.carbon_gco2,
            "renewable_fraction": self.renewable_fraction,
            "index": self.index,
            "ts": self.ts,
            "scheduled_window": scheduled_window,
        }


@dataclass
class CarbonConfig:
    provider: str = "uk"
    region: str | int | None = None  # uk: DNO id/slug/outcode; None = national
    zone: str | None = None  # electricitymaps zone (e.g. "GB")
    token: str | None = None
    min_renewable: float | None = None
    max_carbon: float | None = None
    mode: str = "poll"  # poll | window
    max_wait_s: int = 12 * 3600
    poll_s: int = 15 * 60
    window_hours: int = 24
    window_run_hours: float = 1.0

    def effective_thresholds(self) -> tuple[float | None, float | None]:
        """The thresholds to gate on, applying the default when none are set."""
        if self.min_renewable is None and self.max_carbon is None:
            return DEFAULT_MIN_RENEWABLE, None
        return self.min_renewable, self.max_carbon

    def target_str(self) -> str:
        mr, mc = self.effective_thresholds()
        bits = []
        if mr is not None:
            bits.append(f"≥{mr:.0f}% renewable")
        if mc is not None:
            bits.append(f"≤{mc:.0f} gCO2/kWh")
        return " and ".join(bits)


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _get(url: str, headers: dict | None = None, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── UK provider ──────────────────────────────────────────────────────────────
def _uk_regional_path(region: str | int) -> str:
    if isinstance(region, int) or (isinstance(region, str) and region.isdigit()):
        return f"regionid/{int(region)}"
    slug = str(region).strip().lower().replace(" ", "-")
    if slug in UK_REGION_SLUGS:
        return f"regionid/{UK_REGION_SLUGS[slug]}"
    return f"postcode/{str(region).strip().upper()}"  # treat as a UK outcode


def _uk_reading(period: dict, zone: str) -> Reading:
    mix = {m["fuel"]: m.get("perc", 0) for m in period.get("generationmix", [])}
    renew = sum(mix.get(f, 0) for f in RENEWABLE_FUELS) / 100 if mix else None
    intensity = period.get("intensity", {}) or {}
    gco2 = intensity.get("forecast")
    if gco2 is None:
        gco2 = intensity.get("actual")
    return Reading("uk", zone, gco2, renew, intensity.get("index"), period.get("from"))


def uk_current(region: str | int | None = None) -> Reading:
    if region is None:
        i = _get(f"{UK_BASE}/intensity")["data"][0]
        g = _get(f"{UK_BASE}/generation")["data"]
        period = {
            "intensity": i["intensity"],
            "generationmix": g["generationmix"],
            "from": i["from"],
        }
        return _uk_reading(period, "GB")
    d = _get(f"{UK_BASE}/regional/{_uk_regional_path(region)}")["data"][0]
    return _uk_reading(d["data"][0], d.get("shortname") or str(region))


def uk_forecast(region: str | int | None = None, hours: int = 24) -> list[Reading]:
    frm = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    win = "fw48h" if hours > 24 else "fw24h"
    if region is None:
        periods = _get(f"{UK_BASE}/intensity/{frm}/{win}")["data"]
        zone = "GB"
    else:
        d = _get(f"{UK_BASE}/regional/intensity/{frm}/{win}/{_uk_regional_path(region)}")["data"]
        periods, zone = d["data"], d.get("shortname") or str(region)
    return [_uk_reading(p, zone) for p in periods]


# ── Electricity Maps provider ────────────────────────────────────────────────
def em_current(zone: str, token: str) -> Reading:
    if not token:
        raise SystemExit("electricitymaps needs a token (config `token` or PARATEXT_CARBON_TOKEN)")
    h = {"auth-token": token}
    ci = _get(f"{EM_BASE}/carbon-intensity/latest?zone={zone}", headers=h)
    pb = _get(f"{EM_BASE}/power-breakdown/latest?zone={zone}", headers=h)
    rp = pb.get("renewablePercentage")
    return Reading(
        "electricitymaps",
        zone,
        ci.get("carbonIntensity"),
        rp / 100 if rp is not None else None,
        None,
        ci.get("datetime"),
    )


# ── Dispatch ─────────────────────────────────────────────────────────────────
def current_reading(cfg: CarbonConfig) -> Reading:
    if cfg.provider == "uk":
        return uk_current(cfg.region)
    if cfg.provider == "electricitymaps":
        return em_current(cfg.zone or str(cfg.region or "GB"), cfg.token or "")
    raise SystemExit(f"unknown carbon provider: {cfg.provider!r} (use uk | electricitymaps)")


def cleanest_window(readings: list[Reading], block: int) -> tuple[int, float | None]:
    """Index of the lowest-average-carbon contiguous block of `block` periods."""
    vals = [r.carbon_gco2 for r in readings]
    best_i, best_avg = 0, None
    for i in range(max(1, len(readings) - block + 1)):
        w = [v for v in vals[i : i + block] if v is not None]
        if not w:
            continue
        avg = sum(w) / len(w)
        if best_avg is None or avg < best_avg:
            best_i, best_avg = i, avg
    return best_i, best_avg


# ── Gating ───────────────────────────────────────────────────────────────────
def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def wait_for_clean(cfg: CarbonConfig, log=print, sleep=time.sleep) -> Reading:
    """Block until the grid meets the threshold (or max-wait elapses), then
    return the reading used to proceed. In `window` mode, schedule to the
    greenest forecast window instead of polling."""
    if cfg.mode == "window":
        return _wait_window(cfg, log, sleep)

    mr, mc = cfg.effective_thresholds()
    deadline = time.monotonic() + cfg.max_wait_s
    while True:
        r = current_reading(cfg)
        if r.is_clean(mr, mc):
            log(f"grid clean — {r.summary()}; proceeding")
            return r
        if time.monotonic() >= deadline:
            log(f"max-wait reached — proceeding anyway at {r.summary()}")
            return r
        log(
            f"waiting for {cfg.target_str()} — now {r.summary()}; "
            f"next check in {cfg.poll_s // 60}m"
        )
        sleep(cfg.poll_s)


def _wait_window(cfg: CarbonConfig, log, sleep) -> Reading:
    if cfg.provider != "uk":
        log(f"window mode needs forecasts (uk only); falling back to poll for {cfg.provider}")
        cfg.mode = "poll"
        return wait_for_clean(cfg, log, sleep)

    horizon = min(cfg.window_hours, max(1, cfg.max_wait_s // 3600))
    forecast = uk_forecast(cfg.region, horizon)
    block = max(1, round(cfg.window_run_hours * 2))  # 30-min periods
    i, avg = cleanest_window(forecast, block)
    start = _parse_ts(forecast[i].ts)
    log(
        f"greenest {cfg.window_run_hours:g}h window in next {horizon}h: "
        f"{forecast[i].summary()} (avg {avg:.0f} gCO2/kWh) starting {forecast[i].ts}"
    )
    if start is not None:
        while True:
            wait = (start - datetime.now(timezone.utc)).total_seconds()
            if wait <= 0:
                break
            log(f"holding for the green window — {wait / 60:.0f}m to go")
            sleep(min(wait, cfg.poll_s))
    return forecast[i]


# ── Config ───────────────────────────────────────────────────────────────────
def _dur(v, default: int) -> int:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if s and s[-1] in units:
        return int(float(s[:-1]) * units[s[-1]])
    return int(float(s))


def load_config(
    *, min_renewable: float | None = None, max_carbon: float | None = None
) -> CarbonConfig:
    """Read the `[carbon]` table; CLI overrides (thresholds) win."""
    raw = config.load_table("carbon")
    return CarbonConfig(
        provider=raw.get("provider", "uk"),
        region=raw.get("region"),
        zone=raw.get("zone"),
        token=config.env_or("carbon_token") or raw.get("token"),
        min_renewable=min_renewable if min_renewable is not None else raw.get("min_renewable"),
        max_carbon=max_carbon if max_carbon is not None else raw.get("max_carbon"),
        mode=raw.get("mode", "poll"),
        max_wait_s=_dur(raw.get("max_wait"), 12 * 3600),
        poll_s=_dur(raw.get("poll"), 15 * 60),
        window_hours=int(raw.get("window_hours", 24)),
        window_run_hours=float(raw.get("window_run_hours", 1.0)),
    )
