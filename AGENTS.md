# paratext — agent guide

Modular metadata-extraction pipeline for digitised library/archive collections,
driven by a multimodal model. This orients AI coding agents; `README.md` is the
human guide.

## Overview

- One CLI (`paratext`) runs the loop: `extract` (model → JSONL), `package`
  (JSONL → review dataset), or `run` (both, the common path); `review` launches
  the inbuilt web UI over a packaged dataset; `export` publishes a reviewed round
  as a Hugging Face dataset; `carbon` reports grid intensity for `--green`
  scheduling. Plus `sample`, `config`, `new`, and `guide` (prints this document
  plus the installed projects, so an agent can self-orient from the PATH).
  Typical: `paratext run -p <project> --limit 50` then `paratext review`. Most
  flags resolve from `paratext.toml`/env, so `-p <project>` is usually enough.
- The inbuilt review (`paratext.review`) is a dependency-free stdlib
  `http.server` + `sqlite3` app serving a generic vanilla-JS frontend in
  `review/static/`, driven entirely by each dataset's `view.json`. Reviewers give
  a verdict + free-text note (the `annotations` table); the **Build eval set** tab
  (`#/eval`) additionally lets them edit fields into a corrected answer, stored in
  a separate `gold_labels` table (`POST /api/gold/<id>`). The `annotations.corrections`
  column is unrelated — handwritten corrections on the card, not reviewer edits.
- A **project** is a plug-in package discovered via the `paratext.projects`
  entry-point group: `prompt.md` (prompt), `schema.py` (Pydantic schema), and
  `__init__.py` which wires them to a `paratext.sources` adapter
  (`image_source`/`pdf_source`) into a `PROJECT`. The bundled worked example is
  `card-template`; `paratext new` scaffolds this layout, offers to write the project's
  `[project.<name>]` config block (`scaffold._offer_config`), then registers the
  entry point in pyproject.toml and runs `uv sync` automatically
  (`scaffold._register_and_sync`; `--no-install` skips it).
- Output is JSONL with a `_provenance` header (git commit, prompt hash, model,
  schema version, timestamp). Resumable: re-running with the same `--output`
  skips ids already present.
- Packaging is project-agnostic — `packaging.py` delegates per-record decisions
  to optional hooks on `Project` (`curate`, `materialise_images`,
  `build_record`, `ground_truth`).

## Setup, build, run

- Python 3.11–3.13 via `uv`. `uv sync --extra dev` (add `--extra detector` for the
  torch detector runtime). Run with `uv run paratext …`, or `uv tool install`
  for the bare command.
- model endpoint is any OpenAI-compatible server; base URL via `paratext.toml` or
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
- `paratext export -p <project> --format {hf,marc,dc}` (omit → menu on a TTY, hf
  default). All formats share the same gold set via `records.select_records`:
  `good_enough` rows (`_label_status: verified`) **plus** human-corrected `gold_labels`
  rows (`corrected`); no gold rows → good-enough-only, as before.
  - **hf** (`hf_export.py`): imagefolder + `metadata.jsonl` + auto card via the
    already-present `huggingface_hub` (no `datasets` dep). Single-image only,
    private-by-default; a missing licence is steered (CC0 recommended) but never
    blocks. Spec: `docs/hf-export-spec.md`.
  - **marc/dc** (`catalogue.py`): MARCXML / OAI Dublin Core to `export/<round>.*`
    via stdlib `xml.etree` (no dep); metadata-only, so multi-image (monographs) works.
    Schema fields → MARC tag / DC element: standard names auto-inferred (`CANONICAL`),
    unknowns filled by an interactive wizard and persisted to
    `[project.<name>.export.marc|dc]` in paratext.toml (`""` = skip). Unmapped fields
    are dropped with a warning, never a hard error.
- `paratext.cards` is the reusable scanned-card toolkit: the deterministic
  `is_verso` pre-filter (pure NumPy) and the optional RetinaNet
  `load_card_detector()` (weights from the Hugging Face Hub, `[detector]` extra).
  Both are **off by default** and calibrated on NLS scans — they are opt-in per
  project via `image_source(verso_filter=…, crop=…)`, and the detector repo is
  configurable via the `[detector]` table in paratext.toml. Never assume they
  transfer to another collection unchanged.
- `paratext inspect [-p <name>]` (and the review UI's **Project configuration**
  page, backed by `paratext.inspect`) describes the **installed** projects:
  derived field types, prompt hash, source options, and the `audit_project`
  result. Both are
  read-only. Start here when a project's behaviour doesn't match its source —
  a mismatch usually means the package needs reinstalling, not that the code is
  wrong.
- A source adapter that **degrades** rather than fails appends to
  `Source.notices`, and `extract` prints those at the end of the run (e.g. a
  requested card crop falling back to a uniform crop because no detector loaded).
  Preprocessing that silently does nothing is the worst failure mode here — it
  looks like a clean run and quietly costs accuracy — so if you add a fallback
  path, add a notice with it.
- Bump a project's `schema_version` when its schema changes.
- A project names its fields in three places — `schema.py` (structure; also sent
  to the model as `response_format`), `prompt.md` (instructions), and the `View`
  (presentation). They share no compile-time link, so keep them in step with
  `paratext.projects.audit_project(project)` (call it from your project tests): it
  checks the View's fields exist in the schema and that every `model_output` field
  is named in the prompt. Put behavioural guidance in `prompt.md` (its natural
  home — prose, examples, versioned with the prompt hash); keep Pydantic
  `Field(description=...)` short and structural, since those descriptions are
  *also* sent to the model and shouldn't repeat the prompt in a second voice.

## Iterating: rounds & prompt feedback

The prompt is what you tune. `run` writes each dataset to
`review/<project>-r<N>`, where the round `N` is keyed on the **prompt hash**:
editing `prompt.md` and re-running rolls a new round (the UI diffs the two latest
rounds); re-running the same prompt updates the current round in place, keeping
its annotations. Rounds are a linear history — reverting a prompt starts a new
round. `--round N` forces one; `--fresh` rebuilds a round, discarding its
annotations. To fold review feedback back into the prompt, read the round's
`annotations.db` (SQLite: `annotations` for verdicts/notes, `gold_labels` for
human-corrected answers) or, with the server running, `GET /api/stats`
(accuracy/verdict counts + eval-gold size) and `GET /api/export/<id>` (CSV) — then
tighten the fields reviewers corrected most.
