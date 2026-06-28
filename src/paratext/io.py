"""JSONL append, resume, provenance metadata, pre-flight checks."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

PROVENANCE_KEY = "_provenance"


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def preflight_check(base_url: str) -> list[str]:
    """Confirm the VLM server is reachable and has at least one model loaded."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=5) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(
            f"Server not reachable at {base_url} — is it running?\n  {e}"
        ) from e

    models = data.get("data") or []
    if not models:
        raise SystemExit(
            f"No model loaded at {base_url}. Load a model on your OpenAI-compatible server first."
        )
    return [m.get("id", "?") for m in models]


def write_provenance_header(path: str | Path, metadata: dict) -> None:
    """Write a one-line `_provenance` header at the top of a fresh JSONL file."""
    path = Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        PROVENANCE_KEY: {
            "git_commit": _git_commit(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **metadata,
        }
    }
    path.write_text(json.dumps(header) + "\n")


def read_provenance(path: str | Path) -> dict:
    """Return the `_provenance` dict from the header line, or {} if absent."""
    path = Path(path)
    if not path.exists():
        return {}
    with open(path) as f:
        first = f.readline().strip()
    if not first:
        return {}
    try:
        record = json.loads(first)
    except json.JSONDecodeError:
        return {}
    return record.get(PROVENANCE_KEY) or {}


def append_jsonl(path: str | Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()


def read_processed_ids(path: str | Path, id_field: str = "id") -> set[str]:
    """Return ids already present in `path` so a resumed run can skip them."""
    path = Path(path)
    if not path.exists():
        return set()
    ids: set[str] = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if PROVENANCE_KEY in record:
                continue
            if id_field in record:
                ids.add(str(record[id_field]))
    return ids


def iter_records(path: str | Path) -> Iterator[dict]:
    """Yield every non-provenance record in a JSONL file."""
    path = Path(path)
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if PROVENANCE_KEY in record:
                continue
            yield record


def append_error(path: str | Path, sample_id: str, error: str) -> None:
    path = Path(path)
    error_path = path.with_name(path.stem + "_errors" + path.suffix)
    append_jsonl(
        error_path,
        {
            "id": sample_id,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
