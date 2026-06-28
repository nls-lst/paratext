# paratext — agent guide

Plugin VLM metadata-extraction pipeline for digitised library/archive
collections. This orients AI coding agents; `README.md` is the human guide.

## Overview

- One CLI (`paratext`) runs the loop: `extract` (VLM → JSONL), `package`
  (JSONL → review dataset), or `run` (both); `review` launches the inbuilt web
  UI over a packaged dataset. Plus `sample`, `config`, `new`.
- The inbuilt review (`paratext.review`) is a dependency-free stdlib
  `http.server` + `sqlite3` app serving a generic vanilla-JS frontend in
  `review/static/`, driven entirely by each dataset's `view.json`.
- A **project** is a plug-in package discovered via the `paratext.projects`
  entry-point group: `prompt.md` (prompt), `schema.py` (Pydantic schema), and
  `__init__.py` which wires them to a `paratext.sources` adapter
  (`image_source`/`pdf_source`) into a `PROJECT`. The bundled generic starter is
  `cards`; `paratext new` scaffolds this layout.
- Output is JSONL with a `_provenance` header (git commit, prompt hash, model,
  schema version, timestamp). Resumable: re-running with the same `--output`
  skips ids already present.
- Packaging is project-agnostic — `packaging.py` delegates per-record decisions
  to optional hooks on `Project` (`curate`, `materialise_images`,
  `build_record`, `ground_truth`).

## Setup, build, run

- Python 3.11–3.13 via `uv`. `uv sync --extra dev` (add `--extra pdf` for the
  PDF tests). Run with `uv run paratext …`, or `uv tool install` for the bare
  command.
- VLM endpoint is any OpenAI-compatible server; base URL via `paratext.toml` or
  `PARATEXT_BASE_URL`.

## Testing and lint

- `uv run ruff check` (line length 100, rules E/F/I/W) and `uv run pytest -q`.
  Keep files you touch clean.

## Conventions

- Some models need `enable_thinking=False`; a project sets `disable_thinking`
  and `runner.py` passes it through.
- `paratext.cards` is the reusable scanned-card toolkit: the deterministic
  `is_verso` pre-filter (pure NumPy) and the optional RetinaNet
  `load_card_detector()` (weights from the Hugging Face Hub, `[cards]` extra).
- Bump a project's `schema_version` when its schema changes; the prompt hash
  drives the round-to-round diff shown by the review app.
