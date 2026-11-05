<h1>
  <img src="assets/logo.png" alt="paratext logo" height="100" align="middle">&nbsp; paratext
</h1>

A framework for producing metadata from digitised library and archive
collections with a multimodal model.

A subject expert reviews a small sample of what the model produces. You revise
the prompt and schema until the results are good enough, then run it over the
whole collection. The aim is _good enough_ metadata for large collections, not
_perfect_ metadata.

## What it does

- **Reads your material:** images, PDFs or video from a folder, or a dataset on
  the Hugging Face Hub. It can also load metadata you already have, so you can
  review it without running a model.
- **Runs one project at a time.** A project holds its own prompt, schema and
  input handling, so the same setup runs a 50-item pilot or a 250,000-item
  collection. Runs can be resumed and record where each answer came from.
- **Opens a review screen in your browser.** Experts give each record a verdict
  and a note, and can correct it. Video plays with a timeline that sets the
  model's answers beside any existing catalogue record.
- **Keeps every version of the prompt and schema,** so reviewers can see what
  changed between rounds and judge whether it helped. Most of the domain
  knowledge ends up there: written down, versioned and testable.
- **Builds a gold set** from approved and corrected records. You can publish it
  on the Hugging Face Hub as a fixed test for comparing other models against
  your material, and use other libraries' published sets the same way.
- **Exports the approved results** as a Hugging Face dataset, MARCXML or Dublin
  Core.
- **Measures the energy and carbon of every run.** See below.

## Energy and carbon

Every run on your own hardware records the electricity it used and what that
emitted on your local grid. The figures come from the machine's own power
sensors. Nothing is estimated: a run on a hosted model is recorded as "not
measured".

For example, one run over 18,221 born-digital books took 36 hours on a desktop
machine. It used 3.8 kWh, about 0.2 Wh a record, and emitted 4.2 g CO2e on a
grid that was 84% renewable.

```bash
paratext carbon
```

This shows the grid now and for the next 48 hours, and writes a one-page report
for each run and each project as a Word file (and a PDF if LibreOffice is
installed), plus a CSV. You can use these in a
sustainability return. Runs can also wait while the grid is short of renewable
power. See [Carbon](docs/carbon.md).

## What you'll need

- **Your material:** a directory of images, PDFs or video (video needs
  [ffmpeg](https://ffmpeg.org/)), or an image dataset on the Hugging Face Hub.
  Or metadata you already have, to review without running a model.
- **An OpenAI-compatible endpoint serving a model that accepts images.** Local
  hosting (llama.cpp, vLLM, LM Studio, [Lemonade](https://lemonade-server.ai/)
  etc) or a hosted provider — anything that speaks the OpenAI chat API.
- [uv](https://docs.astral.sh/uv/)

If you have no endpoint in mind, a hosted one takes two lines of config and no
card — every Hugging Face account has a small monthly allowance:

```toml
base-url = "https://router.huggingface.co/v1"
model    = "Qwen/Qwen3-VL-30B-A3B-Instruct"
```

with your token in `PARATEXT_API_KEY`. A local server is the same shape:
`base-url = "http://localhost:8000/v1"` and whichever model it serves.

## Install

```bash
uv tool install paratext-cli
```

Upgrade with `uv tool upgrade paratext-cli`.

## Quickstart

```bash
# 1. Scaffold a project: asks input type, fields and prompt, writes the config,
#    registers the entry point, runs `uv sync`. Ready to run.
#    Works in an empty directory (it offers to create the project for you) or
#    inside an existing one, where it nests into your package.
paratext new my-cards      # also asks for your endpoint and writes paratext.toml

# 2. Check what it will actually do before spending a model run on it.
paratext inspect -p my-cards

# 3. Extract, package, and review. Start small — the first thing you learn is
#    how wrong the prompt is, and five items tell you that as well as fifty.
paratext run -p my-cards --limit 5
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

`paratext carbon` shows the energy your runs used, with no setup needed. To add
emissions, name your grid region in a `[carbon]` table in `paratext.toml`;
`paratext config --suggest-region` proposes one for you to check.

## Documentation

This page covers getting started. The [`docs/`](docs/) folder has the detail:
start with **Writing a project**, then **Review and rounds**.

- **[Writing a project](docs/writing-a-project.md)** — setting a project up step
  by step: source, schema and prompt, model, review view.
- **[Review and rounds](docs/review-and-rounds.md)** — the run/review/edit loop,
  what a round is, verdicts, and building the gold set.
- **[Choosing a review view](docs/review-views.md)** — which fields reviewers
  see, how to compare against an existing record, and video review.
- **[Carbon](docs/carbon.md)** — energy and emissions for every run, a report for
  sustainability returns, and pausing while the grid is dirty.
- **[Commands](docs/commands.md)** — every subcommand and what it is for.
- **[Configuration](docs/configuration.md)** — `paratext.toml`, resolution order,
  every key, hosted endpoints and environment variables.
- **[Export](docs/export.md)** — Hugging Face datasets, MARCXML and Dublin Core,
  and what makes up the gold set.
- **[Scanned cards](docs/scanned-cards.md)** — verso filtering, card cropping and
  show-through suppression for index-card collections.
- **[Troubleshooting](docs/troubleshooting.md)** — what to check when the output
  is not what you expected.
- **[HF export spec](docs/hf-export-spec.md)** — the dataset layout, card and row
  fields a published round produces.
- **[Publishing](docs/publishing.md)** — cutting a paratext release to PyPI.
- **[AGENTS.md](AGENTS.md)** — the guide for AI coding agents. `paratext skill`
  installs it where Claude Code, Codex and the rest look, so an agent finds it
  without being told.

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
