<h1>
  <img src="assets/logo.png" alt="paratext logo" height="100" align="middle">&nbsp; paratext
</h1>

A modular, project-based pipeline that produces metadata from digitised library
& archive collections with a multimodal model, built around human-in-the-loop.

A subject matter expert reviews a sample and helps iterate on the prompt until
the accuracy is good enough to let it run over a full dataset. The focus is on
_good enough_ metadata for large collections rather than _perfect_ metadata.

Version history for prompts and schemas is kept, so reviewers can see exactly
what changed in the prompt and judge whether it helped. Extraction quality lives
almost entirely in the prompt and the schema, which is where domain knowledge
ends up: written down, versioned, deterministic and testable.

Approved and corrected records can also build a gold set: a fixed benchmark
for measuring other models against the same material.

Run a model over a directory of images or PDFs, write resumable JSONL with
provenance, package it for review, and export the approved results. Each
**project** is a self-contained module, with its own prompt, schema and input
handling, so the same code path runs a 50-item pilot and a 250,000-item sweep.

## What you'll need

- **A directory of images or PDFs.** Images are read from a flat directory, one
  item per file; PDFs recursively.
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

## Docs

- **[Writing a project](docs/writing-a-project.md)** — the three scaffolded files,
  the `Project` contract, source adapters, and how projects are discovered.
- **[Review and rounds](docs/review-and-rounds.md)** — the run/review/edit loop,
  what a round is, verdicts, and building the gold set.
- **[Commands](docs/commands.md)** — every subcommand and what it is for.
- **[Configuration](docs/configuration.md)** — `paratext.toml`, resolution order,
  every key, hosted endpoints and environment variables.
- **[Export](docs/export.md)** — Hugging Face datasets, MARCXML and Dublin Core,
  and what makes up the gold set.
- **[Scanned cards](docs/scanned-cards.md)** — verso filtering, card cropping and
  show-through suppression for index-card collections.
- **[Green scheduling](docs/green-scheduling.md)** — wait for clean electricity
  before running a batch.
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
