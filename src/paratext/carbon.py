"""Grid carbon intensity: providers, the `[carbon]` config, and the clean-grid test.

Measuring a run's energy lives in `meters.py` and `tracking.py`; this module
answers "what is the grid doing?" for the zone the user declared. Providers:

- **uk** (default) — the UK Carbon Intensity API (carbonintensity.org.uk): no
  auth, national *or* per-DNO-region readings, and a 48h forecast. Regional
  matters a lot: South Scotland is often ~85% wind while GB-wide is ~35%.
- **energy-charts** — Fraunhofer ISE, EU countries, no token. Renewable share
  only, so emissions can't be computed from it.
- **electricitymaps** — global, free token (config `token` or
  `PARATEXT_CARBON_TOKEN`); latest reading only.

The grid zone is *declared*, not detected (a box is reachable both locally and
remotely, so we can't infer where compute runs). Without a `[carbon]` table a run
is still measured, but its emissions aren't computed.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config

# Fuels counted as renewable in the UK generation mix (biomass excluded — its
# renewability is contested).
RENEWABLE_FUELS = ("wind", "solar", "hydro")

DEFAULT_MIN_RENEWABLE = 70.0

UK_BASE = "https://api.carbonintensity.org.uk"
EM_BASE = "https://api.electricitymaps.com/v3"
EC_BASE = "https://api.energy-charts.info"

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
    basis: str | None = None  # forecast | actual | live — how carbon_gco2 was made

    def is_clean(self, min_renewable: float) -> bool:
        return self.renewable_fraction is not None and (
            self.renewable_fraction * 100 >= min_renewable
        )

    def summary(self) -> str:
        parts = []
        if self.renewable_fraction is not None:
            parts.append(f"{self.renewable_fraction * 100:.0f}% renewable")
        if self.carbon_gco2 is not None:
            parts.append(f"{self.carbon_gco2:.0f} gCO2/kWh")
        if self.index:
            parts.append(self.index)
        return f"{self.zone}: " + (", ".join(parts) if parts else "no data")


@dataclass
class CarbonConfig:
    provider: str = "uk"
    region: str | int | None = None  # uk: DNO id/slug/outcode; None = national
    zone: str | None = None  # electricitymaps / energy-charts zone (e.g. "GB", "de")
    token: str | None = None
    min_renewable: float = DEFAULT_MIN_RENEWABLE
    wait: bool = False
    overhead: float = 1.0
    declared: bool = False  # a [carbon] table exists, so the grid is known

    def is_clean(self, r: Reading) -> bool:
        return r.is_clean(self.min_renewable)

    def target_str(self) -> str:
        return f"≥{self.min_renewable:.0f}% renewable"

    @property
    def period_minutes(self) -> int:
        """The provider's own reporting interval, which emissions are bucketed by."""
        return 15 if self.provider == "energy-charts" else 30


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
    gco2, basis = intensity.get("actual"), "actual"
    if gco2 is None:
        gco2, basis = intensity.get("forecast"), "forecast"
    return Reading(
        "uk", zone, gco2, renew, intensity.get("index"), period.get("from"),
        basis if gco2 is not None else None,
    )


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
    gco2 = ci.get("carbonIntensity")
    return Reading(
        "electricitymaps",
        zone,
        gco2,
        rp / 100 if rp is not None else None,
        None,
        ci.get("datetime"),
        "live" if gco2 is not None else None,
    )


# ── Energy-Charts provider (Fraunhofer ISE — no token, EU countries) ──────────
def _ec_reading(series: dict, idx: int, country: str) -> Reading:
    share = series["share"][idx]
    ts = datetime.fromtimestamp(series["unix_seconds"][idx], timezone.utc).strftime(
        "%Y-%m-%dT%H:%MZ"
    )
    return Reading(
        "energy-charts",
        country.upper(),
        None,  # the signal endpoint reports renewable share, not gCO2/kWh
        share / 100 if share is not None else None,
        None,
        ts,
    )


def ec_current(country: str) -> Reading:
    d = _get(f"{EC_BASE}/signal?country={country.lower()}")
    now = time.time()
    secs = d["unix_seconds"]
    idx = min(range(len(secs)), key=lambda i: abs(secs[i] - now))
    return _ec_reading(d, idx, country)


def ec_forecast(country: str, hours: int = 24) -> list[Reading]:
    d = _get(f"{EC_BASE}/signal?country={country.lower()}")
    now, horizon = time.time(), time.time() + hours * 3600
    return [
        _ec_reading(d, i, country)
        for i, s in enumerate(d["unix_seconds"])
        if now - 900 <= s <= horizon
    ]


# ── Dispatch ─────────────────────────────────────────────────────────────────
def current_reading(cfg: CarbonConfig) -> Reading:
    if cfg.provider == "uk":
        return uk_current(cfg.region)
    if cfg.provider == "electricitymaps":
        return em_current(cfg.zone or str(cfg.region or "GB"), cfg.token or "")
    if cfg.provider == "energy-charts":
        return ec_current(cfg.zone or str(cfg.region or ""))
    raise SystemExit(
        f"unknown carbon provider: {cfg.provider!r} (use uk | energy-charts | electricitymaps)"
    )


def forecast(cfg: CarbonConfig, hours: int = 24) -> list[Reading] | None:
    """The forecast series, or None if the provider has no free forecast."""
    if cfg.provider == "uk":
        return uk_forecast(cfg.region, hours)
    if cfg.provider == "energy-charts":
        return ec_forecast(cfg.zone or str(cfg.region or ""), hours)
    return None


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── Region suggestion (IP geolocation — suggest, never silently detect) ───────
IPGEO_URL = "http://ip-api.com/json/?fields=status,country,countryCode,regionName,city,zip"


def suggest_region() -> dict:
    """Geolocate this box's public IP and suggest a `[carbon]` config. IP-geo is
    approximate and may reflect the ISP/hosting registration rather than the
    physical site — a *suggestion* to confirm, not an authoritative location."""
    geo = _get(IPGEO_URL)
    if geo.get("status") != "success":
        raise SystemExit("IP geolocation failed — set [carbon] region manually")
    cc = geo.get("countryCode")
    info = {
        "country": geo.get("country"),
        "country_code": cc,
        "city": geo.get("city"),
        "zip": geo.get("zip"),
    }
    if cc == "GB":
        outcode = (geo.get("zip") or "").split()[0].upper() or None
        region_name = None
        if outcode:
            try:
                region_name = _get(f"{UK_BASE}/regional/postcode/{outcode}")["data"][0].get(
                    "shortname"
                )
            except Exception:
                region_name = None
        info.update(provider="uk", region=outcode, region_name=region_name, note=None)
    else:
        info.update(
            provider="energy-charts", zone=cc.lower(), region=None, region_name=None,
            note="energy-charts (Fraunhofer) covers EU countries with no token; "
            "for non-EU grids use provider=electricitymaps with a token.",
        )
    return info


def suggestion_toml(info: dict) -> str:
    """Render a ready-to-paste `[carbon]` block from `suggest_region()`."""
    p = info["provider"]
    lines = ["[carbon]", f'provider = "{p}"']
    if p == "uk" and info.get("region"):
        comment = f"  # {info['region_name']}" if info.get("region_name") else ""
        lines.append(f'region = "{info["region"]}"{comment}')
    elif p == "energy-charts":
        lines.append(f'zone = "{info.get("zone")}"')
    elif p == "electricitymaps":
        lines.append(f'zone = "{info.get("zone")}"')
        lines.append('# token = "..."   # from electricitymaps.com')
    lines.append("# wait = true   # pause runs while the grid is dirty")
    return "\n".join(lines) + "\n"


# ── Config ───────────────────────────────────────────────────────────────────
def _bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def load_config() -> CarbonConfig:
    """Read the `[carbon]` table; `PARATEXT_CARBON_WAIT` overrides `wait`."""
    raw = config.load_table("carbon")
    wait = config.env_or("carbon_wait")
    return CarbonConfig(
        provider=raw.get("provider", "uk"),
        region=raw.get("region"),
        zone=raw.get("zone"),
        token=config.env_or("carbon_token") or raw.get("token"),
        min_renewable=float(raw.get("min_renewable", DEFAULT_MIN_RENEWABLE)),
        wait=_bool(wait if wait is not None else raw.get("wait", False)),
        overhead=float(raw.get("overhead", 1.0)),
        declared=bool(raw),
    )
