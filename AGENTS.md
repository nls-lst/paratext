# paratext — agent guide

Plugin VLM metadata-extraction pipeline for digitised library/archive
collections. This orients AI coding agents; `README.md` is the human guide.

## Overview

- One CLI (`paratext`) runs the loop: `extract` (VLM → JSONL), `package`
  (JSONL → review dataset), or `run` (both, the common path); `review` launches
  the inbuilt web UI over a packaged dataset; `export` publishes a reviewed round
  as a Hugging Face dataset; `carbon` reports grid intensity for `--green`
  scheduling. Plus `sample`, `config`, `new`.
  Typical: `paratext run -p <project> --limit 50` then `paratext review`. Most
  flags resolve from `paratext.toml`/env, so `-p <project>` is usually enough.
- The inbuilt review (`paratext.review`) is a dependency-free stdlib
  `http.server` + `sqlite3` app serving a generic vanilla-JS frontend in
  `review/static/`, driven entirely by each dataset's `view.json`.
- A **project** is a plug-in package discovered via the `paratext.projects`
  entry-point group: `prompt.md` (prompt), `schema.py` (Pydantic schema), and
  `__init__.py` which wires them to a `paratext.sources` adapter
  (`image_source`/`pdf_source`) into a `PROJECT`. The bundled generic starter is
  `cards`; `paratext new` scaffolds this layout, offers to write the project's
  `[project.<name>]` config block (`scaffold._offer_config`), and prints the
  entry-point registration + reinstall + run steps.
- Output is JSONL with a `_provenance` header (git commit, prompt hash, model,
  schema version, timestamp). Resumable: re-running with the same `--output`
  skips ids already present.
- Packaging is project-agnostic — `packaging.py` delegates per-record decisions
  to optional hooks on `Project` (`curate`, `materialise_images`,
  `build_record`, `ground_truth`).

## Setup, build, run

- Python 3.11–3.13 via `uv`. `uv sync --extra dev` (add `--extra cards` for the
  torch detector runtime). Run with `uv run paratext …`, or `uv tool install`
  for the bare command.
- VLM endpoint is any OpenAI-compatible server; base URL via `paratext.toml` or
  `PARATEXT_BASE_URL`.

## Testing and lint

- `uv run ruff check` (line length 100, rules E/F/I/W) and `uv run pytest -q`.
  Keep files you touch clean.

## Conventions

- Some models need `enable_thinking=False`; a project sets `disable_thinking`
  and `runner.py` passes it through.
- `paratext carbon` / `run --green` (`carbon.py`) is opt-in carbon-aware
  scheduling: wait for a clean grid before extracting, and stamp the reading into
  provenance (`energy`) so the export card can report it. Providers: `uk` (Carbon
  Intensity API — no token, regional + 48h forecast), `energy-charts` (Fraunhofer,
  no token, EU country-level, forecast), `electricitymaps` (token, global, latest
  only). Grid region is declared in `[carbon]`, never auto-detected — `paratext
  config --suggest-region` (also offered once on fresh-config onboarding)
  IP-geolocates only to *propose* one. Stdlib `urllib` only.
- `paratext export` (`hf_export.py`) publishes a reviewed round as a HF dataset
  (imagefolder + `metadata.jsonl` + auto card) via the already-present
  `huggingface_hub` — no `datasets` dep. v1 gold = `good_enough` rows only,
  single-image projects only, private-by-default with a license gate for
  `--public`. Full design + roadmap: `docs/hf-export-spec.md`.
- `paratext.cards` is the reusable scanned-card toolkit: the deterministic
  `is_verso` pre-filter (pure NumPy) and the optional RetinaNet
  `load_card_detector()` (weights from the Hugging Face Hub, `[cards]` extra).
- Bump a project's `schema_version` when its schema changes.

## Iterating: rounds & prompt feedback

The prompt is what you tune. `run` writes each dataset to
`review/<project>-r<N>`, where the round `N` is keyed on the **prompt hash**:
editing `prompt.md` and re-running rolls a new round (the UI diffs the two latest
rounds); re-running the same prompt updates the current round in place, keeping
its annotations. Rounds are a linear history — reverting a prompt starts a new
round. `--round N` forces one; `--fresh` rebuilds a round, discarding its
annotations. To fold review feedback back into the prompt, read the round's
`annotations.db` (SQLite; `corrections` column is per-field JSON) or, with the
server running, `GET /api/stats` (accuracy/verdict counts) and
`GET /api/export/<id>` (CSV) — then tighten the fields reviewers corrected most.
