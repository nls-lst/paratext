"""Clip manifests: one row per clip of a longer recording, shared by the
time-based sources (video now, audio next)."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def is_url(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def read_manifest(path: Path) -> list[dict]:
    """Rows of a ``.jsonl`` or ``.csv`` manifest as clips: ``id`` and ``src`` (a
    path relative to the manifest, or a URL), optionally ``start`` and ``end`` in
    seconds, ``poster`` and ``label``."""
    if path.suffix.lower() == ".csv":
        with path.open(newline="") as f:
            rows = [{k: v for k, v in r.items() if v not in (None, "")} for r in csv.DictReader(f)]
    else:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    clips = []
    for i, r in enumerate(rows):
        if not r.get("id") or not r.get("src"):
            raise ValueError(f"{path.name} row {i + 1}: needs an id and a src")
        src = str(r["src"])
        if not is_url(src):
            src = str((path.parent / src).resolve())
        clip = {"id": str(r["id"]), "src": src}
        for k in ("start", "end"):
            if k in r:
                clip[k] = float(r[k])
        for k in ("poster", "label"):
            if k in r:
                clip[k] = r[k]
        clips.append(clip)
    return clips
