"""Convert an extraction JSONL into the review dataset layout (samples.json + images/ + view.json).

Output:
    <out-dir>/
        samples.json            one record per kept sample
        samples-ephemera.json   quarantined records (if any), recoverable
        view.json               the display/review contract (if the project
                                defines a View)
        images/<sample_id>/     materialised review images

The packager is project-agnostic: it loops the JSONL and delegates the four
project-specific decisions to hooks on the project (see `Project` in
`projects/__init__.py`). When a project supplies no hook, a generic default is
used (keep everything; one image per record from `metadata.image_path`).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from PIL import Image

from .io import iter_records, read_provenance
from .projects import KEEP, Curation, build_view, get_project

logger = logging.getLogger(__name__)


def save_image(src_path: Path, dest_path: Path, max_size: int = 1024) -> None:
    """Downsample an image to `max_size` and write it as JPEG. A framework
    helper projects can reuse from their `materialise_images` hook."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src_path).convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    img.save(dest_path, format="JPEG", quality=85)


# ── Generic defaults (used when a project supplies no matching hook) ─────────
def _default_curate(rec: dict) -> Curation:
    return KEEP


def _default_materialise(rec: dict, out: Path, max_size: int) -> list[str]:
    src = (rec.get("metadata") or {}).get("image_path")
    if src and Path(src).exists():
        rel = f"images/{rec['id']}/image.jpg"
        save_image(Path(src), out / rel, max_size)
        return [rel]
    return []


def _default_build_record(rec: dict, images_rel: list[str]) -> dict:
    return {
        "id": rec["id"],
        "document_id": rec["id"],
        "model_output": rec.get("extraction") or {},
        "images": images_rel,
    }


def package(
    jsonl: Path,
    out: Path,
    project: str,
    *,
    fresh: bool = False,
    image_max_size: int = 1024,
) -> tuple[int, dict[str, int]]:
    """Write samples.json + images/ for `paratext review`. Returns (kept, skipped_by_reason)."""
    proj = get_project(project)
    if fresh and out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True, exist_ok=True)

    provenance = read_provenance(jsonl)
    prompt_text = provenance.get("prompt", "")
    prompt_hash = provenance.get("prompt_hash", "")

    curate = proj.curate or _default_curate
    materialise = proj.materialise_images or _default_materialise
    build_record = proj.build_record or _default_build_record
    ground_truth = proj.ground_truth

    skipped: dict[str, int] = {}
    records: list[dict] = []
    quarantined: list[dict] = []  # recoverable, not reviewed (e.g. ephemera)

    for rec in iter_records(jsonl):
        decision = curate(rec)
        if decision.action == "drop":
            key = decision.reason or "dropped"
            skipped[key] = skipped.get(key, 0) + 1
            continue

        images_rel = materialise(rec, out, image_max_size)
        r = build_record(rec, images_rel)
        r["schema"] = proj.name
        r["prompt"] = prompt_text
        r["prompt_hash"] = prompt_hash
        if ground_truth is not None:
            gt = ground_truth(rec)
            if gt:
                r["ground_truth"] = gt

        if decision.action == "quarantine":
            key = decision.reason or "quarantined"
            skipped[key] = skipped.get(key, 0) + 1
            quarantined.append(r)
        else:
            records.append(r)

    (out / "samples.json").write_text(json.dumps(records, indent=2, ensure_ascii=False))
    if quarantined:
        (out / "samples-ephemera.json").write_text(
            json.dumps(quarantined, indent=2, ensure_ascii=False)
        )

    # Emit the per-dataset display/review contract (defaults to all schema
    # fields when the project defines no view).
    (out / "view.json").write_text(
        json.dumps(build_view(proj), indent=2, ensure_ascii=False)
    )

    return len(records), skipped
