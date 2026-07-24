<p align="center">
  <img src="assets/logo.png" alt="paratext" width="112" height="112">
</p>

<h1 align="center">paratext</h1>

A modular, project-based pipeline that produces metadata from digitised library
& archive collections with a multimodal model. Includes a human-in-the-loop
review tool.

One command (`paratext`) does the whole loop: run a multimodal model over a
directory of images or PDFs, write resumable JSONL with provenance, and package
it into a review dataset. Each **project** is a self-contained module — its own prompt,
output schema, and sample iteration, added without forking the framework — so the
same code path runs a 50-item pilot and a 250,000-item sweep; only `--limit`
differs.

## What you'll need

- **A directory of images or PDFs.** Images are read from a flat directory, one
  item per file; PDFs are read recursively.
- **An OpenAI-compatible endpoint serving a multimodal model.** This is the part
  that takes real setup — paratext calls it, it doesn't provide it. Anything
  speaking the OpenAI chat API works: [Lemonade](https://lemonade-server.ai/),
  vLLM, llama.cpp, or a hosted provider. The model must accept images.
  Point paratext at it with `base-url` (see [Configure](#configure)); it
  defaults to `http://localhost:8000/v1`.
- **Python 3.11–3.13.**

Nothing else. Card cropping needs an extra, but most collections don't use it.

## Install

```bash
uv tool install paratext          # installs the `paratext` command on PATH
```

Image and PDF collections both work out of the box. Scanned index cards can
optionally use a card-cropping detector, which needs the heavier `[detector]`
extra — see [Scanned cards](#scanned-cards-paratextcards); most collections
don't need it.

### Updating

```bash
uv tool upgrade paratext                          # installed as a CLI tool
# or, as a project dependency:
uv lock --upgrade-package paratext && uv sync
```

Your projects live in their own package, so upgrading the framework leaves them
untouched.

## Quickstart

```bash
# 1. Scaffold a project. Asks input type, fields, prompt, offers to write the
#    paratext.toml config (source + endpoint), then registers the entry point in
#    your pyproject.toml and runs `uv sync` — so it's ready to run.
#    (--no-install to just scaffold the files.)
paratext new my-cards

# 2. Check what the project will actually do before spending a model run on it.
paratext inspect -p my-cards

# 3. Run extraction + packaging in one go, then review in the browser.
paratext run -p my-cards --limit 50
paratext review                       # serves ./review — all projects
```

If you skip the guided steps (or aren't in a package), `new` prints the manual
entry-point line to add and the `uv sync` to run. `paratext config` opens
`paratext.toml` later for tweaks (endpoint, model, per-project source).

`run` writes the extraction JSONL and a `review/<project>-r<N>/` dataset
(`samples.json` + `images/` + `view.json`) — the `-r<N>` is the review **round**
(see [Iterating](#iterating-rounds)). `paratext review` opens a local web UI over
the `review/` root. If a review server is already running, a fresh `run` shows up
there on reload — no restart needed. Add `paratext run … --review` to launch the
UI automatically when the run finishes.

`inspect` prints the fields and types the model is asked for, the prompt, the
preprocessing the source adapter applies, and whether schema, prompt and view
still agree — the same information as the review UI's **Project configuration**
page. It describes what is *installed*, so if it disagrees with the files
you're editing, the package needs reinstalling (`uv sync`). That mismatch is the
most common cause of "my change did nothing".

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

Your fields end up named in all three files — schema (structure), prompt
(instructions), and View (display) — with no automatic link between them. Keep
them in step by calling `audit_project(PROJECT)` from a test: it checks every View
field exists in the schema and every model field is named in the prompt. Put
behaviour in `prompt.md`; keep the schema's `Field(description=...)` short and
structural, since those descriptions are sent to the model too and shouldn't
restate the prompt.

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

The homepage also links to **Project configuration**, a read-only view of every
installed project: its fields and types, its prompt, the preprocessing its
source applies, and its audit status. Where a project has already been run, it
compares the
installed prompt against the one that produced the latest packaged round and
diffs them if they differ — so you can see at a glance whether a new run would
reproduce the round you're looking at. It's the browser equivalent of
`paratext inspect`, and works before you've run anything.

### When something looks wrong

- **A run finishes but preprocessing didn't happen.** `run`/`extract` print a
  `!` notice for anything that degraded rather than failed — most often a
  requested card crop falling back to a uniform crop because no detector was
  available. Notices appear at the end of the run; the per-record `metadata` also
  records what was applied.
- **An edit to `schema.py` or `prompt.md` had no effect.** `paratext inspect`
  reports the *installed* project. If it disagrees with your editor, reinstall
  (`uv sync`, or `pip install -e .`). An editable install avoids this; a plain
  install needs reinstalling after every change.
- **A field renamed in one place but not another.** `paratext inspect` runs the
  same audit as `paratext.projects.audit_project`, which checks the view's fields
  exist in the schema and that every model-output field is named in the prompt.
  Call it from your project's tests too — `paratext new` generates that test.
- **Cropping or verso filtering behaves oddly on your scans.** Both are tuned to
  one collection; see [Scanned cards](#scanned-cards-paratextcards).

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

### Build eval set — correcting rows into gold

Scoring alone yields gold only from the rows the model already got right
(*good enough*). The **Build eval set** tab turns the rest into gold too: it
surfaces just the *needs tweaks* / *not accurate* rows and lets you edit the
fields (text, enums as dropdowns, list values, and structured sub-entries with
add/remove) into the correct answer. A saved edit is stored as a **gold label**
in a separate `gold_labels` table — it never changes the model verdict (accuracy
still reflects the model) and never touches the `annotations` table. The editor
edits the fields your project's View shows; fields the View hides keep their model
value. `paratext export` then ships these corrected rows **alongside** the
*good enough* ones as one gold set (see below). The Stats tab reports the eval-set
size (good-enough + corrected).

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

The model endpoint is just an OpenAI-compatible URL, so a hosted API works exactly
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

## Commands

| Command | What it does |
| --- | --- |
| `paratext run -p <project>` | Extract **and** package in one step (the common path). |
| `paratext extract -p <project>` | Run the model, write JSONL only. |
| `paratext package <jsonl>` | Re-package an existing JSONL for review (no model calls). |
| `paratext review <dataset-dir>` | Launch the inbuilt web UI to review a packaged dataset. |
| `paratext export -p <project>` | Export a reviewed round (`--format hf`/`marc`/`dc`). |
| `paratext carbon` | Show the current grid carbon/renewables (for `--green` scheduling). |
| `paratext sample --source <tree> --out <dir> -n 500` | Symlink a random image subset out of a nested tree. |
| `paratext config [--show]` | Open `paratext.toml`; `--show` prints the resolved defaults. |
| `paratext new [name]` | Scaffold a new project package (asks fields, prompt, source). |
| `paratext inspect [-p <project>]` | Show what an installed project does: fields + types, prompt, source options, audit. |

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
  current reading), `--renewables-above PCT`, `--max-carbon GCO2`.
- **`package <jsonl>`** — `-p/--project` (inferred from the JSONL's provenance
  if omitted), `--out DIR` (default: the `review/<project>-r<N>` round for this
  prompt), `--round N`, `--fresh` (rebuild, discarding annotations).
- **`export -p <project>`** — `--format {hf,marc,dc}` (omit → prompt on a terminal,
  hf default); `--round N` (default: latest). HF-only: `--to <org/name>` (else
  `export.repo`), `--public` (default private), `--license <id>` (else prompted; CC0
  recommended), `--dry-run` (build locally, don't push).
- **`review [data_dir]`** — `data_dir` defaults to `./review`; `--port N`
  (config `review-port`, else 5050), `--no-open`.
- **`sample`** — `--source DIR` (required), `--out DIR` (required), `-n N`
  (default 500), `--seed N`.
- **`config`** — `--show` (print resolved defaults instead of editing),
  `-p <project>` (which project's defaults to resolve), `--suggest-region`
  (IP-geolocate and propose a `[carbon]` region).
- **`new [name]`** (alias `init`) — interactive; `--no-install` (scaffold only,
  don't edit pyproject.toml or run `uv sync`).

## Export

Once a round is reviewed, `paratext export -p <project>` turns the human-approved
items (the gold set — see below) into one of three formats via `--format`:

```bash
paratext export -p monographs --format hf     # Hugging Face dataset (ML)
paratext export -p monographs --format marc   # MARCXML catalogue records
paratext export -p monographs --format dc     # Dublin Core (OAI-DC) records
paratext export -p monographs                 # no --format: prompts on a terminal (hf default)
```

**The gold set** is the same for every format: *verified* rows (a reviewer marked
the model output *good enough*) plus *corrected* rows (a reviewer edited the fields
in **Build eval set**). With no corrections made, that's just the *good enough* rows.

### Hugging Face (`--format hf`, the default)

Writes an imagefolder + `metadata.jsonl` with an auto-generated dataset card (schema,
model, prompt, review accuracy) — a training contribution for other institutions and
a benchmark for other models over the same material.

```bash
paratext export -p index-cards --dry-run     # build ./export/<round>/ and inspect
paratext export -p index-cards               # push (private repo)
paratext export -p index-cards --public      # public (see licence steer below)
```

- **Private by default.** `--public` is opt-in.
- **Licence steer, not a gate.** If no `license` is set (in config or via
  `--license`), `export` prompts for one — **CC0-1.0 is recommended for open
  sharing**, or set your own, or leave it blank. Leaving it blank no longer blocks
  publishing; the dataset card just records `license: other`. Image rights remain
  the publisher's call.
- **Gold = human-approved items**, of two kinds, both shipped together:
  *verified* (a reviewer marked the model output *good enough* — the label is that
  output) and *corrected* (a reviewer edited the fields in **Build eval set** — the
  label is the edited output). Each row's `_label_status` says which; corrected
  rows also carry `_corrected_fields`. `_verdict` keeps the original model verdict,
  so accuracy still measures the model.
- HF is single-image only (index-cards); multi-image projects (monographs) are
  rejected — use `--format marc`/`dc` for those.

```toml
[project.index-cards.export]
repo    = "nls-lst/advocates-index-cards"
# HF licence id (canonical, SPDX-like). Recommended: cc0-1.0 (open sharing),
# cc-by-4.0 (attribution), apache-2.0 (code/models). Shorthands like `cc0` are
# accepted and normalised; unrecognised ids get a soft warning.
license = "cc0-1.0"          # else export prompts; CC0 recommended
# min-verdict = "good_enough"  include-negatives = false  annotators = "omit"
```

Auth uses your Hugging Face token (`huggingface-cli login` or `HF_TOKEN`).

### MARC & Dublin Core (`--format marc` / `--format dc`)

Writes catalogue records — a MARCXML `<collection>` (`export/<round>.marcxml`) or an
OAI Dublin Core file (`export/<round>.dc.xml`) — for loading into an ILS / discovery
layer. Plain XML, no extra dependency. Unlike HF, these are metadata-only, so
**multi-image projects like monographs work**.

Each schema field maps to a MARC tag / DC element. Fields with **standard names**
(title, subtitle, author/creator, publisher, place, date, isbn, subject, …) are
inferred automatically — monographs needs no configuration. For any field with a
non-standard name, a **wizard** prompts you for a target (a `TAG$sub` like `500$a`, or
a DC element) and saves your answers so it's asked only once. Unmapped fields are
dropped with a warning, never a hard error.

```toml
# Auto-inferred for standard names; only edit to override or map the unknowns.
# A value of "" means "skip this field" (so the wizard won't ask again).
[project.monographs.export.marc]
title             = "245$a"
personal_authors  = "100$a|700$a"   # first → 100 (main entry), rest → 700 (added)
publisher         = "264$b"
publication_date  = "264$c"
isbn              = "020$a"

[project.monographs.export.dc]
title            = "title"
personal_authors = "creator"
publication_date = "date"
```

## Scanned cards (`paratext.cards`)

For index-card collections, two reusable, **opt-in** tools. Both are off by
default — they are card-specific, and both are calibrated against one
collection's scans, so neither should be trusted on new material without
checking it first.

- **`is_verso(image)`** — a pure-NumPy blank-back filter (no ML dependency) that
  drops the blank backs of cards before any model call. Thresholds are arguments;
  recalibrate them for your scanner. A false positive silently discards a real
  card, so verify against a labelled sample before enabling it on a full run.
- **`load_card_detector()`** — a permissive (BSD) torchvision RetinaNet that
  crops a scan to the card region. Needs the `[detector]` extra
  (`uv tool install "paratext[detector]"`). Falls back to a uniform crop if the
  runtime or the weights are unavailable, and says so in the run summary.

The reference weights are trained on National Library of Scotland catalogue
cards. They are a starting point, not a general-purpose card detector — expect
to train your own. Point paratext at them with:

```toml
[detector]
repo = "your-org/your-card-detector"   # a Hugging Face repo
file = "weights.pt"
# ...or point at a local file instead, e.g. weights you've just trained:
weights = "models/my-card-detector.pt"
```

Resolution order, highest first: the `weights=` argument → the
`PARATEXT_CARD_DETECTOR` environment variable → `weights` in the config above →
downloading `file` from `repo`. The reference weights live at
[`NationalLibraryOfScotland/card-detector-retinanet`](https://huggingface.co/NationalLibraryOfScotland/card-detector-retinanet).

The bundled `card-template` project (`paratext run -p card-template`) is a
worked example — a neutral prompt and a minimal schema to copy and edit. It
leaves both tools off; enable them once you've calibrated for your collection.

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
- The grid region is *declared, not detected* — a box can be reached both locally
  and remotely, so paratext can't infer where compute runs.
  `paratext config --suggest-region` IP-geolocates your box and *proposes* a
  region for you to confirm (it may reflect your ISP/host rather than your site).
- Only meaningful when inference runs on the grid you name (e.g. a local model box).

## Development

Working from a checkout rather than an installed release:

```bash
uv sync --extra dev            # add --extra detector for the card detector
uv run paratext …             # run the CLI against the local source
uv run pytest -q              # tests
uv run ruff check             # lint (line length 100, rules E/F/I/W)
```

## License

Apache-2.0. The card-detector model weights are distributed separately on the
Hugging Face Hub under their own license.
