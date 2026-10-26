# Design: carbon — energy, emissions and clean-grid runs

Status: built (2026-10-26). User docs: [carbon.md](../carbon.md). Tracked in helical as PTX-71 (measure and report)
and PTX-72 (wait for a clean grid).

## Why

Libraries we've spoken to want to show figures in their sustainability reporting:
how much energy a batch used, what it emitted, and how much of the work ran on a
clean grid. Today `--green` only decides when a run starts, and reports nothing
anyone can cite.

We'll ship our own report format first and offer it as an example. We'll adjust it
once other libraries tell us what their reporting needs.

## Principles

- **Simple and opinionated.** One command, one config table, sensible defaults.
  Nobody should need a flag to get good behaviour.
- **On by default.** Every local run is measured. Measuring is cheap and only
  reads sensors, and a report is only useful if the data was collected before
  anyone thought to ask for it.
- **Measured or nothing.** Figures come from sensors. Where there's no sensor (a
  hosted API, a machine without power readings), the report says
  `not measured`. It never estimates.

## User-facing surface

```
paratext carbon
```

One command, no subcommands and no options. Each time it runs, it:

1. **Prints the grid**: renewables and intensity now, the forecast where the
   provider has one, whether a run would wait right now, and which power meter
   this machine would use (or why none can be).
2. **Writes the report** from every run's sidecar: `output/carbon/carbon.csv`,
   plus `output/carbon/carbon.html` with the graphs. It then prints the path to
   the HTML file.

The report is cheap to rebuild from the sidecars, so it's always regenerated in
full. There's nothing to filter: the CSV has a row per run with its dates, so a
financial year or a single project is a spreadsheet filter, and the graphs cover
everything.

```toml
[carbon]
region = "south-scotland"   # where the compute runs; `paratext config --suggest-region` proposes one
wait   = true               # pause the run while the grid is dirty (default false)
```

That's the whole interface. `run` and `extract` get no carbon flags. A one-off
override goes through the usual env-var route (`PARATEXT_CARBON_WAIT=false`).

**Removed:** `--green`, `--renewables-above` and `--max-carbon` on `run`/`extract`,
all `carbon` options (`--window`, `--renewables-above`, `--max-carbon`), and the `mode`, `max-wait`, `poll`, `window-hours`,
`window-run-hours` and `max-carbon` settings. There's no deprecation period. The
release notes and workshop instructions change in the same release.

**Kept but rarely needed:**

- `provider`, `zone`, `token`: needed outside the UK. `provider` defaults to `uk`.
- `min-renewable`: the clean-grid threshold, default 70.
- `overhead`: covers power the sensor can't see, default 1.0. See below.

### Why one threshold

Renewable share is the one signal every provider gives (`uk`, `energy-charts`,
`electricitymaps`). Carbon intensity isn't available from energy-charts.
`min-renewable` decides when to wait. Reported emissions still use carbon
intensity wherever the provider has it.

### Why `wait` is on/off

The old modes (start-only, poll, greenest window) were three answers to one
question. With `wait = true`, the run checks the grid between records, once per
provider interval (30 min for the UK), and pauses while renewables are below the
threshold. That covers all three:

- **Start-only** was a weaker version of the same thing.
- **Greenest window** was a guess made before the run. Pausing reacts to the grid
  as it is.
- **Poll** is now just how waiting works.

A pause is capped at 12 hours, after which the run carries on and the report
records that it ran on a dirty grid. The cap is a built-in default, not a setting.
It stops an overnight batch stalling for days. The time spent paused is reported.

## How it works

### Measuring energy

While a local run is going, a background sampler reads power and adds up energy.
The meter is chosen automatically, from the first source that works:

| Meter | Source | Notes |
| --- | --- | --- |
| `amdgpu` | hwmon `power1_average` (PPT) | AMD APUs and GPUs. Covers CPU + GPU on an APU. No root needed. |
| `rapl` | `/sys/class/powercap/intel-rapl:*/energy_uj` | Intel and AMD CPUs. Usually root-only; `paratext carbon` says how to grant read access. |
| `nvml` | NVIDIA NVML | Per-GPU energy counter. |

- A meter that reads total energy (RAPL, NVML) is used as-is. Others are sampled every 10 s.
- `paratext carbon` shows which meter will be used, or why none can be.
- **No meter means `not measured`.** There's no fixed-wattage fallback. It would
  be an estimate, and we've decided not to report estimates.
- **Hosted endpoints are `not measured`.** A run whose `base-url` isn't this
  machine's loopback address records its records and duration, and leaves energy
  and carbon empty. A LAN address is another machine, so it isn't measured either.
- **Overhead.** Sensors only see the chip. They miss disks, fans, power-supply
  losses, and RAM unless it's on-package. `overhead` multiplies what was measured,
  defaulting to 1.0. The report always shows the value used, so a site that
  applies a factor says so.

### Turning energy into emissions

Energy is bucketed by the grid's own intervals, and each bucket is multiplied by
that interval's intensity:

```
gCO2e = Σ (kWh in interval × gCO2/kWh for interval)
```

- Accounting is **location-based**: the local grid's average intensity, as most
  public-sector reporting uses. The report states this.
- UK regional figures are forecasts. The report records `intensity_basis` for each interval.
- The renewable share is a kWh-weighted average across the run.

### Where the figures live

Each output gets a sidecar in `output/carbon/runs/`, named after the output plus a
short hash of its path. They live together so the report finds every run, wherever
its output was written. It's a separate file because the provenance header is
written once and never changes. Every session of
a resumed run adds a segment, so stopping and restarting loses nothing:

```json
{
  "schema": "paratext-carbon/1",
  "output": "output/monographs-full.jsonl",
  "project": "monographs",
  "model": "Qwen3.6-35B-A3B-GGUF-Q8_0",
  "endpoint": "local",
  "segments": [
    {
      "start": "2026-10-27T09:00:00Z",
      "end": "2026-10-27T21:00:00Z",
      "records": 5600,
      "meter": "amdgpu",
      "overhead": 1.0,
      "wh": 1310.4,
      "gco2e": 3.1,
      "renewable_fraction": 0.88,
      "intensity_basis": "forecast",
      "zone": "South Scotland",
      "paused_s": 0
    }
  ]
}
```

A hosted-endpoint segment has `"meter": null`, and `wh` and `gco2e` are `null`.

### The report

`paratext carbon` rebuilds both files from the sidecars every time it runs.

**`carbon.csv`** has one row per run: project, output, model, start, end, records,
kWh, Wh per record, gCO2e, renewable share, hours paused, meter (or
`not measured`), overhead, intensity basis. Unmeasured runs are included, with
empty energy and emissions, so the record of work stays complete.

**`carbon.html`** is a single self-contained page: inline SVG, no scripts from
the network, readable offline, and printable straight into a report. It works in
light and dark mode. It shows:

- **Headline figures**: total kWh, gCO2e, records, and the share of work done on a clean grid.
- **Energy and emissions by month**, stacked by project.
- **Wh per record** by project and model, which shows which setups are efficient.
- **Latest run timeline**: power draw against grid renewables, with pauses shaded.
- **Method**: meter, overhead, location-based accounting, forecast or actual
  intensity, and what `not measured` means. It's written so it can be quoted as-is.

It's drawn without a plotting library, so the base install stays small.

The method is also written up in `docs/green-scheduling.md` (renamed
`docs/carbon.md`). `hf_export` puts the run totals on the dataset card, replacing
today's single reading.

## Build order

1. **PTX-71: measure and report.** Sampler and meters, per-interval emissions,
   sidecar, and `paratext carbon` printing the grid and writing the CSV + HTML
   report. Remove `--green` and the old settings.
2. **PTX-72: wait.** Grid checks between records, pausing, the 12 h cap, `paused_s`.

Development happens in a git worktree. `paratext-nls` imports `/opt/paratext` as
an editable install, so edits to the main checkout reach any run that's already going.

## End-to-end test

The full born-digital run (18,242 records: monographs and scot gov monographs) was
started on 2026-10-26, then stopped and discarded after 131 records, so that it can
be the first real run of this feature. Run it from scratch once both cards land, with:

```toml
[carbon]
region = "south-scotland"
wait   = true
```

Expected: one sidecar per output, a segment for each session, and a
`paratext carbon` report covering both outputs. For a sanity check, the stopped run
drew about 110 W on the APU (around 120 W under load), so expect roughly 4–5 kWh
for the whole job.
