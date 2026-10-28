# Carbon: energy, emissions and clean-grid runs

paratext measures every local run: how much energy it used, what that emitted on
your grid, and how much of it ran on clean electricity. One command shows the grid
and writes a report you can drop into a sustainability return.

```bash
paratext carbon
```

```
Meter     amdgpu-apu (CPU + GPU socket power)
Grid      South Scotland: 84% renewable, 0 gCO2/kWh, very low
Waiting   on, for ≥70% renewable — runs would go ahead
Forecast  clean for all of the next 48h (84–90% renewable)

Reports   rebuilt from 12 runs
          /path/to/output/carbon/monographs.pdf
          /path/to/output/carbon/runs/monographs-full-c14a23.pdf  (latest run; one per run beside it)
          /path/to/output/carbon/carbon.csv
```

On a day with dirty spells, the forecast names them and adds a chart of the next
48 hours:

```
Forecast  runs would pause 17:00–21:30 and Wed 16:30–20:00 (8h of the next 48h; 50–90% renewable)
          █████████▅▅▅▅▆██████████████████▆▅▅▅████████████
          now 12:00       Wed         12:00       Thu
```

If the grid is dirty right now, the `Waiting` line says when it's due to be clean
again.

There are no subcommands and no options. Every call writes:

- **A run report** for each run, `output/carbon/runs/<run>.docx`: one page with
  the run's energy, emissions, records, energy per record and renewable share;
  where its energy came from (wind, gas and so on); its energy over time, split
  the same way; and how it was measured. A finished run's report is left as it
  is.
- **A project report** for each project, `output/carbon/<project>.docx`: one page
  with the project's totals, energy and emissions by month, energy per record by
  model when there is more than one, and its runs.
- **`output/carbon/carbon.csv`**: one row per run, with project, model, dates,
  records, kWh, Wh per record, gCO₂e, renewable share, clean-grid share, hours
  paused, and how it was measured. Filter it in a spreadsheet for a financial year.

The charts are Word charts, so you can edit them or paste them into a return.
Each report also gets a PDF copy when LibreOffice is installed; without it,
paratext says so and writes the Word files only.

## Configuration

```toml
[carbon]
region = "south-scotland"   # where the compute runs
wait   = true               # pause runs while the grid is dirty (default false)
```

That's all most sites need. `paratext config --suggest-region` proposes a
`[carbon]` block from your IP address for you to confirm.

| Key | Default | What it does |
| --- | --- | --- |
| `region` | GB national | UK grid region: a slug (`south-scotland`), DNO id, or outcode (`EH`) |
| `wait` | `false` | Pause between records while renewables are below `min-renewable` |
| `min-renewable` | `70` | The clean-grid threshold, in percent |
| `provider` | `uk` | `uk`, `energy-charts` (EU, no token) or `electricitymaps` (token) |
| `zone` | — | Country or zone for `energy-charts` / `electricitymaps` (`de`, `FR`) |
| `token` | — | Electricity Maps token; prefer `PARATEXT_CARBON_TOKEN` |
| `overhead` | `1.0` | Multiplies measured energy to cover what the sensor can't see |

For a single run, `PARATEXT_CARBON_WAIT=false` turns waiting off.

**Without a `[carbon]` table** runs are still measured, but emissions aren't
computed: paratext doesn't know which grid you're on and won't guess.

## Measuring energy

A background thread reads the machine's power sensors every 10 seconds while a run
is going. The sensor is picked automatically:

| Meter | Source | Covers |
| --- | --- | --- |
| `amdgpu-apu` | amdgpu hwmon on an APU (socket power) | CPU + GPU |
| `amdgpu` | amdgpu hwmon on a discrete card | that GPU |
| `rapl` | `/sys/class/powercap/intel-rapl:*/energy_uj` | CPU package(s) |
| `nvml` | NVIDIA NVML energy counter | that GPU |

On a machine with a separate CPU and GPU, the meters are added together
(`rapl+nvml`). RAPL is usually readable by root only; `paratext carbon` prints the
command that opens it up.

**Not measured, never estimated.** A run is recorded as *not measured*, with its
records but no energy, when:

- the model runs on a hosted endpoint (any `base-url` that isn't this machine's
  loopback address), because this machine's sensors can't see it; or
- the machine has no readable sensor.

**Overhead.** Sensors see the processor, not disks, fans or power-supply losses.
If your site applies a factor for those, set `overhead`; it's recorded with every
run and shown in the report.

## Emissions

Emissions are **location-based**: energy in each grid interval (30 minutes for the
UK, 15 for energy-charts) multiplied by that interval's carbon intensity for your
zone. UK regional figures are forecasts; the CSV's `intensity_basis` says which
kind was used. energy-charts gives renewable share but not intensity, so with that
provider runs report energy and renewable share, and no emissions.

Region matters more than anything else: South Scotland is often ~85% wind against
~35% GB-wide.

## Waiting for a clean grid

With `wait = true`, the run checks the grid between records, once per interval.
While renewables are below `min-renewable` it finishes the current record and
pauses, then carries on when the grid is clean again. A single pause gives up after
12 hours and carries on regardless, so a batch can't stall for days. Pauses are
recorded and shown shaded in the report's timeline.

Waiting only applies to local runs: holding back a hosted run doesn't change which
grid powers it.

## Where the figures live

Each run keeps a summary file in `output/carbon/runs/`, one per output JSONL. Each
session of a resumed run adds a segment, and the file is rewritten as the run goes,
so a killed run loses at most one interval. `paratext package` copies a run's
totals into the round, and `paratext export` puts them on the dataset card.

## Providers

| Provider | Token | Coverage | Intensity | Forecast |
| --- | --- | --- | --- | --- |
| `uk` *(default)* | none | Per-DNO-region | yes | 48h |
| `energy-charts` | none | 20+ EU countries | no | yes |
| `electricitymaps` | yes | Global | yes | no (free tier) |

## Why the region is declared, not detected

A box can be reached both locally and remotely, so paratext cannot infer where its
compute actually runs. `paratext config --suggest-region` IP-geolocates and
*proposes* a region for you to confirm: the answer may reflect your ISP or hosting
provider rather than your site, so it always asks rather than assuming.
