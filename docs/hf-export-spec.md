# Spec: `paratext export` — publish a reviewed round as a Hugging Face dataset

Status: **v1 implemented** (`paratext export`, `hf_export.py`). This doc is the
design + roadmap; sections marked "future"/"v2" are not yet built. Owner: NLS.

## Goal

Turn a human-reviewed review round (`review/<project>-r<N>/` + its
`annotations.db`) into a versioned, well-documented dataset on the Hugging Face
Hub — usable both as a **training contribution** for other libraries and as a
**benchmark** to run other/smaller models over the same material.

Design principles:

- **Minimal flags.** One command, ~4 flags; everything else in config with sane
  defaults.
- **Private by default.** Publishing is an explicit opt-in and is **blocked
  without a license** in config.
- **Zero new dependencies.** `huggingface-hub` is already a core dep; we use the
  imagefolder + `metadata.jsonl` convention so we never pull in `datasets`.
- **Provenance is the product.** The value to other institutions is trust: what
  model, what prompt, how it was reviewed, how accurate, under what rights, and
  (later) on what energy.

## Command & flags

```
paratext export -p <project> [--to <repo_id>] [--round N] [--public] [--dry-run]
```

- `-p/--project` — project (inferred from config if only one is set).
- `--to <repo_id>` — HF repo (`org/name`); defaults to `export.repo` in config.
- `--round N` — which review round to export; defaults to the **latest reviewed**
  round for the project.
- `--public` — publish publicly; default is a **private** repo. Requires a
  license (see gate).
- `--dry-run` — build the export folder locally and print a summary; do **not**
  create/push a repo. The obvious "let me look before I publish" path.

Everything else — license, inclusion policy, annotator handling — lives in
config so the command stays tiny.

## Config

```toml
[project.index-cards.export]
repo        = "nls-lst/advocates-index-cards"
license     = "cc-by-4.0"        # SPDX-ish id; REQUIRED before any public push
min-verdict = "good_enough"      # lowest verdict to include as gold (see policy)
include-negatives = false        # also export not_accurate rows as hard negatives
annotators  = "omit"             # omit | pseudonym | name  (privacy default: omit)
```

Defaults if the section is absent: `min-verdict = "good_enough"` (the only
gold-producing verdict until structured corrections exist),
`include-negatives = false`, `annotators = "omit"`, `license` unset (blocks
public).

## License gate

- **Public push** (`--public`, or `export.public = true`): hard-error unless
  `export.license` is set and non-empty. The message points at
  `paratext config`. No network call happens before this check.
- **Private push**: license optional but **warned** ("no license set — this
  dataset can't be made public until one is added").
- The license id flows into the dataset card's YAML front matter (`license:`),
  which is what the Hub reads.

## Gold-label derivation (the crux)

For each sample in the round, read its annotation from `annotations.db` (keyed by
`(dataset, sample_id)`):

- `model_correct` ∈ `{good_enough, needs_tweaks, not_accurate}` or `None`
  (unreviewed) — the reviewer's verdict.
- `notes` — a **free-text general comment** (this is how staff actually interact
  today; a streamlined single box, not per-field edits).
- `corrections` — a JSON-blob column keyed by field name that *exists* in the
  store but is **not populated by the current review UI** (there is no
  structured per-field correction control yet). Treat it as future-only.

**v1 reality (no structured corrections):** we cannot synthesise a corrected
label from a free-text note, so the clean gold set is the **`good_enough`** rows
— model output a human verified as correct as-is. `needs_tweaks`/`not_accurate`
have a note saying *something* is off but not *what the right answer is*, so they
are not labelled examples.

Inclusion policy (v1):

| Verdict | Action | `_label_status` |
|---|---|---|
| `good_enough` | include; gold = model output as-is | `verified` |
| `needs_tweaks` | exclude from gold; optionally emit to a **review queue** with its note | — |
| `not_accurate` | exclude; with `include-negatives`, emit as a hard negative (gold = null) + note | `rejected` |
| unreviewed (`None`) | exclude (only human-checked rows ship) | — |

So `min-verdict` effectively defaults to `good_enough` in v1. The reviewer's
`notes` ride along on every exported/queued row as `_review_note` — useful
context even when the row isn't gold.

**Future upgrade (needs a review-UI feature first):** add a structured per-field
correction control to the review app that writes the `corrections` blob
(`{field: corrected_value}`). Then `needs_tweaks` rows become mergeable gold
(`{**model_output, **corrections}`), `_label_status = "corrected"`, and
`min-verdict = "needs_tweaks"` starts including them. The export format below
already reserves `_label_status`/`_corrected_fields` so this needs no card change
— it just starts populating them. **Out of scope for the first export version.**

The `--dry-run` summary prints the counts (gold / queued / excluded by reason) so
the operator sees exactly what would publish.

## Repository layout (imagefolder + metadata.jsonl)

Dependency-free; the Hub auto-renders it as a browsable dataset.

```
<repo>/
  README.md                       # auto-generated dataset card
  images/<sample_id>.jpg          # the review images, reused as-is
  metadata.jsonl                  # one row per included sample
```

`metadata.jsonl` row (index-cards example):

```json
{
  "file_name": "images/000123.jpg",
  "heading": "Scott, Sir Walter",
  "heading_type": "person",
  "ms_no": "5538",
  "entries": [{"ms_no": "5538", "folios": ["f.1"], "description": "..."}],
  "_label_status": "verified",
  "_verdict": "good_enough",
  "_review_note": "",
  "_sample_id": "000123",
  "_document_id": "000123",
  "_prompt_hash": "3af1c2e9b0d4",
  "_schema_version": "v3",
  "_round": 3,
  "_model": "Qwen3-VL-30B"
}
```

The schema fields are top-level columns (so the Hub shows them as dataset
columns); paratext-internal provenance is `_`-prefixed. `_review_note` carries
the reviewer's free-text comment. `_corrected_fields` (which fields a human
changed) is reserved for the future structured-corrections upgrade and is absent
in v1.

**Multi-image records** — v1 targets single-image projects (index-cards) and
uses just `file_name`. Multi-image projects (monographs: several pages per
document) are **rejected in v1** with a clear message; in v2 they use
`file_name` = primary image + an `images: ["images/..", ...]` array column (the
format reserves it). See resolved decision 2.

**Annotator privacy:** per `export.annotators` — `omit` (default, no annotator
column), `pseudonym` (stable hash), or `name` (verbatim). Never publish names by
default.

## Dataset card (auto-generated `README.md`)

Note terminology: a **dataset card** (README of a `dataset` repo) — distinct
from a *model* card. Energy/environmental provenance belongs here and is
increasingly expected on datasets.

YAML front matter:

```yaml
---
license: cc-by-4.0            # from config; required for public
pretty_name: Advocates' Manuscript Index Cards (NLS)
task_categories: [image-to-text]
tags: [paratext, library-metadata, index-cards, glam]
size_categories: [n<1K]
---
```

Body sections, all populated from data we already track:

1. **Description** — one paragraph, from the project.
2. **Schema** — field table (name, type, description) rendered from the Pydantic
   model (reuse the `view`/schema introspection that already builds `view.json`).
3. **How it was labelled** — model id, the full prompt inline in a collapsed
   `<details>` block + its `prompt_hash`, the review process (staff verdict +
   free-text note; no per-field corrections in v1), the inclusion policy (gold =
   `good_enough`), and headline **accuracy** and verdict counts (reuse the review
   server's `_api_stats` computation).
4. **Provenance** — paratext version, git commit, schema version, round number,
   extraction date range.
5. **Environmental provenance** *(if recorded — see below)* — grid zone, average
   carbon intensity and renewable share during extraction, and whether the run
   was scheduled to a low-carbon window.
6. **Rights & license** — the configured license + a rights statement the
   operator must set. Blank-by-design for public until filled.
7. **Limitations** — collection scope, single-institution, model biases.
8. **Citation** — auto BibTeX stub.

## Environmental provenance (forward-compat with the carbon feature)

This ties the two features together and answers "is the card the right place?" —
**yes, the dataset card.** Plan:

- At **extract** time, if a carbon provider is configured, record a reading into
  the JSONL `_provenance` header alongside model/prompt/commit:
  `energy = {provider, zone, carbon_gco2, renewable_fraction, ts,
  scheduled_window: bool}`.
- On **export**, aggregate `energy` across the round's source run(s) → the card's
  "Environmental provenance" section ("Produced on the GB grid at avg 78%
  renewable / 120 gCO₂·kWh⁻¹, Carbon Intensity API; scheduled to greenest 2h
  window"). If no reading exists, the section is omitted.

**Implemented:** `run --green` (see `carbon.py`) records this `energy` block into
provenance, and the export card renders an "Environmental provenance" section
when present; absent otherwise.

### Grid zone: sub-national precision, declare-don't-detect

Precision matters: NLS's box sits in the **South Scotland** DNO region, which is
exactly why the grid was so wind-heavy. Coarse "GB" would miss that. The UK
Carbon Intensity API has a **regional** endpoint — 14 GB DNO regions (North
Scotland and South Scotland are separate) via `/regional/regionid/{id}` or
`/regional/postcode/{outcode}` (e.g. `EH`) — so we can and should pin the region.

There's no reliable way to auto-detect whether a `base-url` is local (the same
box is `localhost:8000` and `api.ai.nls.uk`), so carbon-aware is opt-in by
declaring the region in config:

```toml
[carbon]
provider = "uk"            # uk (Carbon Intensity) | electricitymaps | watttime
region   = "south-scotland"  # or a UK outcode like "EH"; sub-national for uk
```

**IP → region: derive-to-*suggest*, not at runtime.** We can offer a convenience
in `paratext config`/setup: call an IP-geolocation service (ipinfo/ip-api) on the
box's public IP → lat-long/outcode → map to the Carbon Intensity region, and
**propose** it ("looks like South Scotland — use this?"). The operator confirms
and it's written to config once. We deliberately do **not** geolocate silently at
run time, because:

- Server IP-geo often reflects the ISP/hosting registration, not the physical
  site, and can't reliably split North vs. South Scotland — the very precision we
  want. A wrong guess would silently mislabel the dataset's energy provenance.
- It needs an external call + public IP; isolated networks break it.

So: IP-geo is a first-run *suggestion* to make config easy; the committed
`region` value is the source of truth. (Electricity Maps/WattTime zones are
coarser than the UK regional API; for sub-national UK, prefer `provider = "uk"`.)

## Implementation notes

- New module `paratext/hf_export.py`; new `export` subcommand in `cli.py`.
- Reuse: `discover_datasets`/`load_samples` and the `Store` from
  `paratext.review.server` to read the round + annotations; the schema/`view`
  introspection for the field table; `_api_stats`' accuracy math (factor it out
  so both the server and the card call it).
- Push via `huggingface_hub.HfApi`: `create_repo(repo_type="dataset",
  private=not public, exist_ok=True)` then `upload_folder(...)`. Auth from
  `HF_TOKEN`/`huggingface-cli login` (document it). **No `datasets` dependency.**
- Build into a temp dir (scratch), then upload; `--dry-run` stops before upload
  and prints the path + summary.

## Benchmark follow-on (not this pass)

The exported artifact *is* a benchmark (image + gold + provenance). A later
`paratext bench <hf-dataset> --model X` = `extract` over the dataset's images +
the same `_api_stats` scoring against the gold labels. Note only; out of scope
here.

## Resolved decisions

1. **Prompt in the card — inline, collapsed.** The prompt *is* the labelling
   methodology and the single most useful provenance item, so it travels with the
   data: the full text goes in a collapsed `<details>` block in the card, with the
   12-char `prompt_hash` as a short line for cross-referencing rounds. A
   hash/link-only approach is useless to anyone who can't see the source repo.
2. **Multi-image — index-cards (single-image) in v1; monographs in v2.** HF's
   imagefolder is one-image-per-row, which fits index-cards exactly (one card =
   one image = one label) and is the immediate target. Monographs (many page
   images per document) need the `images[]` array column, which the Hub viewer
   renders less cleanly; the format reserves that column so v2 is purely additive.
   Multi-image projects are rejected by `export` in v1 with a clear message.
3. **Versioning — one repo, rounds as Hub revisions + a `_round` column.** Each
   export is a new git revision of the same repo; the `_round`/date columns keep
   rows distinguishable and let a consumer pin an exact round, while "latest"
   stays the default. This matches how HF datasets evolve and keeps one citable
   artifact. Repo-per-round only if a round must be *simultaneously public and
   frozen* (a benchmark) — better served by tagging a revision anyway.
```
