"""The run tracker: energy per interval, emissions, sidecar, resume, waiting."""

import json

import pytest

from paratext import tracking
from paratext.carbon import CarbonConfig, Reading
from paratext.meters import Meter, Sensor


class Watts(Sensor):
    kind = "fake"

    def __init__(self, w):
        self.w = w

    def watts(self):
        return self.w


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


T0 = 1_800_000_000.0 // 1800 * 1800  # on a 30-min boundary


def _tracker(tmp_path, clock, *, cfg=None, readings=None, base_url="http://localhost:1235/v1",
             watts=100.0, **kw):
    readings = readings if readings is not None else []
    it = iter(readings)
    return tracking.Tracker(
        tmp_path / "out.jsonl", project="cards", model="m", base_url=base_url,
        cfg=cfg or CarbonConfig(declared=True), meter=Meter([Watts(watts)]),
        meter_note="fake", runs_dir=tmp_path / "runs", clock=clock,
        reading_fn=lambda cfg: next(it), log=lambda *a: None, sample_s=3600, **kw,
    )


def _r(g, ren):
    return Reading("uk", "South Scotland", g, ren, None, None, "forecast")


def test_is_local():
    assert tracking.is_local("http://localhost:1235/v1")
    assert tracking.is_local("http://127.0.0.1:8000/v1")
    assert tracking.is_local("http://[::1]:8000/v1")
    assert not tracking.is_local("https://api.example.org/v1")
    assert not tracking.is_local("http://192.168.1.20:8000/v1")  # another machine


def test_energy_and_emissions_per_interval(tmp_path):
    clock = Clock(T0)
    t = _tracker(tmp_path, clock, readings=[_r(100, 0.5), _r(0, 1.0)])
    t.start()
    clock.t = T0 + 1800  # first half-hour at 100 W = 50 Wh, at 100 g/kWh = 5 g
    t.tick()
    clock.t = T0 + 3600  # second half-hour = 50 Wh at 0 g/kWh
    t.tick()
    t.record(10)
    out = t.stop()
    assert out["wh"] == pytest.approx(100)
    assert out["gco2e"] == pytest.approx(5)
    assert out["renewable_fraction"] == pytest.approx(0.75)
    assert out["intensity_basis"] == "forecast"
    doc = json.loads(t.path.read_text())
    seg = doc["segments"][0]
    assert seg["records"] == 10 and seg["meter"] == "fake" and seg["zone"] == "South Scotland"
    assert all("_b" not in iv for iv in seg["intervals"])


def test_overhead_scales_figures(tmp_path):
    clock = Clock(T0)
    t = _tracker(tmp_path, clock, cfg=CarbonConfig(declared=True, overhead=1.5),
                 readings=[_r(100, 0.5)])
    t.start()
    clock.t = T0 + 1800
    out = t.stop()
    assert out["wh"] == pytest.approx(75) and out["gco2e"] == pytest.approx(7.5)


def test_resume_adds_a_segment(tmp_path):
    for _ in range(2):
        clock = Clock(T0)
        t = _tracker(tmp_path, clock, readings=[_r(10, 0.9)])
        t.start()
        clock.t = T0 + 600
        t.stop()
    doc = json.loads(t.path.read_text())
    assert len(doc["segments"]) == 2


def test_hosted_is_not_measured(tmp_path):
    clock = Clock(T0)
    t = _tracker(tmp_path, clock, base_url="https://openrouter.ai/api/v1")
    t.start()
    t.record(3)
    clock.t = T0 + 600
    out = t.stop()
    assert out["wh"] is None and out["gco2e"] is None
    seg = json.loads(t.path.read_text())["segments"][0]
    assert seg["meter"] is None and seg["endpoint"] == "hosted" and seg["records"] == 3


def test_undeclared_grid_measures_energy_only(tmp_path):
    clock = Clock(T0)
    t = _tracker(tmp_path, clock, cfg=CarbonConfig(declared=False))
    t.start()
    clock.t = T0 + 1800
    out = t.stop()
    assert out["wh"] == pytest.approx(50) and out["gco2e"] is None


def test_grid_failure_does_not_stop_the_run(tmp_path):
    clock = Clock(T0)

    def boom(cfg):
        raise OSError("offline")

    t = tracking.Tracker(
        tmp_path / "o.jsonl", project="p", model="m", base_url="http://localhost/v1",
        cfg=CarbonConfig(declared=True), meter=Meter([Watts(10)]), meter_note="fake",
        runs_dir=tmp_path / "runs", clock=clock, reading_fn=boom, log=lambda *a: None,
        sample_s=3600,
    )
    t.start()
    clock.t = T0 + 1800
    out = t.stop()
    assert out["wh"] == pytest.approx(5) and out["gco2e"] is None


def test_wait_pauses_until_clean(tmp_path):
    clock = Clock(T0)
    slept = []

    def sleep(s):
        slept.append(s)
        clock.t += s

    t = _tracker(tmp_path, clock, cfg=CarbonConfig(declared=True, wait=True),
                 readings=[_r(300, 0.3), _r(250, 0.4), _r(20, 0.9)], sleep=sleep)
    t.start()  # interval 1: dirty
    t.wait_if_dirty()
    assert len(slept) == 2  # dirty for two intervals, clean on the third
    assert t.seg["paused_s"] == pytest.approx(sum(slept))
    assert len(t.seg["pauses"]) == 1
    t.wait_if_dirty()  # still the clean interval: no further pause
    assert len(slept) == 2


def test_wait_gives_up_after_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(tracking, "MAX_PAUSE_S", 3600)
    clock = Clock(T0)

    def sleep(s):
        clock.t += s

    dirty = [_r(400, 0.1)] * 10
    t = _tracker(tmp_path, clock, cfg=CarbonConfig(declared=True, wait=True),
                 readings=dirty, sleep=sleep)
    t.start()
    t.wait_if_dirty()
    assert t.seg["paused_s"] == pytest.approx(3600)


def test_wait_off_never_pauses(tmp_path):
    clock = Clock(T0)
    t = _tracker(tmp_path, clock, readings=[_r(400, 0.1)],
                 sleep=lambda s: pytest.fail("should not sleep"))
    t.start()
    t.wait_if_dirty()
    assert t.seg["paused_s"] == 0
