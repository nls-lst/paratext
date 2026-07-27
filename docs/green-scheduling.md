# Green scheduling (`--green`)

A batch sweep is a movable load, so you can wait for the grid to be clean before
running. `paratext run --green` (or `extract --green`) blocks until renewables
are high enough — or carbon low enough — then proceeds, and records the reading
into provenance so `export` reports it on the dataset card.

```bash
paratext config --suggest-region     # geolocate your box → propose a [carbon] region
paratext carbon                      # what's the grid doing right now?
paratext carbon --window             # greenest window in the next 24h
paratext run -p index-cards --green  # wait for a clean grid, then run
```

Only meaningful when inference runs on the grid you name — a local model box, not
a hosted API in someone else's data centre.

## Configuration

Declare your **grid region**. It matters more than the thresholds: South Scotland
is often ~85% wind against ~35% GB-wide.

```toml
[carbon]
provider = "uk"              # uk (no token, incl. regional + forecast)
region   = "south-scotland"  # DNO region slug/id, or a UK outcode like "EH"
min-renewable = 80           # wait until renewables ≥ 80% (or set max-carbon)
mode = "poll"                # poll, or "window" to schedule to the greenest slot
max-wait = "12h"             # give up waiting and run anyway after this
```

`max-wait` matters: without it a dirty grid blocks the run indefinitely. The
default gives up and runs rather than stalling a batch overnight.

## Providers

| Provider | Token | Coverage | Forecast |
| --- | --- | --- | --- |
| `uk` *(default)* | none | Per-DNO-region | 48h |
| `energy-charts` | none | 20+ EU countries | yes |
| `electricitymaps` | yes | Global | no (free tier) |

- **UK** is uniquely granular — per-region readings *and* a forecast, free and
  unauthenticated. No other country has a direct equivalent at that resolution.
- **energy-charts** (Fraunhofer ISE) gives renewable-share readings and forecast
  at country level: `provider = "energy-charts"`, `zone = "de"`.
- **Electricity Maps** covers everywhere but the free token gives only the latest
  reading, so `mode = "window"` won't work: `provider = "electricitymaps"`, plus
  `zone` and `token`.

## Why the region is declared, not detected

A box can be reached both locally and remotely, so paratext cannot infer where
its compute actually runs. `paratext config --suggest-region` IP-geolocates and
*proposes* a region for you to confirm — the answer may reflect your ISP or
hosting provider rather than your site, so it always asks rather than assuming.
