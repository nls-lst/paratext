"""Carbon-aware scheduling: parsing, thresholds, window pick, gating, providers."""

import paratext.carbon as carbon
from paratext.carbon import CarbonConfig, Reading

# Real-shape fixtures (trimmed from live api.carbonintensity.org.uk responses).
_NATIONAL_INTENSITY = {"data": [{"from": "2026-07-01T19:30Z", "intensity": {
    "forecast": 147, "actual": 167, "index": "moderate"}}]}
_NATIONAL_GEN = {"data": {"from": "2026-07-01T19:30Z", "generationmix": [
    {"fuel": "gas", "perc": 36.6}, {"fuel": "wind", "perc": 35.3},
    {"fuel": "solar", "perc": 1.4}, {"fuel": "hydro", "perc": 1.0},
    {"fuel": "nuclear", "perc": 9.0}]}}
_REGIONAL_SS = {"data": [{"regionid": 2, "shortname": "South Scotland", "data": [
    {"from": "2026-07-01T19:30Z", "intensity": {"forecast": 5, "index": "very low"},
     "generationmix": [{"fuel": "wind", "perc": 84.5}, {"fuel": "solar", "perc": 0.4},
                       {"fuel": "hydro", "perc": 0.0}, {"fuel": "nuclear", "perc": 13.5}]}]}]}


def test_regional_path():
    assert carbon._uk_regional_path(2) == "regionid/2"
    assert carbon._uk_regional_path("2") == "regionid/2"
    assert carbon._uk_regional_path("south-scotland") == "regionid/2"
    assert carbon._uk_regional_path("South Scotland") == "regionid/2"
    assert carbon._uk_regional_path("EH1") == "postcode/EH1"


def test_uk_current_national(monkeypatch):
    urls = []

    def fake_get(url, headers=None, timeout=10.0):
        urls.append(url)
        return _NATIONAL_INTENSITY if url.endswith("/intensity") else _NATIONAL_GEN

    monkeypatch.setattr(carbon, "_get", fake_get)
    r = carbon.uk_current(None)
    assert r.zone == "GB" and r.carbon_gco2 == 147
    assert round(r.renewable_fraction * 100, 1) == 37.7  # wind+solar+hydro, biomass excluded


def test_uk_current_regional(monkeypatch):
    monkeypatch.setattr(carbon, "_get", lambda url, headers=None, timeout=10.0: _REGIONAL_SS)
    r = carbon.uk_current("south-scotland")
    assert r.zone == "South Scotland" and r.carbon_gco2 == 5
    assert round(r.renewable_fraction * 100, 1) == 84.9


def test_thresholds_and_default():
    r = Reading("uk", "GB", carbon_gco2=120, renewable_fraction=0.6, index="moderate", ts=None)
    assert r.is_clean(min_renewable=50, max_carbon=None) is True
    assert r.is_clean(min_renewable=80, max_carbon=None) is False
    assert r.is_clean(min_renewable=50, max_carbon=100) is False  # AND: carbon too high
    # default kicks in when nothing configured
    assert CarbonConfig()._effective() == (carbon.DEFAULT_MIN_RENEWABLE, None)


def test_duration_parse():
    assert carbon._dur("15m", 0) == 900
    assert carbon._dur("12h", 0) == 43200
    assert carbon._dur("45s", 0) == 45
    assert carbon._dur(None, 99) == 99


def test_cleanest_window():
    vals = [200, 180, 40, 30, 35, 220]
    readings = [Reading("uk", "GB", v, None, None, None) for v in vals]
    i, avg = carbon.cleanest_window(readings, block=2)
    assert i == 3 and avg == 32.5  # (30+35)/2 is the greenest 1h (two 30-min) block


def test_wait_for_clean_polls_until_clean(monkeypatch):
    seq = iter([
        Reading("uk", "GB", 300, 0.30, "high", None),   # dirty
        Reading("uk", "GB", 90, 0.82, "low", None),      # clean
    ])
    monkeypatch.setattr(carbon, "current_reading", lambda cfg: next(seq))
    slept = []
    cfg = CarbonConfig(min_renewable=80)
    r = carbon.wait_for_clean(cfg, log=lambda *a: None, sleep=slept.append)
    assert r.renewable_fraction == 0.82 and len(slept) == 1  # waited once, then proceeded


def test_suggest_region_uk(monkeypatch):
    def fake_get(url, headers=None, timeout=10.0):
        if "ip-api" in url:
            return {"status": "success", "country": "United Kingdom", "countryCode": "GB",
                    "regionName": "Scotland", "city": "Prestonpans", "zip": "EH32"}
        return {"data": [{"regionid": 2, "shortname": "South Scotland"}]}

    monkeypatch.setattr(carbon, "_get", fake_get)
    info = carbon.suggest_region()
    assert info["provider"] == "uk" and info["region"] == "EH32"
    assert info["region_name"] == "South Scotland"
    toml = carbon.suggestion_toml(info)
    assert 'provider = "uk"' in toml and 'region = "EH32"  # South Scotland' in toml


def test_suggest_region_non_gb(monkeypatch):
    monkeypatch.setattr(
        carbon, "_get",
        lambda url, headers=None, timeout=10.0: {
            "status": "success", "country": "France", "countryCode": "FR", "city": "Paris"},
    )
    info = carbon.suggest_region()
    assert info["provider"] == "energy-charts" and info["zone"] == "fr"  # tokenless EU default
    assert 'zone = "fr"' in carbon.suggestion_toml(info)


# Trimmed energy-charts /signal response: renewable share-of-load + 15-min series.
def _ec_signal(now):
    return {"unix_seconds": [now - 900, now, now + 900, now + 1800],
            "share": [20.0, 22.0, 90.0, 121.0], "signal": [0, 0, 0, 0]}


def test_energy_charts_current(monkeypatch):
    import time as _t
    sig = _ec_signal(_t.time())
    monkeypatch.setattr(carbon, "_get", lambda url, headers=None, timeout=10.0: sig)
    r = carbon.ec_current("de")
    assert r.provider == "energy-charts" and r.zone == "DE"
    assert r.carbon_gco2 is None and round(r.renewable_fraction * 100) == 22  # nearest to now


def test_cleanest_window_by_renewable_when_no_carbon():
    # carbon absent → pick the block with the highest renewable share
    fr = [0.20, 0.25, 0.90, 0.85, 0.30]
    readings = [Reading("energy-charts", "DE", None, f, None, None) for f in fr]
    i, _ = carbon.cleanest_window(readings, block=2)
    assert i == 2  # (0.90+0.85) is the greenest 2-period block


def test_wait_for_clean_gives_up_at_max_wait(monkeypatch):
    monkeypatch.setattr(
        carbon, "current_reading",
        lambda cfg: Reading("uk", "GB", 400, 0.10, "very high", None),
    )
    cfg = CarbonConfig(min_renewable=80, max_wait_s=0)  # already past deadline
    r = carbon.wait_for_clean(cfg, log=lambda *a: None, sleep=lambda s: None)
    assert r.carbon_gco2 == 400  # proceeded anyway
