# Spec: `paratext export` — publish a reviewed round as a Hugging Face dataset

Status: design (not yet implemented). Owner: NLS. Target: framework (`paratext`).

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
min-verdict = "needs_tweaks"     # lowest verdict to include (see policy)
include-negatives = false        # also export not_accurate rows as hard negatives
annotators  = "omit"             # omit | pseudonym | name  (privacy default: omit)
```

Defaults if the section is absent: `min-verdict = "needs_tweaks"`,
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

For each sample in the round, combine the model output with its annotation from
`annotations.db` (keyed by `(dataset, sample_id)`):

- `model_correct` ∈ `{good_enough, needs_tweaks, not_accurate}` or `None`
  (unreviewed).
- `corrections` — generic JSON keyed by **schema field name**; a corrected value
  replaces that whole field. (Matches how the review UI writes it: per-field,
  whole-value.)

Gold value = `model_output` overlaid with `corrections`
(`{**model_output, **corrections}` at the field level).

Inclusion policy:

| Verdict | Corrections? | Action | `_label_status` |
|---|---|---|---|
| `good_enough` | — | include, gold = model output (+any corrections) | `verified` |
| `needs_tweaks` | yes | include, gold = merged | `corrected` |
| `needs_tweaks` | **no** | **exclude** (label untrustworthy), count `needs_tweaks_uncorrected` | — |
| `not_accurate` | — | exclude by default; with `include-negatives`, include gold=merged-or-null | `rejected` |
| unreviewed (`None`) | — | exclude (only human-checked rows ship) | — |

`min-verdict` gates the ordinal (`good_enough` > `needs_tweaks`): setting it to
`good_enough` ships only fully-approved rows; the default `needs_tweaks` also
ships human-corrected rows. `needs_tweaks`-without-corrections is *always*
excluded regardless of `min-verdict`.

The `--dry-run` summary prints these counts (included / corrected / excluded by
reason) so the operator sees exactly what would publish.

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
  "_label_status": "corrected",
  "_verdict": "needs_tweaks",
  "_corrected_fields": ["heading", "ms_no"],
  "_sample_id": "000123",
  "_document_id": "000123",
  "_prompt_hash": "3af1c2e9b0d4",
  "_schema_version": "v3",
  "_round": 3,
  "_model": "Qwen3-VL-30B"
}
```

The schema fields are top-level columns (so the Hub shows them as dataset
columns); paratext-internal provenance is `_`-prefixed. `_corrected_fields`
(which fields the human changed) is deliberately surfaced — it's gold for
error-analysis and for the card's "where the model struggles" section.

**Multi-image records** (monographs: several pages per document; card runs that
continue across cards): `file_name` = the primary/first image; any extras go in
an `images: ["images/..","images/.."]` array column. Single-image projects
(index-cards, the immediate target) use just `file_name`.

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
3. **How it was labelled** — model id, prompt hash (+ the prompt text or a link),
   the review process, the verdict/inclusion policy, headline **accuracy** and
   verdict counts (reuse the review server's `_api_stats` computation), and the
   most-frequently `_corrected_fields`.
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

Until the carbon feature lands the field is simply absent; the export spec just
**reserves the slot** so no card format change is needed later.

### Local vs. remote endpoint (open question, answered: *declare, don't detect*)

There's no reliable way to auto-detect whether a `base-url` is local — the same
box is reachable as `localhost:8000` and `api.ai.nls.uk`. So don't try. Instead,
carbon-aware behaviour is opt-in **by declaring the grid zone** in config
(`[carbon] zone = "GB"`). Presence of a zone = "I know where my compute runs;
gate/record against this grid." For a remote endpoint whose datacenter is
elsewhere, the operator sets the zone to that datacenter's grid. The
local/remote distinction dissolves into a single value the operator owns.
(Optional nicety: warn if `base-url` host isn't loopback and no zone override is
set — but never guess.)

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

## Open decisions

1. **Prompt in the card**: inline the full prompt text, or link to it by hash?
   (Leaning: inline, collapsed — it's the single most useful provenance item.)
2. **Multi-image UX** on the Hub for monographs — accept the `images[]` array
   column, or hold monographs back to a v2? (Leaning: index-cards single-image
   for v1; monographs v2.)
3. **Versioning**: one repo with a `_round`/date column and Hub revisions, or a
   repo-per-round? (Leaning: one repo, rounds as revisions + a column.)
```
