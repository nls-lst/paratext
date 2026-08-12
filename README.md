<h1>
  <img src="assets/logo.png" alt="paratext logo" height="100" align="middle">&nbsp; paratext
</h1>

A modular, project-based pipeline that produces metadata from digitised library
& archive collections with a multimodal model. Includes a human-in-the-loop
review tool.

One command does the whole loop: run a model over a directory of images or PDFs,
write resumable JSONL with provenance, package it for review, and export the
approved results. Each **project** is a self-contained module — its own prompt,
schema, and input handling — so the same code path runs a 50-item pilot and a
250,000-item sweep. Only `--limit` differs.

## What you'll need

- **A directory of images or PDFs.** Images are read from a flat directory, one
  item per file; PDFs recursively.
- **An OpenAI-compatible endpoint serving a model that accepts images.** Local
  hosting (llama.cpp, vLLM, LM Studio, [Lemonade](https://lemonade-server.ai/)
  etc) or a hosted provider.
- **Python 3.11 or newer**, and [uv](https://docs.astral.sh/uv/). (The optional
  card detector is capped at 3.13 until torch ships 3.14 wheels.)

## Install

paratext is not on PyPI. Install from a clone:

```bash
git clone https://github.com/nls-lst/paratext
uv tool install ./paratext
```

The trailing path matters: plain `uv tool install paratext` resolves an
unrelated package of the same name from PyPI, which installs no `paratext`
command.

Upgrade with `git -C paratext pull && uv tool install ./paratext --force`. Your
projects live in their own package, so upgrading the framework leaves them
untouched.

## Quickstart

```bash
# 1. Scaffold a project: asks input type, fields and prompt, writes the config,
#    registers the entry point, runs `uv sync`. Ready to run.
#    Works in an empty directory (it offers to create the project for you) or
#    inside an existing one, where it nests into your package.
paratext new my-cards

# 2. Check what it will actually do before spending a model run on it.
paratext inspect -p my-cards

# 3. Extract, package, and review.
paratext run -p my-cards --limit 50
paratext review
```

`run` writes the extraction JSONL and a `review/my-cards-r1/` dataset;
`review` opens a local web UI over everything under `review/`. Datasets are
re-read per request, so a fresh `run` appears on reload without a restart.

`inspect` prints the fields the model is asked for, the prompt, the
preprocessing applied, and whether schema, prompt and view still agree. It
describes what is **installed** — so if it disagrees with the files you're
editing, the package needs reinstalling. That mismatch is the most common cause
of "my change did nothing".

## Writing a project

`paratext new` scaffolds three files:

```
my_cards/
    prompt.md     # the prompt (prose, for the model)
    schema.py     # the Pydantic output schema (your metadata fields)
    __init__.py   # wires them together
```

`__init__.py` stays small because input handling comes from a **source adapter**:

```python
from paratext.projects import Project, load_prompt
from paratext.sources import image_source   # or pdf_source

from .schema import Record

PROJECT = Project(
    name="my-cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=Record,
    source=image_source(),
)
```

Register it so it's discovered at runtime:

```toml
[project.entry-points."paratext.projects"]
my-cards = "my_cards:PROJECT"
```

That's the whole contract. The review view defaults to showing every schema
field; override it only when you want to curate the display. Optional hooks
(`curate`, `build_record`, `ground_truth`) handle drop rules and ground truth.

Your fields end up named in three places — schema, prompt, and view — with no
automatic link between them. Keep them in step by calling `audit_project(PROJECT)`
from a test; `paratext new` generates one. Put behaviour in `prompt.md`, and keep
the schema's `Field(description=...)` short and structural — those descriptions
are sent to the model too, and shouldn't restate the prompt in a second voice.

## Review and rounds

Extraction quality lives almost entirely in the prompt, so the workflow is a
loop: **run → review → edit the prompt → run again**. A **round** captures one
prompt version, keyed on the prompt's hash:

- **Edit `prompt.md` and re-run** → a new round (`-r2`, `-r3`, …). The UI shows
  the two most recent rounds side by side and highlights what changed.
- **Re-run the same prompt** (a resume, or a bigger `--limit`) → the current round
  is updated in place, keeping the annotations you've already made.

Reviewers give a verdict and a free-text note. The **Build eval set** tab goes
further: it surfaces the rows the model got wrong and lets you edit the fields
into the correct answer, stored separately as **gold labels**. Accuracy still
reflects the model — correcting a row never changes its verdict — but those
corrected rows ship as gold alongside the approved ones when you export.

Everything is saved to a SQLite `annotations.db` you can query directly.

## Configure

A `paratext.toml` in the working directory holds your defaults, and
`paratext config` creates and opens it. Keys are kebab-case, matching the CLI
flag that sets them:

```toml
base-url = "http://localhost:8000/v1"
model    = "Qwen3-VL-30B"

[project.my-cards]
source = "/data/my-cards/images"
output = "output/my-cards.jsonl"
```

Once a project has a section, `paratext run -p my-cards` needs nothing else.
CLI flags override environment variables, which override the file.

Full reference, including hosted endpoints and auth: **[docs/configuration.md](docs/configuration.md)**.

## Commands

| Command | What it does |
| --- | --- |
| `paratext run -p <project>` | Extract **and** package in one step (the common path) |
| `paratext extract -p <project>` | Run the model, write JSONL only |
| `paratext package <jsonl>` | Re-package an existing JSONL (no model calls) |
| `paratext review [dir]` | Launch the review UI (default: `./review`) |
| `paratext export -p <project>` | Export a reviewed round (`--format hf`/`marc`/`dc`) |
| `paratext inspect [-p <project>]` | Show what an installed project does |
| `paratext new [name]` | Scaffold a new project package |
| `paratext config [--show]` | Open `paratext.toml`; `--show` prints resolved defaults |
| `paratext sample` | Symlink a random image subset out of a nested tree |
| `paratext carbon` | Show current grid carbon/renewables |
| `paratext guide` | Print the agent guide |

Run `paratext <command> -h` for that command's flags.

## Going further

- **[Export](docs/export.md)** — Hugging Face datasets, MARCXML, Dublin Core, and
  what makes up the gold set.
- **[Configuration](docs/configuration.md)** — full key reference, hosted
  endpoints, environment variables.
- **[Scanned cards](docs/scanned-cards.md)** — optional verso filtering, card
  cropping and show-through suppression for index-card collections.
- **[Green scheduling](docs/green-scheduling.md)** — wait for a clean electricity
  grid before running a batch.
- **[AGENTS.md](AGENTS.md)** — the guide for AI coding agents, including how to
  extend paratext for your own collection.

## When something looks wrong

- **A run finished but preprocessing didn't happen.** `run` prints a `!` notice
  for anything that degraded rather than failed — most often a card crop falling
  back to a uniform crop because no detector was available.
- **An edit to `schema.py` or `prompt.md` had no effect.** `paratext inspect`
  reports the *installed* project. If it disagrees with your editor, reinstall
  (`uv sync`). An editable install avoids this entirely.
- **A field renamed in one place but not another.** `paratext inspect` runs the
  same audit as `audit_project`. Call it from your tests too.

## Development

```bash
uv sync --extra dev            # add --extra detector for the card detector
uv run paratext …              # run the CLI against local source
uv run pytest -q               # tests
uv run ruff check              # lint
```

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Copyright 2026
National Library of Scotland. The card-detector model weights are distributed
separately on the Hugging Face Hub under their own license.
