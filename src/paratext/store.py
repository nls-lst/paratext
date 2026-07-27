"""SQLite store for review annotations and human-corrected gold labels.

Separate from the review server because it is not web code: `paratext export`
and the catalogue/HF exporters read the same tables directly to select gold,
without starting a server. The review UI is one writer among several readers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_NAME = "annotations.db"


def default_db_path(dataset_dir: Path, db_path: Path | None = None) -> Path:
    """Where a dataset's annotations live: an explicit --db wins, else the
    dataset directory. Callers outside the server share this rule."""
    return Path(db_path) if db_path else dataset_dir / DEFAULT_DB_NAME


class Store:
    """One ``annotations`` table keyed by (dataset, sample_id). Corrections are
    a generic JSON blob keyed by field name, so any schema works."""

    def __init__(self, db_path: Path):
        # One connection shared across a ThreadingHTTPServer. check_same_thread
        # permits cross-thread use but does NOT make the connection thread-safe:
        # concurrent requests raise "bad parameter or other API misuse". The
        # stats page alone fires three fetches at once, so serialise every access.
        self._lock = threading.RLock()
        self.db_path = Path(db_path)  # so callers (e.g. export) can read the same gold
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS annotations (
                dataset TEXT NOT NULL,
                sample_id TEXT NOT NULL,
                catalogue_correct TEXT,
                model_correct TEXT,
                corrections TEXT,
                notes TEXT,
                annotator TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (dataset, sample_id)
            )"""
        )
        # Human-corrected gold labels, kept in their OWN table (additive: never
        # alters `annotations`, so pointing --db at a legacy DB is safe). A row
        # here means the reviewer built a corrected answer for that sample; it
        # becomes gold in `paratext export`. `output` is the full corrected
        # field->value map (the label); `fields` lists which keys the human
        # changed (provenance). NB the `annotations.corrections` column is a
        # different thing — handwritten corrections on the card, not this.
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS gold_labels (
                dataset TEXT NOT NULL,
                sample_id TEXT NOT NULL,
                output TEXT NOT NULL,
                fields TEXT,
                annotator TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (dataset, sample_id)
            )"""
        )
        self.db.commit()

    def _row(self, r: sqlite3.Row) -> dict:
        corrections = None
        if r["corrections"]:
            try:
                corrections = json.loads(r["corrections"])
            except json.JSONDecodeError:
                corrections = None
        return {
            "dataset": r["dataset"],
            "sample_id": r["sample_id"],
            "catalogue_correct": r["catalogue_correct"],
            "model_correct": r["model_correct"],
            "corrections": corrections,
            "notes": r["notes"],
            "annotator": r["annotator"],
            "updated_at": r["updated_at"],
        }

    def get(self, dataset: str, sample_id: str) -> dict | None:
        with self._lock:
            r = self.db.execute(
                "SELECT * FROM annotations WHERE dataset = ? AND sample_id = ?",
                (dataset, sample_id),
            ).fetchone()
            return self._row(r) if r else None

    def all(self, dataset: str | None = None) -> list[dict]:
        with self._lock:
            if dataset is None:
                rows = self.db.execute("SELECT * FROM annotations").fetchall()
            else:
                rows = self.db.execute(
                    "SELECT * FROM annotations WHERE dataset = ?", (dataset,)
                ).fetchall()
            return [self._row(r) for r in rows]

    def upsert(self, dataset: str, sample_id: str, body: dict) -> dict:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            corrections = body.get("corrections")
            self.db.execute(
                """INSERT INTO annotations (
                    dataset, sample_id, catalogue_correct, model_correct,
                    corrections, notes, annotator, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, sample_id) DO UPDATE SET
                    catalogue_correct = excluded.catalogue_correct,
                    model_correct = excluded.model_correct,
                    corrections = excluded.corrections,
                    notes = excluded.notes,
                    annotator = excluded.annotator,
                    updated_at = excluded.updated_at""",
                (
                    dataset,
                    sample_id,
                    body.get("catalogue_correct"),
                    body.get("model_correct"),
                    json.dumps(corrections) if corrections else None,
                    body.get("notes"),
                    body.get("annotator"),
                    now,
                ),
            )
            self.db.commit()
            return self.get(dataset, sample_id)

    def reset(self, dataset: str | None = None) -> None:
        with self._lock:
            if dataset is None:
                self.db.execute("DELETE FROM annotations")
                self.db.execute("DELETE FROM gold_labels")
            else:
                self.db.execute("DELETE FROM annotations WHERE dataset = ?", (dataset,))
                self.db.execute("DELETE FROM gold_labels WHERE dataset = ?", (dataset,))
            self.db.commit()

    # -- gold labels (human-corrected answers; see the table comment) --
    def _gold_row(self, r: sqlite3.Row) -> dict:
        return {
            "sample_id": r["sample_id"],
            "output": json.loads(r["output"]),
            "fields": json.loads(r["fields"]) if r["fields"] else [],
            "annotator": r["annotator"],
            "updated_at": r["updated_at"],
        }

    def get_gold(self, dataset: str, sample_id: str) -> dict | None:
        with self._lock:
            r = self.db.execute(
                "SELECT * FROM gold_labels WHERE dataset = ? AND sample_id = ?",
                (dataset, sample_id),
            ).fetchone()
            return self._gold_row(r) if r else None

    def all_gold(self, dataset: str) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM gold_labels WHERE dataset = ?", (dataset,)
            ).fetchall()
            return [self._gold_row(r) for r in rows]

    def upsert_gold(self, dataset: str, sample_id: str, body: dict) -> dict:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                """INSERT INTO gold_labels (
                    dataset, sample_id, output, fields, annotator, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset, sample_id) DO UPDATE SET
                    output = excluded.output,
                    fields = excluded.fields,
                    annotator = excluded.annotator,
                    updated_at = excluded.updated_at""",
                (
                    dataset,
                    sample_id,
                    json.dumps(body.get("output") or {}),
                    json.dumps(body.get("fields") or []),
                    body.get("annotator"),
                    now,
                ),
            )
            self.db.commit()
            return self.get_gold(dataset, sample_id)

    def delete_gold(self, dataset: str, sample_id: str) -> None:
        with self._lock:
            self.db.execute(
                "DELETE FROM gold_labels WHERE dataset = ? AND sample_id = ?",
                (dataset, sample_id),
            )
            self.db.commit()
