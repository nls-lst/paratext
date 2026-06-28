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
# optional extras:
uv tool install "paratext[cards]" # torchvision RetinaNet card cropping
uv tool install "paratext[pdf]"   # pypdfium2 PDF page rendering
```

For development from a checkout: `uv sync --extra dev` and run with
`uv run paratext …`.

The VLM endpoint is any OpenAI-compatible server (e.g. Lemonade, vLLM,
llama.cpp). The base URL defaults to `http://localhost:8000/v1`; override it in
`paratext.toml` or via `PARATEXT_BASE_URL`. No API key is required for local
servers.

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

`run` writes the extraction JSONL and a `review/<project>/` dataset
(`samples.json` + `images/` + `view.json`); `paratext review` opens a local web
UI over the `review/` root. If a review server is already running, a fresh `run`
shows up there on reload — no restart needed. Add `paratext run … --review` to
launch the UI automatically when the run finishes.

## Commands

| Command | What it does |
| --- | --- |
| `paratext run -p <project>` | Extract **and** package in one step (the common path). |
| `paratext extract -p <project>` | Run the VLM, write JSONL only. |
| `paratext package <jsonl> -p <project> --out <dir>` | Package an existing JSONL for review. |
| `paratext review <dataset-dir>` | Launch the inbuilt web UI to review a packaged dataset. |
| `paratext sample --source <tree> --out <dir> -n 500` | Symlink a random image subset out of a nested tree. |
| `paratext config [--show]` | Open `paratext.toml`; `--show` prints the resolved defaults. |
| `paratext new [name]` | Scaffold a new project package (asks fields, prompt, source). |

Run `paratext`, `paratext help`, or `paratext <command> -h` for usage.

### Flags

Most `run`/`extract` values resolve from `paratext.toml` (see Configure), so you
rarely pass them — but every default can be overridden on the CLI.

- **`run -p <project>`** — `--source DIR`, `--output FILE` (default
  `output/<project>.jsonl`), `--model ID`, `--base-url URL`, `--api-key KEY`,
  `--limit N`, `--no-structured`, `--skip-preflight`, `--review-out DIR`,
  `--review` (open the UI when finished).
- **`extract -p <project>`** — same as `run` minus the two review flags
  (writes JSONL only).
- **`package <jsonl> -p <project>`** — `--out DIR` (required), `--fresh`
  (delete the output dir first).
- **`review [data_dir]`** — `data_dir` defaults to `./review`; `--port N`
  (config `review-port`, else 5050), `--no-open`.
- **`sample`** — `--source DIR` (required), `--out DIR` (required), `-n N`
  (default 500), `--seed N`.
- **`config`** — `--show` (print resolved defaults instead of editing),
  `-p <project>` (which project's defaults to resolve).
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

## License

Apache-2.0. The card-detector model weights are distributed separately on the
Hugging Face Hub under their own license.
