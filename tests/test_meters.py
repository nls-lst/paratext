"""Power meters, against a fake /sys tree."""

import pytest

from paratext import meters


def _hwmon(root, n, name, files):
    d = root / "class/hwmon" / f"hwmon{n}"
    d.mkdir(parents=True)
    (d / "name").write_text(name + "\n")
    for f, v in files.items():
        (d / f).write_text(f"{v}\n")
    return d


def _rapl(root, n, uj, max_uj=1_000_000_000):
    d = root / "class/powercap" / f"intel-rapl:{n}"
    d.mkdir(parents=True)
    (d / "energy_uj").write_text(f"{uj}\n")
    (d / "max_energy_range_uj").write_text(f"{max_uj}\n")
    sub = root / "class/powercap" / f"intel-rapl:{n}:0"  # a sub-zone: not counted twice
    sub.mkdir()
    (sub / "energy_uj").write_text("5\n")
    return d


pytestmark = pytest.mark.real_carbon


def test_apu_socket_power_alone_covers_cpu(tmp_path):
    _hwmon(tmp_path, 0, "k10temp", {})
    _hwmon(tmp_path, 1, "amdgpu", {"power1_average": 120_000_000})  # no power1_cap → APU
    _rapl(tmp_path, 0, 1000)
    m, desc = meters.detect(tmp_path, nvml=False)
    assert m.name == "amdgpu-apu" and "CPU + GPU" in desc
    assert m.joules_since_last(10) == pytest.approx(1200)  # 120 W × 10 s, RAPL not added


def test_discrete_gpu_plus_rapl(tmp_path):
    _hwmon(tmp_path, 0, "amdgpu", {"power1_average": 200_000_000, "power1_cap": 250_000_000})
    z = _rapl(tmp_path, 0, 1_000_000)
    m, desc = meters.detect(tmp_path, nvml=False)
    assert m.name == "rapl+amdgpu" and "CPU + GPU" in desc
    m.joules_since_last(0)  # primes the counter
    (z / "energy_uj").write_text("31000000\n")  # +30 J
    assert m.joules_since_last(1) == pytest.approx(30 + 200)


def test_rapl_counter_wraps(tmp_path):
    z = _rapl(tmp_path, 0, 999_000_000, max_uj=1_000_000_000)
    m, _ = meters.detect(tmp_path, nvml=False)
    m.joules_since_last(0)
    (z / "energy_uj").write_text("1000000\n")
    assert m.joules_since_last(1) == pytest.approx(2.0)


def test_unreadable_rapl_is_explained(tmp_path, monkeypatch):
    _rapl(tmp_path, 0, 1)

    def deny(self):
        raise PermissionError

    monkeypatch.setattr(meters.RaplSensor, "joules", deny)
    m, why = meters.detect(tmp_path, nvml=False)
    assert m is None and "root-only" in why


def test_no_sensor_means_no_meter(tmp_path):
    m, why = meters.detect(tmp_path, nvml=False)
    assert m is None and "no power sensor" in why
