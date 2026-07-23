"""Inbuilt review server — `paratext review`.

A dependency-free local web app (stdlib ``http.server`` + ``sqlite3``) for
human review of packaged datasets. It serves the generic vanilla-JS frontend in
``static/`` and a small JSON API the frontend drives entirely from each
dataset's ``view.json`` contract, so the same UI reviews any project's output.

A dataset is a directory containing ``samples.json`` (+ optional ``view.json``
and ``images/``). Point ``paratext review`` at one dataset directory, or at a
parent directory holding several (each in its own subdir). Annotations persist
to ``<data-dir>/annotations.db``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5050


def is_running(port: int = DEFAULT_PORT) -> bool:
    """True if a review server already answers on this port (so callers can
    avoid launching a second one — datasets are re-read per request, so a new
    one appears in the running server on reload)."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/datasets", timeout=0.5) as r:
            return r.status == 200
    except Exception:
        return False

VERDICTS_FALLBACK = [
    {
        "value": "good_enough",
        "label": "Good enough",
        "hotkey": "1",
        "notes": False,
        "negative": False,
    },
    {
        "value": "needs_tweaks",
        "label": "Needs tweaks",
        "hotkey": "2",
        "notes": True,
        "negative": False,
    },
    {
        "value": "not_accurate",
        "label": "Not accurate",
        "hotkey": "3",
        "notes": True,
        "negative": True,
    },
]


# ── Annotation store (sqlite) ───────────────────────────────────────────────
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


# ── Dataset discovery + loading ─────────────────────────────────────────────
def _parse_name(name: str) -> tuple[str, int]:
    m = re.match(r"^(.*)-r(\d+)$", name)
    return (m.group(1), int(m.group(2))) if m else (name, 1)


def discover_datasets(data_dir: Path) -> list[dict]:
    """Datasets are subdirs of ``data_dir`` with a samples.json — or ``data_dir``
    itself if it holds one (single-dataset case)."""
    out: list[dict] = []

    def _add(name: str, d: Path):
        records = json.loads((d / "samples.json").read_text())
        base, rnd = _parse_name(name)
        schema = (records[0].get("schema") if records else None) or name
        out.append(
            {
                "name": name,
                "schema": schema,
                "count": len(records),
                "dir": d,
                "base": base,
                "round": rnd,
            }
        )

    if (data_dir / "samples.json").is_file():
        _add(data_dir.name, data_dir)
        return out
    for sub in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        if (sub / "samples.json").is_file():
            _add(sub.name, sub)
    return out


def _active_round(datasets: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in datasets:
        out[d["base"]] = max(out.get(d["base"], 0), d["round"])
    return out


def _resolve(data_dir: Path, name: str | None) -> dict:
    datasets = discover_datasets(data_dir)
    if not datasets:
        raise FileNotFoundError(f"No datasets found under {data_dir}")
    if name:
        for d in datasets:
            if d["name"] == name:
                return d
        raise KeyError(f"Unknown dataset: {name}")
    return datasets[0]


def load_samples(dataset: dict) -> list[dict]:
    records = json.loads((dataset["dir"] / "samples.json").read_text())
    for s in records:
        imgs = s.get("images") or []
        s["images"] = [
            p if p.startswith("/") else f"images/{dataset['name']}/{re.sub('^images/', '', p)}"
            for p in imgs
        ]
    return records


def _humanise(key: str) -> str:
    s = key.replace("_", " ")
    return s[:1].upper() + s[1:]


def _infer_type(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, list):
        return "entries" if (v and isinstance(v[0], dict)) else "list"
    return "string"


def synthesise_view(dataset: dict, samples: list[dict]) -> dict:
    """Generic view inferred from the data, for datasets packaged without a
    view.json. Field types come from the first non-empty value across samples."""
    first = samples[0] if samples else {}
    has_gt = first.get("ground_truth") is not None

    def fields_of(source: str) -> list[dict]:
        keys = list((samples[0].get(source) or {}).keys()) if samples else []
        specs = []
        for k in keys:
            t = "string"
            for s in samples:
                v = (s.get(source) or {}).get(k)
                empty = v is None or v == "" or (isinstance(v, list) and not v)
                if not empty:
                    t = _infer_type(v)
                    break
            specs.append({"key": k, "label": _humanise(k), "type": t})
        return specs

    panels = (
        [
            {
                "source": "ground_truth",
                "title": "Catalogue ground truth",
                "fields": fields_of("ground_truth"),
            },
            {
                "source": "model_output",
                "title": "Model output",
                "fields": fields_of("model_output"),
            },
        ]
        if has_gt
        else [
            {"source": "model_output", "title": "Model output", "fields": fields_of("model_output")}
        ]
    )
    return {
        "contract_version": 0,
        "schema": dataset["schema"],
        "title": dataset["base"],
        "id_label": "ID",
        "layout": "stacked" if has_gt else "split",
        "ground_truth": has_gt,
        "panels": panels,
        "scoring": {
            "verdicts": VERDICTS_FALLBACK,
            "notes": {
                "label": "Notes",
                "placeholder": "Describe what's wrong or what should change…",
            },
        },
    }


def load_view(dataset: dict, samples: list[dict]) -> dict:
    vp = dataset["dir"] / "view.json"
    if vp.is_file():
        return json.loads(vp.read_text())
    return synthesise_view(dataset, samples)


def review_stats(
    total: int, annotations: list[dict], gold_ids: set[str] | None = None
) -> dict:
    """Verdict counts + accuracy for a round. `needs_tweaks` counts as half
    credit. Shared by the `/api/stats` endpoint and `paratext export`.

    `gold_ids` (sample ids with a human-corrected gold label) drives the eval-set
    figures: `corrected` = how many, `eval_gold` = distinct samples that are
    `good_enough` OR corrected (the full gold set `paratext export` would ship)."""
    gold_ids = gold_ids or set()
    n = lambda v: sum(1 for a in annotations if a["model_correct"] == v)  # noqa: E731
    good, tweaks, bad = n("good_enough"), n("needs_tweaks"), n("not_accurate")
    scored = good + tweaks + bad
    good_ids = {a["sample_id"] for a in annotations if a["model_correct"] == "good_enough"}
    return {
        "total": total,
        "annotated": sum(1 for a in annotations if a["model_correct"] is not None),
        "flagged_marc": sum(1 for a in annotations if a["catalogue_correct"] == "flagged"),
        "corrected": len(gold_ids),
        "eval_gold": len(good_ids | gold_ids),
        "model": {
            "good_enough": good,
            "needs_tweaks": tweaks,
            "not_accurate": bad,
            "scored": scored,
            "accuracy": ((good + tweaks * 0.5) / scored * 100) if scored else None,
        },
    }


# ── HTTP handler ────────────────────────────────────────────────────────────
_MIME = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class Handler(BaseHTTPRequestHandler):
    data_dir: Path
    store: Store

    def log_message(self, *a):  # quiet by default
        pass

    # -- helpers --
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body: bytes, mime: str, status=200, headers: dict | None = None):
        self.send_response(status)
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _dataset(self, qs):
        return _resolve(self.data_dir, (qs.get("dataset") or [None])[0])

    def _body(self) -> dict:
        n = int(self.headers.get("content-length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return {}

    # -- routing --
    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        try:
            if path == "/api/datasets":
                return self._api_datasets()
            if path == "/api/view":
                ds = self._dataset(qs)
                return self._json(load_view(ds, load_samples(ds)))
            if path == "/api/samples":
                return self._api_samples(self._dataset(qs))
            if path.startswith("/api/samples/"):
                return self._api_sample(
                    self._dataset(qs), unquote(path.split("/api/samples/", 1)[1])
                )
            if path == "/api/stats":
                return self._api_stats(self._dataset(qs))
            if path == "/api/table":
                return self._api_table(self._dataset(qs))
            if path == "/api/projects":
                return self._api_projects()
            if path == "/api/prompts":
                return self._api_prompts(self._dataset(qs))
            if path == "/api/export/fields":
                return self._api_export_fields(self._dataset(qs), qs)
            if path in ("/api/export/marc", "/api/export/dc"):
                return self._api_export_catalogue(
                    self._dataset(qs), path.rsplit("/", 1)[1], qs
                )
            if path == "/api/export/jsonl":
                return self._api_export_jsonl(self._dataset(qs), qs)
            if path.startswith("/api/export/"):
                return self._api_export(self._dataset(qs))
            if path.startswith("/images/"):
                return self._serve_image(path)
            return self._serve_static(path)
        except (FileNotFoundError, KeyError) as e:
            return self._json({"error": str(e)}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/api/export/marc", "/api/export/dc"):
            body = self._body()
            if body.get("scope"):
                qs["scope"] = [body["scope"]]
            return self._api_export_catalogue(
                self._dataset(qs), u.path.rsplit("/", 1)[1], qs, mapping=body.get("mapping")
            )
        if u.path.startswith("/api/annotations/"):
            ds = self._dataset(qs)
            sid = unquote(u.path.split("/api/annotations/", 1)[1])
            return self._json(self.store.upsert(ds["name"], sid, self._body()))
        if u.path.startswith("/api/gold/"):
            ds = self._dataset(qs)
            sid = unquote(u.path.split("/api/gold/", 1)[1])
            return self._json(self.store.upsert_gold(ds["name"], sid, self._body()))
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/api/reset":
            if self._body().get("confirm") is not True:
                return self._json({"error": "Pass {confirm: true} to reset."}, 400)
            self.store.reset((qs.get("dataset") or [None])[0])
            return self._json({"ok": True})
        if u.path.startswith("/api/gold/"):
            ds = self._dataset(qs)
            sid = unquote(u.path.split("/api/gold/", 1)[1])
            self.store.delete_gold(ds["name"], sid)
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    # -- endpoints --
    def _api_datasets(self):
        datasets = discover_datasets(self.data_dir)
        active = _active_round(datasets)
        self._json(
            [
                {
                    "name": d["name"],
                    "schema": d["schema"],
                    "count": d["count"],
                    "base": d["base"],
                    "round": d["round"],
                    "active": d["round"] == active.get(d["base"]),
                }
                for d in datasets
            ]
        )

    def _api_projects(self):
        """Installed projects, described, each annotated with the prompt from its
        most recent packaged round.

        The comparison is the useful part: if the installed prompt differs from
        the one that produced the latest round, the next run will not reproduce
        that round. That is the drift this page exists to catch, so it's shown
        as a diff rather than asserted in prose.
        """
        from ..inspect import describe_all

        projects = describe_all()
        datasets = discover_datasets(self.data_dir)
        for p in projects:
            if p.get("error"):
                continue
            mine = [d for d in datasets if d.get("schema") == p["name"]]
            if not mine:
                continue
            latest = max(mine, key=lambda d: d["round"])
            sample = next((s for s in load_samples(latest) if s.get("prompt")), None)
            if not sample:
                continue
            prompt = sample["prompt"]
            p["latest_round"] = {
                "dataset": latest["name"],
                "round": latest["round"],
                # The round number comes from the directory name, which can lie:
                # a re-packaged round (an "r2b" rerun landing in `-r2`) keeps the
                # old number. The hash is the only unambiguous identifier, so
                # show it alongside.
                "prompt_hash": sample.get("prompt_hash"),
                "prompt": prompt,
                "matches_installed": prompt.strip() == p["prompt"].strip(),
            }
        self._json(projects)

    def _api_samples(self, ds):
        ann = {a["sample_id"]: a for a in self.store.all(ds["name"])}
        gold = {g["sample_id"] for g in self.store.all_gold(ds["name"])}
        self._json(
            [
                {
                    "id": s["id"],
                    "document_id": s.get("document_id"),
                    "annotated": (ann.get(str(s["id"]), {}).get("model_correct")) is not None,
                    "model_correct": ann.get(str(s["id"]), {}).get("model_correct"),
                    "corrected": str(s["id"]) in gold,
                }
                for s in load_samples(ds)
            ]
        )

    def _api_sample(self, ds, sid):
        sample = next((s for s in load_samples(ds) if str(s["id"]) == sid), None)
        if sample is None:
            return self._json({"error": "not found"}, 404)
        sample = {
            **sample,
            "schema": sample.get("schema") or ds["schema"],
            "annotation": self.store.get(ds["name"], sid),
            "gold": self.store.get_gold(ds["name"], sid),
        }
        self._json(sample)

    def _api_stats(self, ds):
        gold_ids = {g["sample_id"] for g in self.store.all_gold(ds["name"])}
        stats = review_stats(len(load_samples(ds)), self.store.all(ds["name"]), gold_ids)
        self._json({"dataset": ds["name"], "schema": ds["schema"], **stats})

    def _api_table(self, ds):
        all_s = load_samples(ds)
        view = load_view(ds, all_s)
        tl = view.get("table_label")
        ann = {a["sample_id"]: a for a in self.store.all(ds["name"])}
        rows = []
        for s in all_s:
            a = ann.get(str(s["id"]), {})
            label = (s.get(tl["source"]) or {}).get(tl["key"]) if tl else None
            rows.append(
                {
                    "sample_id": str(s["id"]),
                    "document_id": s.get("document_id"),
                    "title": label,
                    "model_correct": a.get("model_correct"),
                    "catalogue_correct": a.get("catalogue_correct"),
                    "notes": a.get("notes"),
                }
            )
        self._json(rows)

    def _api_prompts(self, ds):
        siblings = [d for d in discover_datasets(self.data_dir) if d["base"] == ds["base"]]
        groups: dict[str, dict] = {}
        for sib in siblings:
            for s in load_samples(sib):
                text = s.get("prompt") or ""
                if not text:
                    continue
                h = s.get("prompt_hash") or str(hash(text) & 0xFFFFFFFFFFFF)
                g = groups.setdefault(
                    h, {"hash": h, "text": text, "count": 0, "rounds": [], "datasets": []}
                )
                g["count"] += 1
                if sib["round"] not in g["rounds"]:
                    g["rounds"].append(sib["round"])
                if sib["name"] not in g["datasets"]:
                    g["datasets"].append(sib["name"])
        for g in groups.values():
            g["rounds"].sort()
        prompts = sorted(groups.values(), key=lambda g: max(g["rounds"]), reverse=True)
        self._json({"dataset": ds["name"], "base": ds["base"], "prompts": prompts})

    def _api_export_fields(self, ds, qs):
        """The mapping table for the export modal: every schema field and its
        inferred MARC tag / DC element (editable in the UI). `fmt=marc|dc`."""
        from ..catalogue import infer_target, records_for_scope
        from ..inspect import describe
        from ..projects import get_project

        fmt = (qs.get("fmt") or ["marc"])[0]
        project = get_project(ds["schema"])
        fields = describe(project)["view"]["panels"][0]["fields"]
        rows = [
            {
                "key": f["key"],
                "label": f["label"],
                "type": f["type"],
                "target": infer_target(f["key"], fmt),  # None == unmapped
            }
            for f in fields
        ]
        scopes = {
            s: len(records_for_scope(ds["dir"], ds["schema"], s, db_path=self.store.db_path))
            for s in ("good_enough", "needs_tweaks", "everything")
        }
        self._json({"dataset": ds["name"], "format": fmt, "fields": rows, "scopes": scopes})

    def _api_export_catalogue(self, ds, fmt, qs, mapping=None):
        """Stream a MARCXML / Dublin Core collection as a browser download.
        `scope=good_enough|needs_tweaks|everything`. On POST, an optional
        `mapping` (field -> target) from the modal's edited table is applied."""
        from ..catalogue import export_bytes

        scope = (qs.get("scope") or ["everything"])[0]
        try:
            xml, n = export_bytes(
                ds["dir"], ds["schema"], fmt, scope,
                db_path=self.store.db_path, mapping=mapping,
            )
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        self._bytes(
            xml,
            "application/xml",
            headers={
                "content-disposition": f'attachment; filename="{ds["name"]}-{fmt}.xml"',
                "x-record-count": str(n),
            },
        )

    def _api_export_jsonl(self, ds, qs):
        """Stream the selected records as line-delimited JSON — the zero-config
        escape hatch. `scope` as above; the label per record is the gold answer
        where a human corrected it, else the model output."""
        from ..catalogue import records_for_scope

        scope = (qs.get("scope") or ["everything"])[0]
        try:
            records = records_for_scope(ds["dir"], ds["schema"], scope, db_path=self.store.db_path)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        lines = [
            json.dumps({"id": r.sid, "document_id": r.document_id, **r.label}, ensure_ascii=False)
            for r in records
        ]
        self._bytes(
            ("\n".join(lines) + "\n").encode("utf-8"),
            "application/x-ndjson",
            headers={
                "content-disposition": f'attachment; filename="{ds["name"]}-{scope}.jsonl"',
                "x-record-count": str(len(records)),
            },
        )

    def _api_export(self, ds):
        """Generic CSV of flagged/scored samples (project-neutral)."""
        all_s = load_samples(ds)
        ann = {a["sample_id"]: a for a in self.store.all(ds["name"])}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "document_id", "model_correct", "catalogue_correct", "notes"])
        for s in all_s:
            a = ann.get(str(s["id"]), {})
            if a.get("model_correct") or a.get("catalogue_correct"):
                w.writerow(
                    [
                        s["id"],
                        s.get("document_id"),
                        a.get("model_correct"),
                        a.get("catalogue_correct"),
                        a.get("notes"),
                    ]
                )
        self._bytes(
            buf.getvalue().encode(),
            "text/csv",
            headers={"content-disposition": f'attachment; filename="{ds["name"]}-review.csv"'},
        )

    def _serve_image(self, path):
        parts = [unquote(p) for p in path.split("/") if p][1:]  # drop "images"
        if len(parts) < 3:
            return self._json({"error": "not found"}, 404)
        ds = _resolve(self.data_dir, parts[0])
        base = (ds["dir"] / "images").resolve()
        target = (base / "/".join(parts[1:])).resolve()
        if base != target and base not in target.parents:  # path-traversal guard
            return self._json({"error": "not found"}, 404)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        self._bytes(
            target.read_bytes(),
            _MIME.get(target.suffix.lower(), "application/octet-stream"),
            headers={"cache-control": "public, max-age=3600"},
        )

    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            return self._json({"error": "not found"}, 404)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        self._bytes(
            target.read_bytes(), _MIME.get(target.suffix.lower(), "application/octet-stream")
        )


def serve(
    data_dir: Path,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    host: str = "127.0.0.1",
    db_path: Path | None = None,
    allow_empty: bool = False,
) -> None:
    """Serve the review UI over ``data_dir``.

    ``allow_empty`` starts the server even when the directory doesn't exist yet
    (creating it). The CLI passes it for the *default* review root, so a fresh
    install can still reach the Projects page and the homepage guidance — an
    explicitly-passed path that's missing is a typo, and still an error.
    """
    data_dir = Path(data_dir).resolve()
    if data_dir.exists() and not data_dir.is_dir():
        raise SystemExit(f"Not a directory: {data_dir}")
    if not data_dir.exists():
        if not allow_empty:
            raise SystemExit(
                f"No review datasets at {data_dir}. Run `paratext run` first, "
                f"or pass a dataset directory: paratext review <dir>"
            )
        data_dir.mkdir(parents=True, exist_ok=True)
    Handler.data_dir = data_dir
    # Default the annotation store to <data_dir>/annotations.db; --db can point it
    # elsewhere (e.g. an existing DB when swapping in for another review app).
    Handler.store = Store(Path(db_path).resolve() if db_path else data_dir / "annotations.db")
    datasets = discover_datasets(data_dir)
    httpd = ThreadingHTTPServer((host, port), Handler)
    # When bound to all interfaces there's no single canonical URL; show
    # localhost for clicking and note the bind address.
    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{shown}:{port}"
    print(f"paratext review on {url}" + (f"  (bound to {host}:{port})" if shown != host else ""))
    names = ", ".join(d["name"] for d in datasets) or "none"
    print(
        f"  data dir: {data_dir}  ({len(datasets)} dataset(s): {names})"
    )
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
