"""Format-neutral selection of the human-approved (gold) records for a reviewed
round. Shared by every export format (`hf_export`, `catalogue`) so they all ship
the same set: `good_enough` rows (verified) plus human-corrected rows from the
`gold_labels` table (corrected), with negatives optional.

Each format then renders `Record.label` its own way — an HF metadata row, a MARC
record, a Dublin Core element set — without re-deriving the selection.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .projects import schema_fields_for
from .store import Store, default_db_path

# Verdict ordering for the min-verdict gate (higher = more approved).
_VERDICT_ORDER = {"not_accurate": 0, "needs_tweaks": 1, "good_enough": 2}


def _round_of(dataset_name: str) -> int | None:
    m = re.match(r"^.*-r(\d+)$", dataset_name)
    return int(m.group(1)) if m else None


def _annotator_value(ann: dict, mode: str) -> str | None:
    who = ann.get("annotator")
    if not who or mode == "omit":
        return None
    if mode == "pseudonym":
        import hashlib

        return "anon-" + hashlib.sha256(who.encode()).hexdigest()[:8]
    return who


@dataclass
class Record:
    """One human-approved item, format-neutral. `label` maps schema field -> value
    (the gold label); negatives carry all-None. `images` are resolved source paths
    (may be empty; only HF export cares)."""

    sid: str
    document_id: str | None
    label: dict
    status: str  # verified | corrected | rejected
    verdict: str | None  # original model verdict (kept even for corrected rows)
    corrected_fields: list[str]
    note: str
    prompt_hash: str | None
    annotator: str | None
    images: list[Path] = field(default_factory=list)


@dataclass
class Selection:
    records: list[Record]
    excluded: dict[str, int]
    provenance: dict
    samples: list[dict]
    store: Store
    name: str
    round: int | None
    schema_fields: list[str]


def select_records(
    dataset_dir: Path,
    project: str,
    *,
    min_verdict: str = "good_enough",
    include_negatives: bool = False,
    annotators: str = "omit",
    db_path: Path | None = None,
) -> Selection:
    """Select the gold records for a packaged round. Image-count rules (multi-image
    rejection, no-image exclusion) are left to the caller — they are HF-specific."""
    samples = json.loads((dataset_dir / "samples.json").read_text())
    provenance = {}
    pfile = dataset_dir / "provenance.json"
    if pfile.is_file():
        provenance = json.loads(pfile.read_text())

    schema_fields = schema_fields_for(project, dataset_dir)
    # Gold may live in a store outside the dataset dir (the review service runs
    # with --db elsewhere), so callers can point at it explicitly.
    store = Store(default_db_path(dataset_dir, db_path))
    name = dataset_dir.name
    threshold = _VERDICT_ORDER.get(min_verdict, 2)

    records: list[Record] = []
    excluded: Counter[str] = Counter()

    for s in samples:
        sid = str(s["id"])
        ann = store.get(name, sid) or {}
        gold = store.get_gold(name, sid)
        verdict = ann.get("model_correct")
        model_output = s.get("model_output") or {}

        # A human-corrected row is gold regardless of its (original) verdict — that
        # verdict measured the *model*, which was wrong; the human supplied the right
        # answer. With no gold rows at all, this never fires and selection is exactly
        # the old behaviour (good_enough only).
        is_corrected = gold is not None
        if not is_corrected and verdict is None:
            excluded["unreviewed"] += 1
            continue

        is_gold = is_corrected or _VERDICT_ORDER.get(verdict, -1) >= threshold
        is_negative = not is_corrected and verdict == "not_accurate" and include_negatives
        if not (is_gold or is_negative):
            excluded[verdict] += 1
            continue

        gold_output = (gold or {}).get("output") or {}
        label = {}
        for f in schema_fields:
            if is_negative:
                label[f] = None
            elif is_corrected:
                label[f] = gold_output.get(f, model_output.get(f))
            else:
                label[f] = model_output.get(f)

        records.append(
            Record(
                sid=sid,
                document_id=s.get("document_id"),
                label=label,
                status="corrected" if is_corrected else "rejected" if is_negative else "verified",
                verdict=verdict,
                corrected_fields=(gold.get("fields") or []) if is_corrected else [],
                note=ann.get("notes") or "",
                prompt_hash=s.get("prompt_hash") or provenance.get("prompt_hash"),
                annotator=_annotator_value(ann, annotators),
                images=[dataset_dir / p for p in (s.get("images") or [])],
            )
        )

    return Selection(
        records=records,
        excluded=excluded,
        provenance=provenance,
        samples=samples,
        store=store,
        name=name,
        round=_round_of(name),
        schema_fields=schema_fields,
    )
