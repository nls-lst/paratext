"""Measure a run while it happens: energy, emissions, and pauses for a dirty grid.

Every `extract` gets a Tracker. A background thread reads the power meter every
few seconds and buckets energy by the grid provider's own interval, fetching the
intensity once per interval. Each session of a run is one *segment* in a sidecar
under `output/carbon/runs/`, rewritten as it goes, so a killed run loses at most
one interval. `paratext carbon` builds its report from those sidecars.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import carbon, meters

logger = logging.getLogger(__name__)

RUNS_DIR = Path("output/carbon/runs")
SCHEMA = "paratext-carbon/1"
SAMPLE_S = 10.0
MAX_PAUSE_S = 12 * 3600

_LOOPBACK = ("localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0")


def is_local(base_url: str) -> bool:
    """True when the model runs on this machine, so this machine's sensors see it."""
    host = base_url.split("://")[-1].split("/")[0]
    if host.startswith("["):
        host = host[: host.find("]") + 1]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host in _LOOPBACK or host.startswith("127.")


def sidecar_path(output: Path, runs_dir: Path | None = None) -> Path:
    digest = hashlib.sha1(str(Path(output).resolve()).encode()).hexdigest()[:6]
    return (runs_dir or RUNS_DIR) / f"{Path(output).stem}-{digest}.json"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_sidecar(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def totals(seg: dict) -> dict:
    """A segment's headline figures from its intervals (overhead applied)."""
    ivs = seg.get("intervals") or []
    if seg.get("meter") is None:
        return {"wh": None, "gco2e": None, "renewable_fraction": None, "intensity_basis": None}
    k = seg.get("overhead", 1.0)
    wh = sum(i["wh"] for i in ivs) * k
    priced = [i for i in ivs if i.get("gco2_per_kwh") is not None]
    gco2e = sum(i["wh"] / 1000 * i["gco2_per_kwh"] for i in priced) * k if priced else None
    rated = [i for i in ivs if i.get("renewable_fraction") is not None and i["wh"] > 0]
    rated_wh = sum(i["wh"] for i in rated)
    renew = sum(i["wh"] * i["renewable_fraction"] for i in rated) / rated_wh if rated_wh else None
    bases = {i.get("basis") for i in priced if i.get("basis")}
    basis = bases.pop() if len(bases) == 1 else ("mixed" if bases else None)
    return {
        "wh": round(wh, 3),
        "gco2e": round(gco2e, 3) if gco2e is not None else None,
        "renewable_fraction": round(renew, 4) if renew is not None else None,
        "intensity_basis": basis,
    }


class Tracker:
    """One session of one run. Use as a context manager around the sample loop."""

    def __init__(
        self,
        output: Path,
        *,
        project: str,
        model: str,
        base_url: str,
        cfg: carbon.CarbonConfig | None = None,
        meter: meters.Meter | None = None,
        meter_note: str | None = None,
        runs_dir: Path | None = None,
        sample_s: float = SAMPLE_S,
        clock=time.time,
        sleep=time.sleep,
        reading_fn=None,
        log=print,
    ):
        self.cfg = cfg or carbon.load_config()
        self.local = is_local(base_url)
        if meter is None and meter_note is None and self.local:
            meter, meter_note = meters.detect()
        self.meter = meter if self.local else None
        if not self.local:
            meter_note = "hosted endpoint — this machine's sensors can't see it"
        self.path = sidecar_path(output, runs_dir)
        self.sample_s = sample_s
        self.clock, self.sleep, self.log = clock, sleep, log
        self.reading_fn = reading_fn or carbon.current_reading
        self._lock = threading.RLock()  # tick → new interval → grid reading re-enters
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._readings: dict[int, carbon.Reading | None] = {}
        self._grid_error_logged = False
        self._last_t = 0.0
        self._minute: list[float] = []  # [minute_start, joules, seconds]
        self.doc = load_sidecar(self.path) or {
            "schema": SCHEMA,
            "output": str(output),
            "project": project,
            "model": model,
            "segments": [],
        }
        self.doc.update(project=project, model=model)
        self.seg = {
            "start": None,
            "end": None,
            "records": 0,
            "endpoint": "local" if self.local else "hosted",
            "meter": self.meter.name if self.meter else None,
            "meter_note": meter_note,
            "overhead": self.cfg.overhead,
            "provider": self.cfg.provider if self.cfg.declared else None,
            "zone": None,
            "min_renewable": self.cfg.min_renewable,
            "wait": self.cfg.wait,
            "paused_s": 0.0,
            "pauses": [],
            "intervals": [],
            "timeline": [],
        }

    # ── grid ──────────────────────────────────────────────────────────────
    def _bucket(self, t: float) -> int:
        p = self.cfg.period_minutes * 60
        return int(t // p * p)

    def _reading(self, bucket: int) -> carbon.Reading | None:
        if not self.cfg.declared:
            return None
        with self._lock:
            if bucket in self._readings:
                return self._readings[bucket]
        try:
            r = self.reading_fn(self.cfg)
        except (Exception, SystemExit) as e:  # never stop a run over the grid API
            r = None
            if not self._grid_error_logged:
                self.log(f"carbon: grid reading failed ({e}); emissions for this "
                         f"interval won't be counted")
                self._grid_error_logged = True
        with self._lock:
            self._readings[bucket] = r
            if r is not None:
                self.seg["zone"] = r.zone
        return r

    def _interval(self, bucket: int) -> dict:
        ivs = self.seg["intervals"]
        if ivs and ivs[-1]["_b"] == bucket:
            return ivs[-1]
        r = self._reading(bucket)
        iv = {
            "_b": bucket,
            "from": _iso(bucket),
            "wh": 0.0,
            "gco2_per_kwh": r.carbon_gco2 if r else None,
            "renewable_fraction": r.renewable_fraction if r else None,
            "basis": r.basis if r else None,
        }
        ivs.append(iv)
        if len(ivs) > 1:
            self.flush()
        return iv

    # ── sampling ──────────────────────────────────────────────────────────
    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        dt = now - self._last_t
        self._last_t = now
        if self.meter is None or dt <= 0:
            return
        j = self.meter.joules_since_last(dt)
        with self._lock:
            iv = self._interval(self._bucket(now - dt))  # the period the sample covered
            iv["wh"] += j / 3600
            m0 = now // 60 * 60
            if self._minute and self._minute[0] != m0:
                self._close_minute()
            if not self._minute:
                self._minute = [m0, 0.0, 0.0]
            self._minute[1] += j
            self._minute[2] += dt

    def _close_minute(self) -> None:
        m0, j, s = self._minute
        if s > 0:
            self.seg["timeline"].append([_iso(m0), round(j / s, 1)])
        self._minute = []

    def _loop(self) -> None:
        while not self._stop.wait(self.sample_s):
            try:
                self.tick()
            except Exception as e:  # a sensor glitch must not kill the run
                logger.debug("carbon sample failed: %s", e)

    # ── waiting ───────────────────────────────────────────────────────────
    def wait_if_dirty(self) -> None:
        """Pause while the grid is below the threshold (`[carbon] wait = true`)."""
        if not (self.cfg.wait and self.cfg.declared and self.local):
            return
        start = self.clock()
        r = self._reading(self._bucket(start))
        if r is None or self.cfg.is_clean(r):
            return
        self.log(f"carbon: grid below {self.cfg.target_str()} ({r.summary()}); pausing")
        while True:
            now = self.clock()
            waited = now - start
            if waited >= MAX_PAUSE_S:
                self.log("carbon: paused 12h — carrying on although the grid is still dirty")
                break
            p = self.cfg.period_minutes * 60
            nxt = self._bucket(now) + p + 5
            self.sleep(max(1.0, min(nxt - now, MAX_PAUSE_S - waited)))
            r = self._reading(self._bucket(self.clock()))
            if r is None or self.cfg.is_clean(r):
                self.log(f"carbon: grid clean again ({r.summary() if r else 'no reading'})")
                break
        end = self.clock()
        with self._lock:
            self.seg["paused_s"] += end - start
            self.seg["pauses"].append([_iso(start), _iso(end)])

    # ── lifecycle ─────────────────────────────────────────────────────────
    def record(self, n: int = 1) -> None:
        with self._lock:
            self.seg["records"] += n

    def start(self) -> Tracker:
        now = self.clock()
        self.seg["start"] = _iso(now)
        self.doc["segments"].append(self.seg)
        self._last_t = now
        if self.meter is not None:
            self.meter.joules_since_last(0)  # prime cumulative counters
            self._interval(self._bucket(now))
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        self.flush()
        return self

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.sample_s + 5)
        if self.meter is not None:
            self.tick()
            with self._lock:
                if self._minute:
                    self._close_minute()
        self.flush()
        return totals(self.seg)

    def flush(self) -> None:
        seg = self.seg
        seg["end"] = _iso(self.clock())
        seg.update(totals(seg))
        doc = json.loads(json.dumps(self.doc, default=str))
        for s in doc["segments"]:
            for iv in s.get("intervals", []):
                iv.pop("_b", None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1))
        tmp.replace(self.path)

    def __enter__(self) -> Tracker:
        return self.start()

    def __exit__(self, *exc) -> None:
        t = self.stop()
        if self.meter is None:
            self.log(f"carbon: not measured ({self.seg['meter_note']})")
            return
        wh = t["wh"]
        bits = [f"{wh / 1000:.2f} kWh" if wh >= 1000 else f"{wh:.1f} Wh"]
        if t["gco2e"] is not None:
            bits.append(f"{t['gco2e']:.1f} gCO2e")
        if self.seg["paused_s"]:
            bits.append(f"paused {self.seg['paused_s'] / 3600:.1f}h")
        self.log(f"carbon: {', '.join(bits)} — `paratext carbon` for the report")
