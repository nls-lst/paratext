"""How `paratext carbon` words the forecast."""

from datetime import datetime, timedelta, timezone

from paratext import carbon, cli


def _series(renewables, start="2026-10-27T08:00:00Z"):
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return [carbon.Reading("uk", "South Scotland", 10, r, None,
                           (t0 + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%MZ"))
            for i, r in enumerate(renewables)]


NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc).astimezone()


def test_all_clean_is_one_line():
    lines = cli._forecast_lines(carbon.CarbonConfig(wait=True), _series([0.9] * 96), NOW)
    assert lines == ["clean for all of the next 48h (90–90% renewable)"]


def test_dirty_spells_are_named_with_bars_and_axis():
    vals = [0.9] * 96
    vals[18:27] = [0.5] * 9      # 17:00–21:30 today
    vals[65:72] = [0.5] * 7      # Wed 16:30–20:00
    lines = cli._forecast_lines(carbon.CarbonConfig(wait=True), _series(vals), NOW)
    assert len(lines) == 3
    assert lines[0].startswith("runs would pause ")
    assert " and Wed " in lines[0] and "(8h of the next 48h; 50–90% renewable)" in lines[0]
    assert len(lines[1]) == 48 and lines[2].startswith("now")


def test_a_spell_past_the_forecast_says_from():
    vals = [0.9] * 90 + [0.4] * 6
    lines = cli._forecast_lines(carbon.CarbonConfig(), _series(vals), NOW)
    assert lines[0].startswith("below 70% renewable from ")
