"""Grid providers, the clean-grid threshold and the [carbon] config."""

import pytest

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
    assert r.zone == "GB" and r.carbon_gco2 == 167 and r.basis == "actual"
    assert round(r.renewable_fraction * 100, 1) == 37.7  # wind+solar+hydro, biomass excluded


def test_uk_current_regional(monkeypatch):
    monkeypatch.setattr(carbon, "_get", lambda url, headers=None, timeout=10.0: _REGIONAL_SS)
    r = carbon.uk_current("south-scotland")
    assert r.zone == "South Scotland" and r.carbon_gco2 == 5 and r.basis == "forecast"
    assert round(r.renewable_fraction * 100, 1) == 84.9


def test_threshold():
    r = Reading("uk", "GB", carbon_gco2=120, renewable_fraction=0.6, index="moderate", ts=None)
    assert r.is_clean(50) is True
    assert r.is_clean(80) is False
    assert CarbonConfig().min_renewable == carbon.DEFAULT_MIN_RENEWABLE
    assert Reading("energy-charts", "DE", None, None, None, None).is_clean(10) is False


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


@pytest.mark.real_carbon
def test_load_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert carbon.load_config().declared is False  # no [carbon] table: grid unknown
    (tmp_path / "paratext.toml").write_text(
        '[carbon]\nregion = "south-scotland"\nwait = true\nmin-renewable = 80\n'
        'overhead = 1.2\n'
    )
    cfg = carbon.load_config()
    assert cfg.declared and cfg.wait and cfg.min_renewable == 80 and cfg.overhead == 1.2
    monkeypatch.setenv("PARATEXT_CARBON_WAIT", "false")
    assert carbon.load_config().wait is False


def test_suggestion_has_no_threshold():
    toml = carbon.suggestion_toml({"provider": "uk", "region": "EH32", "region_name": None})
    assert "min-renewable" not in toml and "# wait = true" in toml
