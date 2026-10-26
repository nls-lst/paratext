"""Power sensors on the machine a run executes on.

Only sensors are read. With none available the run is `not measured`; paratext
never estimates energy. Three kinds are supported, all without extra packages:

- **amdgpu** — hwmon `power1_average` (µW). On an APU this is socket power (PPT)
  and covers CPU + GPU, so RAPL is not added on top.
- **rapl** — `/sys/class/powercap/intel-rapl:N/energy_uj`, a cumulative counter
  per CPU package. Usually root-only.
- **nvml** — NVIDIA's `nvmlDeviceGetTotalEnergyConsumption` (mJ), via ctypes.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from pathlib import Path

SYS = Path("/sys")


class Sensor:
    """One power source. Subclasses give either `watts()` or a cumulative `joules()`."""

    kind = "sensor"
    cumulative = False

    def watts(self) -> float:
        raise NotImplementedError

    def joules(self) -> float:
        raise NotImplementedError


@dataclass
class AmdgpuSensor(Sensor):
    path: Path  # the hwmon power file
    apu: bool = False
    kind = "amdgpu"

    def watts(self) -> float:
        return int(self.path.read_text().strip()) / 1e6


@dataclass
class RaplSensor(Sensor):
    path: Path  # the powercap zone dir
    kind = "rapl"
    cumulative = True

    def joules(self) -> float:
        return int((self.path / "energy_uj").read_text().strip()) / 1e6

    def wrap(self) -> float:
        try:
            return int((self.path / "max_energy_range_uj").read_text().strip()) / 1e6
        except (OSError, ValueError):
            return 0.0


@dataclass
class NvmlSensor(Sensor):
    lib: object
    handle: object
    kind = "nvml"
    cumulative = True

    def joules(self) -> float:
        mj = ctypes.c_ulonglong()
        if self.lib.nvmlDeviceGetTotalEnergyConsumption(self.handle, ctypes.byref(mj)):
            raise OSError("nvmlDeviceGetTotalEnergyConsumption failed")
        return mj.value / 1000

    def wrap(self) -> float:
        return 0.0


def _amdgpu_sensors(root: Path) -> list[AmdgpuSensor]:
    out = []
    for hw in sorted((root / "class/hwmon").glob("hwmon*")):
        try:
            if (hw / "name").read_text().strip() != "amdgpu":
                continue
        except OSError:
            continue
        for name in ("power1_average", "power1_input"):
            p = hw / name
            try:
                int(p.read_text().strip())
            except (OSError, ValueError):
                continue
            # APUs have no board power cap; discrete cards do.
            out.append(AmdgpuSensor(p, apu=not (hw / "power1_cap").exists()))
            break
    return out


def _rapl_sensors(root: Path) -> tuple[list[RaplSensor], str | None]:
    zones = sorted(
        z for z in (root / "class/powercap").glob("intel-rapl:*") if z.name.count(":") == 1
    )
    if not zones:
        return [], None
    sensors = []
    for z in zones:
        try:
            RaplSensor(z).joules()
        except PermissionError:
            return [], (
                f"RAPL is present but root-only: sudo chmod a+r {z.parent}/intel-rapl:*/energy_uj "
                "(resets at boot; a udev rule makes it stick)"
            )
        except (OSError, ValueError):
            continue
        sensors.append(RaplSensor(z))
    return sensors, None


def _nvml_sensors() -> list[NvmlSensor]:
    try:
        lib = ctypes.CDLL("libnvidia-ml.so.1")
    except OSError:
        return []
    try:
        if lib.nvmlInit_v2():
            return []
        count = ctypes.c_uint()
        if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)):
            return []
        out = []
        for i in range(count.value):
            h = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)):
                continue
            s = NvmlSensor(lib, h)
            try:
                s.joules()
            except OSError:
                continue
            out.append(s)
        return out
    except AttributeError:
        return []


@dataclass
class Meter:
    """The sensors that together cover this machine, read as one."""

    sensors: list[Sensor]
    notes: list[str] = field(default_factory=list)
    _last: list[float | None] = field(default_factory=list, repr=False)

    @property
    def name(self) -> str:
        kinds = []
        for s in self.sensors:
            k = "amdgpu-apu" if getattr(s, "apu", False) else s.kind
            if k not in kinds:
                kinds.append(k)
        return "+".join(kinds)

    def joules_since_last(self, dt: float) -> float:
        """Energy since the previous call. Power sensors are integrated over `dt`."""
        if not self._last:
            self._last = [None] * len(self.sensors)
        total = 0.0
        for i, s in enumerate(self.sensors):
            try:
                if s.cumulative:
                    now = s.joules()
                    prev = self._last[i]
                    self._last[i] = now
                    if prev is not None:
                        delta = now - prev
                        if delta < 0:  # counter wrapped
                            delta += s.wrap()
                        total += max(delta, 0.0)
                else:
                    total += s.watts() * dt
            except (OSError, ValueError):
                continue
        return total


def detect(root: Path | None = None, nvml: bool = True) -> tuple[Meter | None, str]:
    """The meter for this machine, or None with the reason it can't be measured."""
    root = root or SYS
    amd = _amdgpu_sensors(root)
    gpus: list[Sensor] = [*amd, *(_nvml_sensors() if nvml else [])]
    if any(s.apu for s in amd):
        meter = Meter(gpus)  # socket power already includes the CPU
        return meter, f"{meter.name} (CPU + GPU socket power)"
    rapl, why = _rapl_sensors(root)
    sensors = [*rapl, *gpus]
    if not sensors:
        return None, why or "no power sensor found (amdgpu, RAPL or NVIDIA)"
    meter = Meter(sensors)
    covered = []
    if rapl:
        covered.append("CPU")
    if gpus:
        covered.append("GPU")
    desc = f"{meter.name} ({' + '.join(covered)})"
    if gpus and not rapl:
        meter.notes.append(why or "CPU power not measured: no RAPL counter")
        desc += f" — {meter.notes[-1]}"
    return meter, desc
