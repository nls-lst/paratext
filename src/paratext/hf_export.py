"""`paratext export` — publish a reviewed round as a Hugging Face dataset.

Turns a `review/<project>-r<N>/` round plus its `annotations.db` into an
imagefolder + `metadata.jsonl` dataset with an auto-generated dataset card, then
(optionally) pushes it to the Hub. Design points (see docs/hf-export-spec.md):

- **Private by default**; `--public` is opt-in. A licence is strongly steered —
  `export` prompts for one when none is set — but never blocks publishing.
- **v1 gold = `good_enough` rows only** — the review UI records a free-text note,
  not structured per-field corrections, so `needs_tweaks`/`not_accurate` can't be
  turned into labels yet. Their note rides along for context.
- **Single-image projects only in v1** (index-cards); multi-image (monographs) is
  rejected with a clear message.
- **No new dependency**: uses the already-present `huggingface_hub`.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_project_section
from .projects import get_project
from .records import select_records
from .review.server import review_stats

# HF Hub licence ids are a controlled, SPDX-like vocabulary — the Hub only renders
# a tag it recognises (so `cc0`, unversioned, would NOT show as a licence; use
# `cc0-1.0`). Recommended for NLS outputs: cc0-1.0, cc-by-4.0, apache-2.0. This is
# the common subset we recognise silently; anything else gets a soft warning, not a
# rejection. Full list: https://huggingface.co/docs/hub/repositories-licenses
KNOWN_LICENSES = frozenset({
    "apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "isc",
    "gpl-2.0", "gpl-3.0", "lgpl-2.1", "lgpl-3.0", "agpl-3.0", "mpl-2.0", "unlicense",
    "cc0-1.0", "cc-by-4.0", "cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nd-4.0",
    "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0", "cc-by-3.0", "cc-by-sa-3.0",
    "cdla-permissive-2.0", "cdla-sharing-1.0", "odc-by", "odbl", "pddl",
    "openrail", "other", "unknown",
})

# Forgiving shorthands → canonical HF id, so `--license cc0` / a config typo works.
_LICENSE_ALIASES = {
    "cc0": "cc0-1.0", "cc-0": "cc0-1.0", "cc-by": "cc-by-4.0", "ccby": "cc-by-4.0",
    "cc-by-sa": "cc-by-sa-4.0", "cc-by-nc": "cc-by-nc-4.0", "cc-by-nd": "cc-by-nd-4.0",
    "apache": "apache-2.0", "apache2": "apache-2.0", "apache-2": "apache-2.0",
    "bsd": "bsd-3-clause", "bsd-3": "bsd-3-clause", "gpl": "gpl-3.0", "gpl3": "gpl-3.0",
    "lgpl": "lgpl-3.0", "agpl": "agpl-3.0", "mpl": "mpl-2.0",
}


def normalise_license(value: str | None) -> str | None:
    """Canonicalise a licence id: lower-case, strip, expand common shorthands.

    Returns the (possibly unchanged) value; unknown ids pass through so the caller
    can soft-warn rather than reject.
    """
    if not value:
        return value
    v = value.strip().lower()
    return _LICENSE_ALIASES.get(v, v)

# Where local export folders are built (inspectable; --dry-run stops here).
EXPORT_ROOT = Path("export")


@dataclass
class ExportConfig:
    repo: str | None = None
    license: str | None = None
    rights: str | None = None  # free-text rights statement for the card (overrides default)
    min_verdict: str = "good_enough"
    include_negatives: bool = False
    annotators: str = "omit"  # omit | pseudonym | name
    public: bool = False


def load_config(
    project: str, *, repo: str | None, public: bool,
    license: str | None = None, rights: str | None = None,
) -> ExportConfig:
    """Build the export config from `[project.<name>.export]`, with CLI overrides."""
    raw = load_project_section(project, "export")
    cfg = ExportConfig(
        repo=repo or raw.get("repo"),
        license=license or raw.get("license"),
        rights=rights or raw.get("rights"),
        min_verdict=raw.get("min_verdict", "good_enough"),
        include_negatives=bool(raw.get("include_negatives", False)),
        annotators=raw.get("annotators", "omit"),
        public=public or bool(raw.get("public", False)),
    )
    return cfg


@dataclass
class ExportSummary:
    dataset: str
    gold: int
    negatives: int
    corrected: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    build_dir: Path | None = None
    repo: str | None = None
    url: str | None = None
    provenance_missing: list[str] = field(default_factory=list)


# Card fields sourced from the round's provenance.json; if any are absent the
# dataset card reads "unknown"/blank, so export warns before publishing.
_PROVENANCE_FIELDS = ("model", "prompt_hash", "schema_version", "prompt")


def missing_provenance(provenance: dict) -> list[str]:
    return [k for k in _PROVENANCE_FIELDS if not provenance.get(k)]


def provenance_gaps(dataset_dir: Path) -> list[str]:
    """Which provenance fields the round is missing (empty = complete)."""
    pfile = dataset_dir / "provenance.json"
    prov = json.loads(pfile.read_text()) if pfile.is_file() else {}
    return missing_provenance(prov)


def _rows(dataset_dir: Path, project: str, cfg: ExportConfig, *, db_path: Path | None = None):
    """Yield (metadata_row, source_image_path) for included samples, plus a
    running tally of what was excluded and why. Raises on multi-image projects.

    Selection (which items are gold) is shared with the other export formats via
    `records.select_records`; here we add the image-count rules and the HF row shape.
    `db_path` points at the gold DB when it isn't the round's own annotations.db
    (the review service keeps it at `--db`) — same fix the catalogue exports got.
    """
    sel = select_records(
        dataset_dir,
        project,
        min_verdict=cfg.min_verdict,
        include_negatives=cfg.include_negatives,
        annotators=cfg.annotators,
        db_path=db_path,
    )
    excluded = dict(sel.excluded)
    rows: list[dict] = []
    images: list[Path] = []

    for rec in sel.records:
        if len(rec.images) > 1:
            raise SystemExit(
                f"'{project}' has multi-image records (sample {rec.sid} has "
                f"{len(rec.images)}). v1 HF export supports single-image projects only "
                "(e.g. index-cards); use --format marc/dc for multi-image, or v2."
            )
        if not rec.images:
            excluded["no_image"] = excluded.get("no_image", 0) + 1
            continue

        src = rec.images[0]  # resolved: <round>/images/<id>/image.jpg
        ext = src.suffix or ".jpg"
        row = {"file_name": f"images/{rec.sid}{ext}"}
        for f in sel.schema_fields:
            row[f] = rec.label.get(f)
        row["_label_status"] = rec.status
        if rec.status == "corrected":
            row["_corrected_fields"] = rec.corrected_fields
        row["_verdict"] = rec.verdict
        row["_review_note"] = rec.note
        row["_sample_id"] = rec.sid
        row["_document_id"] = rec.document_id
        row["_prompt_hash"] = rec.prompt_hash
        row["_schema_version"] = sel.provenance.get("schema_version")
        row["_round"] = sel.round
        row["_model"] = sel.provenance.get("model")
        if rec.annotator:
            row["_annotator"] = rec.annotator

        rows.append(row)
        images.append(src)

    return rows, images, excluded, sel.provenance, sel.samples, sel.store, sel.name


def _type_str(annotation) -> str:
    s = str(annotation)
    s = re.sub(r"<class '([^']+)'>", r"\1", s)
    return s.replace("typing.", "").replace("NoneType", "None")


def _size_category(n: int) -> str:
    if n < 1_000:
        return "n<1K"
    if n < 10_000:
        return "1K<n<10K"
    if n < 100_000:
        return "10K<n<100K"
    return "100K<n<1M"


def _dataset_card(
    project: str, cfg: ExportConfig, provenance: dict, stats: dict, n_gold: int,
    n_verified: int = 0, n_corrected: int = 0,
) -> str:
    proj = get_project(project)
    pretty = project.replace("-", " ").replace("_", " ").title()
    # Front-matter stays honest: `other` when unset (never assert a licence the
    # publisher didn't choose). The Rights section then steers toward CC0.
    canon = normalise_license(cfg.license)
    lic = canon or "other"
    # A project can set an explicit `rights` statement; otherwise a licence-aware
    # default (no unfinished-TODO boilerplate). Front matter is set separately.
    if cfg.rights:
        rights_body = cfg.rights
    elif canon:
        rights_body = (
            f"Released under [`{canon}`](https://spdx.org/licenses/{canon}.html) — "
            "labels and images alike. If your collection includes third-party material, "
            "confirm the image rights position before reuse."
        )
    else:
        rights_body = (
            "No licence set (front matter records `license: other`). **CC0-1.0** is "
            "recommended for open sharing — pass `--license`/`--rights` to "
            "`paratext export` or set them under `[project.<name>.export]`."
        )

    front = [
        "---",
        f"license: {lic}",
        f"pretty_name: {pretty}",
        "task_categories:",
        "  - image-to-text",
        "tags:",
        "  - paratext",
        "  - library-metadata",
        f"  - {project}",
        "size_categories:",
        f"  - {_size_category(n_gold)}",
        "---",
        "",
    ]

    # Schema field table from the Pydantic model.
    rows = ["| Field | Type | Description |", "| --- | --- | --- |"]
    for fname, fdef in proj.schema.model_fields.items():
        desc = (fdef.description or "").replace("|", "\\|").replace("\n", " ")
        rows.append(f"| `{fname}` | `{_type_str(fdef.annotation)}` | {desc} |")
    schema_table = "\n".join(rows)

    acc = stats["model"]["accuracy"]
    acc_str = f"{acc:.1f}%" if acc is not None else "n/a"
    prompt = provenance.get("prompt", "")

    energy = provenance.get("energy")
    energy_section = ""
    if energy:
        bits = []
        if energy.get("renewable_fraction") is not None:
            bits.append(f"{energy['renewable_fraction'] * 100:.0f}% renewable")
        if energy.get("carbon_gco2") is not None:
            bits.append(f"{energy['carbon_gco2']:.0f} gCO₂/kWh")
        summary = ", ".join(bits) or "recorded"
        sched = " (scheduled to a low-carbon window)" if energy.get("scheduled_window") else ""
        energy_section = (
            f"\n## Environmental provenance\n\n"
            f"Extraction ran on the **{energy.get('zone', 'unknown')}** grid at "
            f"{summary}{sched}, per the {energy.get('provider', 'carbon')} data "
            f"({energy.get('ts', 'n/a')}).\n"
        )

    body = f"""# {pretty}

Catalogue metadata extracted from digitised material with a multimodal model and
human-reviewed.

## Schema

{schema_table}

The exact machine-readable output schema (enum values, nested objects, optionality)
is in [`schema.json`](schema.json) — the `response_format` the labels follow.

## How it was labelled

- **Model:** `{provenance.get("model", "unknown")}`
- **Prompt hash:** `{provenance.get("prompt_hash", "unknown")}`
- **Schema version:** `{provenance.get("schema_version", "unknown")}`
- **Review:** each item was shown to a human reviewer who gave a verdict and an
  optional free-text note. **Gold labels are the {n_gold} items a human signed
  off:** {n_verified} _verified_ (model output a reviewer marked good enough) and
  {n_corrected} _corrected_ (a reviewer edited the fields into the right answer).
  Each row's `_label_status` (`verified` / `corrected`) and, for corrected rows,
  `_corrected_fields` record which is which.
- **Model baseline (for benchmarking — not the label quality):** the labels above are
  fully human-verified, so this figure describes the *generating* model, not the
  dataset. It agreed with reviewers on **{acc_str}** of {stats["model"]["scored"]}
  scored items (good_enough={stats["model"]["good_enough"]},
  needs_tweaks={stats["model"]["needs_tweaks"]},
  not_accurate={stats["model"]["not_accurate"]}; needs_tweaks scored as half credit) —
  a reference point for scoring other models against this set.

<details>
<summary>Extraction prompt</summary>

```
{prompt}
```

</details>

## Provenance

Produced by paratext. Each row carries `_label_status`, `_verdict`,
`_prompt_hash`, `_schema_version`, `_round`, `_model`, and the reviewer's
`_review_note` (plus `_corrected_fields` on corrected rows).
{energy_section}
## Rights & license

{rights_body}

## Limitations

Single-institution scope; labels reflect one model + prompt at a point in time and
the reviewing institution's cataloguing conventions.
"""
    return "\n".join(front) + body


def build(
    dataset_dir: Path, project: str, cfg: ExportConfig, dest: Path,
    *, db_path: Path | None = None,
) -> ExportSummary:
    """Build the export folder (imagefolder + metadata.jsonl + card) at `dest`."""
    rows, images, excluded, provenance, samples, store, name = _rows(
        dataset_dir, project, cfg, db_path=db_path
    )
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "images").mkdir(parents=True, exist_ok=True)

    for row, src in zip(rows, images):
        shutil.copyfile(src, dest / row["file_name"])

    with (dest / "metadata.jsonl").open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # The machine-readable output schema (field names, types, enum values, nested
    # objects, optionality) — so a downstream eval/bench harness has the exact
    # response_format the labels follow, not just the card's prose table.
    (dest / "schema.json").write_text(
        json.dumps(get_project(project).schema.model_json_schema(), indent=2, ensure_ascii=False)
    )

    gold_ids = {g["sample_id"] for g in store.all_gold(name)}
    stats = review_stats(len(samples), store.all(name), gold_ids)
    verified = sum(1 for r in rows if r["_label_status"] == "verified")
    corrected = sum(1 for r in rows if r["_label_status"] == "corrected")
    negatives = sum(1 for r in rows if r["_label_status"] == "rejected")
    gold = verified + corrected
    (dest / "README.md").write_text(
        _dataset_card(project, cfg, provenance, stats, gold, verified, corrected)
    )

    return ExportSummary(
        dataset=name, gold=gold, corrected=corrected, negatives=negatives,
        excluded=excluded, build_dir=dest,
        provenance_missing=missing_provenance(provenance),
    )


def push_built(dest: Path, cfg: ExportConfig, summary: ExportSummary, *, token: str | None = None):
    """Create the dataset repo (if needed) and upload a built folder. `token`
    lets a caller push as a specific user (the review UI's OAuth flow); None
    falls back to the ambient token (env / HF cache) the CLI uses. Sets
    `summary.repo`/`summary.url`."""
    if not cfg.repo:
        raise ValueError("no target repo: pass a repo id (org/name) or set export.repo in config")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(
        repo_id=cfg.repo, repo_type="dataset", private=not cfg.public, exist_ok=True
    )
    api.upload_folder(
        folder_path=str(dest),
        repo_id=cfg.repo,
        repo_type="dataset",
        commit_message=f"paratext export: {summary.dataset} ({summary.gold} gold)",
    )
    summary.repo = cfg.repo
    summary.url = f"https://huggingface.co/datasets/{cfg.repo}"
    return summary


def run(dataset_dir: Path, project: str, cfg: ExportConfig, *, dry_run: bool) -> ExportSummary:
    """Build the export and, unless `dry_run`, push it to the Hub."""
    cfg.license = normalise_license(cfg.license)
    if cfg.license and cfg.license not in KNOWN_LICENSES:
        print(f"warning: '{cfg.license}' isn't a recognised HF licence id — the Hub "
              "may not display it. Common ids: cc0-1.0, cc-by-4.0, apache-2.0.")
    dest = EXPORT_ROOT / dataset_dir.name
    summary = build(dataset_dir, project, cfg, dest)

    if summary.provenance_missing:
        print(f"note: no recorded provenance for {', '.join(summary.provenance_missing)} — "
              "publishing anyway; the dataset card shows 'unknown'/blank for these until you fill "
              "them in on the Hub (or re-package the round with a provenance.json).")

    if dry_run:
        return summary
    if not cfg.repo:
        raise SystemExit("no target repo: pass --to <org/name> or set export.repo in config")
    if not cfg.license:
        vis = "publicly" if cfg.public else "privately"
        print(f"warning: publishing {vis} with no licence set — the dataset card shows "
              "`license: other`. Add a licence (e.g. cc0-1.0) to make reuse terms clear.")
    return push_built(dest, cfg, summary)
