# paratext — agent guide

Modular metadata-extraction pipeline for digitised library/archive collections,
driven by a multimodal model. This orients AI coding agents; `README.md` is the
human guide.

paratext is **built to be adapted**. Most users need a project of their own, and
some need a new input format or a new export format. Those are extension points,
not forks — the recipes below are the supported way in.

## Rules

- **Read a file in full before editing it.** These modules are short by design;
  there is no excuse for patching blind.
- **Run `uv run pytest -q` and `uv run ruff check` after every change.** Both must
  be clean. Line length 100, rules E/F/I/W.
- **Never edit `prompt.md` and `schema.py` casually.** A prompt edit rolls a new
  review round and invalidates comparisons; a schema change needs a
  `schema_version` bump. Both cost a model run to re-evaluate.
- **Keep a project's fields in step across all three places** (schema, prompt,
  view) and call `audit_project()` from its tests.
- **Add a notice, not a silent fallback.** If you write a degraded path, append to
  `Source.notices` so `extract` reports it. Preprocessing that silently does
  nothing looks like a clean run and quietly costs accuracy — it is the worst
  failure mode in this codebase.
- **Don't hardcode institution-specific values.** Detector weights, verso
  thresholds and grid regions are all config.
- **Ask before removing functionality** that looks deliberate.
- Say "multimodal model" or "the model" — never "VLM".

## Setup, build, run

```bash
uv sync --extra dev          # add --extra detector for the torch card detector
uv run paratext …            # run the CLI against local source
uv run pytest -q
uv run ruff check
```

Python 3.11+ via `uv` (which supplies the interpreter). The model endpoint is
any OpenAI-compatible server;
set `base-url` in `paratext.toml` or `PARATEXT_BASE_URL`.

**The installed-vs-source trap:** a non-editable install means source edits do
nothing until reinstall. `paratext inspect` reports the *installed* project — when
behaviour doesn't match the source you're reading, check there first.

## Architecture

One CLI runs the loop: `extract` (model → JSONL) → `package` (JSONL → review
dataset) → `review` (web UI) → `export` (publish). `run` does extract+package.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Argparse wiring, round resolution, command bodies |
| `config.py` | `paratext.toml` + `PARATEXT_*` resolution |
| `projects/` | The `Project` plug-in contract, `View`, `audit_project` |
| `sources.py` | Input adapters (`image_source`, `pdf_source`) |
| `extract.py` / `runner.py` | Sample loop; model call, retries, image encoding |
| `packaging.py` | JSONL → `samples.json` + `images/` + `view.json` |
| `store.py` | SQLite annotations + gold labels — **not** web code |
| `datasets.py` | Discovering packaged rounds, resolving `view.json` |
| `records.py` | Format-neutral gold selection, shared by all exports |
| `catalogue.py` / `hf_export.py` | MARC/DC and Hugging Face exports |
| `review/server.py` | HTTP layer only; `review/static/` is the vanilla-JS frontend |
| `cards.py` | Optional scanned-card tools (verso, crop, show-through) |
| `carbon.py` | Grid-intensity providers for `--green` |

`store.py` and `datasets.py` are deliberately outside `review/` so exporters can
read a reviewed round without starting a web server.

Output is JSONL with a `_provenance` header (git commit, prompt hash, model,
schema version, timestamp), and is resumable: re-running with the same `--output`
skips ids already present. A changed prompt or model is refused rather than
resumed — pass `--re-extract` to discard the old records, or `--output` a new
file to keep both.

---

# Extending paratext

## Recipe: a new project

The common case — a user's own collection. `paratext new <name>` scaffolds it;
these are the files it makes and what to edit.

```
my_cards/
    prompt.md     # behaviour lives here
    schema.py     # Pydantic model = the fields, also sent as response_format
    __init__.py   # wires them into PROJECT
```

```python
from paratext.projects import Project, load_prompt
from paratext.sources import image_source

from .schema import Record

PROJECT = Project(
    name="my-cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=Record,
    source=image_source(),
)
```

Register it in the user's `pyproject.toml`:

```toml
[project.entry-points."paratext.projects"]
my-cards = "my_cards:PROJECT"
```

Then `uv sync` — entry points are re-scanned per request, so the review server
picks up a new project without a restart, but **framework code changes still need
one**.

Optional, in order of how often you'll need them:

- `view=View(...)` — curate the review display. Defaults to every schema field.
- `curate(rec) -> Curation` — `keep` / `drop` / `quarantine` per record.
- `build_record(rec, images)` — extra keys in `samples.json`.
- `ground_truth(rec)` — attach existing catalogue data for side-by-side review.
- `disable_thinking` — asks the server to skip reasoning. **vLLM/Qwen dialect
  only** (`chat_template_kwargs.enable_thinking`); other providers ignore it and
  reason anyway. Users cover those with `[project.<name>.extra-body]`.
- `max_tokens` — per-project output ceiling; `None` uses `runner.DEFAULT_MAX_TOKENS`
  (8192). A reasoning model spends this budget before writing any answer, so a
  cap that fits the JSON but not the thinking yields nothing at all.

**Field discipline:** the field names appear in schema, prompt and view with no
compile-time link. `audit_project(PROJECT)` checks the view's fields exist in the
schema and that every model-output field is named in the prompt. Call it from a
test — `paratext new` generates one.

Put behaviour in `prompt.md` (prose, examples, versioned by the prompt hash).
Keep `Field(description=...)` short and structural: it is *also* sent to the
model and shouldn't restate the prompt in a second voice.

## Recipe: a new source adapter

For an input shape neither `image_source` nor `pdf_source` covers — a IIIF
manifest, a METS/ALTO tree, a CSV of URLs, a database query.

A `Source` is two functions that must agree on the metadata they pass between
them, plus optional notices and a descriptive config:

```python
from paratext.sources import Source
from paratext.projects import Sample
from paratext.packaging import save_image

def iiif_source(*, max_items: int | None = None) -> Source:
    notices: list[str] = []

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        # yield one Sample per unit of work
        yield Sample(
            id="unique-stable-id",           # becomes the JSONL/review key
            images=[pil_image],              # what the model sees
            metadata={"iiif_url": url},      # anything materialise() will need
        )

    def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
        # write review images under `out`, return paths relative to it
        rel = f"images/{rec['id']}/image.jpg"
        save_image(local_path, out / rel, max_size)
        return [rel]

    return Source(
        iter_samples=_iter,
        materialise=_materialise,
        notices=notices,
        config={"kind": "iiif", "max_items": max_items},   # shown by `paratext inspect`
    )
```

Rules specific to sources:

- **`id` must be stable across runs** — resume and round-updating both key on it.
- **`metadata` is the contract between the two halves.** `_materialise` runs at
  packaging time, long after iteration, and gets only the JSONL record.
- **Degrade loudly.** Falling back? `notices.append(...)`, and say what to do
  about it.
- **`config` is descriptive only** — nothing reads it back to make decisions; it
  exists so `paratext inspect` can show what preprocessing was applied.
- If your images need no special handling, reuse `packaging.default_materialise`
  rather than writing the same six lines again.

A source can also pre-classify a sample to skip the model entirely: set
`metadata["preclassified"] = {...}` and `extract` writes it straight through
(this is how the verso filter avoids paying for blank card backs).

## Recipe: a new export format

For a shape the built-in `hf` / `marc` / `dc` don't cover — EAD, MODS, a local ILS
format, a CSV for a spreadsheet workflow.

**Never re-derive which records are gold.** `records.select_records()` is the
single source of truth and every format shares it:

```python
from paratext.records import select_records

sel = select_records(dataset_dir, project, db_path=db_path)
for rec in sel.records:
    rec.label            # {field: value} — the gold label
    rec.status           # verified | corrected | rejected
    rec.verdict          # the model's original verdict, kept for corrected rows
    rec.document_id      # stable id, falls back to rec.sid
    rec.images           # resolved paths (may be empty)
sel.schema_fields        # field order from the Pydantic schema
sel.provenance           # model, prompt_hash, schema_version
```

Then follow `catalogue.py`'s shape — a pure `build_*(records, mapping)` that
returns bytes or a tree, and a `run()` that selects, builds and writes:

1. Write `build_ead(records, mapping) -> ET.ElementTree` with no I/O, so it's
   unit-testable without a dataset on disk.
2. Add a `run(dataset_dir, project, fmt)` that calls `select_records`, builds,
   and writes to `EXPORT_ROOT`.
3. Plumb it into the CLI in `cli.py`: add the name to `--format`'s `choices`, to
   `_FORMAT_MENU`, and to the `_cmd_export` dispatch.
4. If fields need mapping to a target vocabulary, reuse `resolve_mapping()` —
   config under `[project.<name>.export.<fmt>]` wins, then canonical inference by
   field name, and anything left goes to the wizard. Unmapped fields are dropped
   with a warning, **never** a hard error.

To expose it in the review UI's export modal as well, add a tab in
`review/static/app.js` (`openExportModal`) and an endpoint in `review/server.py`
alongside `_api_export_catalogue`.

---

## Conventions

- **Rounds.** `run` writes `review/<project>-r<N>`, keyed on the **prompt hash
  and the model**: change either and it rolls a new round (the UI diffs the two
  latest); re-run the same prompt on the same model and it updates the current
  round in place, keeping its annotations. The model is part of the key because
  annotations are keyed `(dataset, sample_id)` — reusing a round across a model
  swap would leave verdicts attached by id to output nobody reviewed. A round
  packaged before `provenance.json` existed doesn't record its model and so is
  never reused; you get an extra round and a line saying why. Rounds are linear —
  reverting a prompt starts a new round, it doesn't return to the old one.
  `--round N` forces (and skips the model check); `--fresh` rebuilds and discards
  annotations.
- **Reading feedback back into the prompt.** `annotations.db` holds verdicts and
  notes (`annotations`) and human-corrected answers (`gold_labels`); read it via
  `store.py`. With the server running, `GET /api/stats` gives accuracy and
  eval-gold size. Tighten the fields reviewers corrected most.
  The `annotations.corrections` column is unrelated — handwritten corrections on
  the *card*, not reviewer edits.
- **Export gold** is `good_enough` rows (`_label_status: verified`) plus corrected
  `gold_labels` rows (`corrected`). `_verdict` preserves the model's original
  verdict, so accuracy still measures the model, not the human who fixed it.
- **`paratext.cards`** (verso filter, RetinaNet crop, show-through suppression) is
  **off by default** and calibrated on one library's scans. Never assume it
  transfers to another collection unchanged.
- **`paratext carbon` / `run --green`** is opt-in carbon-aware scheduling; the grid
  region is declared in `[carbon]`, never auto-detected. Stdlib `urllib` only.
- **Config keys are kebab-case** (`base-url`), matching the CLI flag that sets
  them. Snake_case still parses so old configs work, but generate kebab-case.
- **Bump `schema_version`** when a schema changes.
- **Commits:** short messages, no Co-Authored-By trailer.

## Tasks in this repo are public

This repository is public, and `.helical/` is committed with it. Task titles,
descriptions and notes are visible to anyone.

Keep repo tasks to engineering work. Anything naming NLS internals, staff,
suppliers, unannounced plans or licensing negotiations belongs in the
`paratext-nls` board or the `admin` project instead.

<!-- HELICAL START -->
## Tasks

This project's tasks live in `.helical/tasks/` and are managed with the `helical`
command. Read them before starting, and record what you find.

```bash
helical ls -p <project>              # open work here
helical show <ID>                    # one task in full
helical set <ID> --status doing      # todo | doing | done
helical set <ID> --horizon next      # now | next | future
helical set <ID> --flow waiting --blocker "why"
helical new "Title" -p <project> --horizon next
```

`--json` works on every command. A task carries both a **status** (how far along)
and a **horizon** (when it matters); the routemap across all projects is built from
horizons, so set one deliberately.

**Flow** says who can unstick a task: `waiting` sits with someone else and needs
chasing, `blocked` sits with us and needs a decision. Neither is accepted without
`--blocker` explaining it.

Labels come from a fixed vocabulary; `helical new --help` lists it.

Boards: <https://helical.ai.nls.uk> · read-only <https://projects.ai.nls.uk>
<!-- HELICAL END -->
