# paratext

A small, plugin-based pipeline for extracting catalogue metadata from digitised
library and archive collections with a vision-language model (VLM), then
packaging the results for human review.

One command (`paratext`) does the whole loop: run a VLM over a directory of
images or PDFs, write resumable JSONL with provenance, and package it into a
review dataset. Each **project** is a plug-in — its own prompt, output schema,
and sample iteration — so the same code path runs a 50-item pilot and a
250,000-item sweep; only `--limit` differs.

## Install

```bash
uv tool install paratext          # installs the `paratext` command on PATH
uv tool install "paratext[cards]" # + torchvision RetinaNet card cropping (optional)
```

Image and PDF collections both work out of the box; the `[cards]` extra only
adds the (heavier) card-cropping detector.

The VLM endpoint is any OpenAI-compatible server (e.g. Lemonade, vLLM,
llama.cpp). The base URL defaults to `http://localhost:8000/v1`; override it in
`paratext.toml` or via `PARATEXT_BASE_URL`. Set `api-key` if your endpoint
requires one (see Configure).

## Quickstart

```bash
# 1. Scaffold a project (asks about input type, verso filter, card cropping).
paratext new my-cards

# 2. Register it (add the printed entry-point line to your pyproject.toml, then
#    reinstall) and point the config at your data.
paratext config                       # opens paratext.toml in $EDITOR

# 3. Run extraction + packaging in one go, then review in the browser.
paratext run -p my-cards --limit 50
paratext review                       # serves ./review — all projects
```

`run` writes the extraction JSONL and a `review/<project>-r<N>/` dataset
(`samples.json` + `images/` + `view.json`) — the `-r<N>` is the review **round**
(see [Iterating](#iterating-rounds)). `paratext review` opens a local web UI over
the `review/` root. If a review server is already running, a fresh `run` shows up
there on reload — no restart needed. Add `paratext run … --review` to launch the
UI automatically when the run finishes.

## Commands

| Command | What it does |
| --- | --- |
| `paratext run -p <project>` | Extract **and** package in one step (the common path). |
| `paratext extract -p <project>` | Run the VLM, write JSONL only. |
| `paratext package <jsonl>` | Re-package an existing JSONL for review (no VLM calls). |
| `paratext review <dataset-dir>` | Launch the inbuilt web UI to review a packaged dataset. |
| `paratext export -p <project>` | Publish a reviewed round as a Hugging Face dataset. |
| `paratext carbon` | Show the current grid carbon/renewables (for `--green` scheduling). |
| `paratext sample --source <tree> --out <dir> -n 500` | Symlink a random image subset out of a nested tree. |
| `paratext config [--show]` | Open `paratext.toml`; `--show` prints the resolved defaults. |
| `paratext new [name]` | Scaffold a new project package (asks fields, prompt, source). |

Run `paratext`, `paratext help`, or `paratext <command> -h` for usage.

### Flags

Most `run`/`extract` values resolve from `paratext.toml` (see Configure), so you
rarely pass them — but every default can be overridden on the CLI.

- **`run -p <project>`** — `--source DIR`, `--output FILE` (default
  `output/<project>.jsonl`), `--model ID`, `--base-url URL`, `--api-key KEY`,
  `--limit N`, `--no-structured`, `--skip-preflight`, `--green` (wait for a clean
  grid; see below), `--review-out DIR` (overrides round auto-naming), `--round N`
  (force a round), `--fresh` (rebuild the round, discarding its annotations),
  `--review` (open the UI when finished).
- **`extract -p <project>`** — same as `run` minus the review flags
  (writes JSONL only); includes `--green`.
- **`carbon`** — `--window` (show the greenest forecast window instead of the
  current reading), `--renewables-above PCT`, `--max-carbon GCO2`,
  `--max-percent PCT` (WattTime).
- **`package <jsonl>`** — `-p/--project` (inferred from the JSONL's provenance
  if omitted), `--out DIR` (default: the `review/<project>-r<N>` round for this
  prompt), `--round N`, `--fresh` (rebuild, discarding annotations).
- **`export -p <project>`** — `--to <org/name>` (else `export.repo` in config),
  `--round N` (default: latest), `--public` (default private; needs a license),
  `--dry-run` (build locally, don't push).
- **`review [data_dir]`** — `data_dir` defaults to `./review`; `--port N`
  (config `review-port`, else 5050), `--no-open`.
- **`sample`** — `--source DIR` (required), `--out DIR` (required), `-n N`
  (default 500), `--seed N`.
- **`config`** — `--show` (print resolved defaults instead of editing),
  `-p <project>` (which project's defaults to resolve), `--suggest-region`
  (IP-geolocate and propose a `[carbon]` region).
- **`new [name]`** (alias `init`) — interactive; no flags.

## Review

`paratext review` serves a dependency-free local web app (stdlib only) for human
review: it reads `samples.json` + `view.json` + `images/`, renders the fields and
verdict hotkeys from the view contract, and saves annotations to
`annotations.db`. With no argument it serves the `./review` root and lists every
project on its homepage; pass a directory to review a single dataset (datasets in
subdirs may use `-r<N>` round suffixes). Datasets are re-read per request, so a
new `run` appears on reload without restarting the server.

Once a project is configured, `run`/`extract` need only `-p <project>` —
everything else resolves from config.

<a id="iterating-rounds"></a>

### Iterating: rounds & prompt feedback

Extraction quality lives almost entirely in the prompt, so the workflow is a
loop: run → review → edit the prompt → run again. A **round** captures one prompt
version. The round is keyed on the prompt's hash (not `schema_version` — the
prompt is what you iterate), and `run` names each dataset `review/<project>-r<N>`:

- **Edit `prompt.md`, then `run` again → a new round** (`-r2`, `-r3`, …). The
  review UI shows the two most recent rounds side by side and highlights what
  changed, so you can see whether an edit helped.
- **Re-run the *same* prompt** (a crash resume, or more `--limit`) → the current
  round is **updated in place**, keeping the annotations you've already made.
- Rounds are a linear history: reverting to an earlier prompt still starts a new
  round. Force one with `--round N`; `--fresh` rebuilds a round from scratch
  (discarding its annotations).

Reading feedback back into the prompt: each round's `annotations.db` (a SQLite
file in the dataset dir) holds every reviewer verdict and free-text note. While
the server runs, `GET /api/stats` gives the round's accuracy and verdict counts,
and `GET /api/export/<id>` returns a CSV of scored/flagged samples with notes.
Query the db (or those endpoints), see where the model struggles, and tighten
those parts of `prompt.md` before the next round.

## Export to Hugging Face

Once a round is reviewed, `paratext export -p <project>` turns the
human-approved items into a Hugging Face dataset — a training contribution for
other institutions and a benchmark for other models over the same material. It
reuses the round's images and writes an imagefolder + `metadata.jsonl` with an
auto-generated dataset card (schema, model, prompt, review accuracy).

```bash
paratext export -p index-cards --dry-run     # build ./export/<round>/ and inspect
paratext export -p index-cards               # push (private repo)
paratext export -p index-cards --public      # public — requires a license (below)
```

- **Private by default.** `--public` is opt-in and is **refused without a
  `license`** set in config — no accidental publishing, and image rights are the
  publisher's call.
- **Gold = approved items.** Only items a reviewer marked *good enough* become
  labelled rows (the label is the verified model output); *needs tweaks* /
  *not accurate* items carry their note but aren't labels. (Structured per-field
  corrections, which would promote *needs tweaks* to gold, are a planned review
  feature.)
- Single-image projects (index-cards) are supported; multi-image projects
  (monographs) are rejected for now.

Configure per project:

```toml
[project.index-cards.export]
repo    = "nls-lst/advocates-index-cards"
license = "cc-by-4.0"        # required before any --public push
# min-verdict = "good_enough"  include-negatives = false  annotators = "omit"
```

Auth uses your Hugging Face token (`huggingface-cli login` or `HF_TOKEN`).

## Green scheduling (`--green`)

A batch sweep is a movable load, so you can wait for the grid to be clean before
running. `paratext run --green` (or `extract --green`) blocks until renewables
are high enough (or carbon low enough), then proceeds — and records the reading
into provenance so `export` reports it on the dataset card.

```bash
paratext config --suggest-region    # geolocate your box → propose a [carbon] region
paratext carbon                     # what's the grid doing right now?
paratext carbon --window            # greenest window in the next 24h
paratext run -p index-cards --green # wait for a clean grid, then run
```

Configure a `[carbon]` block (thresholds and, importantly, your **grid region** —
far more precise than national; South Scotland is often ~85% wind vs ~35%
GB-wide):

```toml
[carbon]
provider = "uk"              # uk (no token, incl. regional + forecast)
region   = "south-scotland"  # DNO region slug/id, or a UK outcode like "EH"
min-renewable = 80           # wait until renewables ≥ 80% (or set max-carbon)
mode = "poll"                # poll, or "window" to schedule to the greenest slot
max-wait = "12h"             # give up waiting and run anyway after this
```

- **UK** (default) needs no token and is uniquely granular — per-DNO-region
  readings *and* a 48h forecast, free and unauthenticated. No other country has a
  direct equivalent at that resolution.
- **energy-charts** (`provider = "energy-charts"`, `zone = "de"`) — Fraunhofer
  ISE, **no token**, renewable-share readings *and* forecast for 20+ EU countries
  (country-level).
- **Electricity Maps** (`provider = "electricitymaps"`, `zone`, `token`) — global
  coverage; latest reading only on the free token.
- **WattTime** (`provider = "watttime"`, `region`, `username`/`password`) — US +
  global; gates on the marginal-emissions percentile (`max-percent`, "run in the
  cleanest third") rather than renewables. Needs a free watttime.org account.
- The grid region is *declared, not detected* — a box can be reached both locally
  and remotely, so paratext can't infer where compute runs.
  `paratext config --suggest-region` IP-geolocates your box and *proposes* a
  region for you to confirm (it may reflect your ISP/host rather than your site).
- Only meaningful when inference runs on the grid you name (e.g. a local VLM box).

## Configure

A `paratext.toml` in the working directory holds defaults. Resolution order,
highest priority first:

1. CLI flags (`--source`, `--model`, …)
2. `PARATEXT_*` environment variables (idiomatic inside containers)
3. `[project.<name>]` section in `paratext.toml`
4. top-level keys in `paratext.toml`

Keys may be kebab- or snake-case:

```toml
base-url = "http://localhost:8000/v1"
model    = "Qwen3-VL-30B"

[project.my-cards]
source     = "/data/my-cards/images"
output     = "output/my-cards.jsonl"
review-out = "review/my-cards"

[project.my-cards.preprocess]
verso-filter = true
card-crop    = true
```

### Remote / hosted endpoints (incl. Hugging Face)

The VLM endpoint is just an OpenAI-compatible URL, so a hosted API works exactly
like a local server — only `base-url`, `api-key`, and `model` change. For example,
Hugging Face Inference Providers (or a dedicated Inference Endpoint's URL + `/v1`):

```toml
base-url = "https://router.huggingface.co/v1"
api-key  = "hf_…"                          # or set PARATEXT_API_KEY
model    = "Qwen/Qwen2.5-VL-7B-Instruct"   # a vision model repo id
```

Two things to know for hosted endpoints:

- **Auth:** set `api-key` to your provider token (local servers ignore it; the
  default is `EMPTY`).
- **Structured output:** extraction uses OpenAI json-schema structured outputs by
  default. If a provider/model doesn't support that, set `no-structured = true`
  (or pass `--no-structured`) to fall back to a plain completion + JSON parsing.

paratext is a *client*, not a model runner — to use a model that isn't hosted,
self-host it behind vLLM/TGI/llama.cpp and point `base-url` at that.

## Scanned-card toolkit (`paratext.cards`)

For index-card collections, two reusable, opt-in tools:

- **`is_verso(image)`** — a pure-NumPy blank-back filter (no ML dependency) that
  drops the blank backs of cards before any VLM call. Thresholds are arguments;
  recalibrate them for your scanner.
- **`load_card_detector()`** — a permissive (BSD) torchvision RetinaNet that
  crops a scan to the card region. Weights download from the Hugging Face Hub on
  first use; needs the `[cards]` extra. Falls back to a uniform crop if
  unavailable.

The bundled `cards` project (`paratext run -p cards`) wires both to a neutral
prompt and a minimal schema as a working starting point.

## Writing a project

`paratext new` scaffolds a project package for you — the three files you then
edit are the prompt, the schema, and a short wiring file:

```
my_cards/
    prompt.md     # the prompt (prose, for the model)
    schema.py     # the Pydantic output schema (your metadata fields)
    __init__.py   # wires schema + prompt + a source adapter into PROJECT
```

`__init__.py` is small because the input handling comes from a **source
adapter** (`paratext.sources`):

```python
# my_cards/__init__.py
from paratext.projects import Project, load_prompt
from paratext.sources import image_source   # or pdf_source

from .schema import Record

PROJECT = Project(
    name="my-cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=Record,
    source=image_source(verso_filter=True, crop=True),
)
```

Register it via the `paratext.projects` entry-point group so it's discovered at
runtime:

```toml
[project.entry-points."paratext.projects"]
my-cards = "my_cards:PROJECT"
```

The View defaults to showing every schema field. Override only what you need:
pass a `view=View(...)` to curate the display, and the optional hooks `curate`,
`build_record`, `ground_truth` (and a custom `materialise_images` or
`iter_samples`) for drop/quarantine rules, ground truth, etc.

## Development

Working from a checkout rather than an installed release:

```bash
uv sync --extra dev            # add --extra cards for the detector runtime
uv run paratext …             # run the CLI against the local source
uv run pytest -q              # tests
uv run ruff check             # lint (line length 100, rules E/F/I/W)
```

## License

Apache-2.0. The card-detector model weights are distributed separately on the
Hugging Face Hub under their own license.
