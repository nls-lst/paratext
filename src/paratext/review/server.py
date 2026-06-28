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
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
VERDICTS_FALLBACK = [
    {"value": "good_enough", "label": "Good enough", "hotkey": "1", "notes": False, "negative": False},
    {"value": "needs_tweaks", "label": "Needs tweaks", "hotkey": "2", "notes": True, "negative": False},
    {"value": "not_accurate", "label": "Not accurate", "hotkey": "3", "notes": True, "negative": True},
]


# ── Annotation store (sqlite) ───────────────────────────────────────────────
class Store:
    """One ``annotations`` table keyed by (dataset, sample_id). Corrections are
    a generic JSON blob keyed by field name, so any schema works."""

    def __init__(self, db_path: Path):
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
        r = self.db.execute(
            "SELECT * FROM annotations WHERE dataset = ? AND sample_id = ?",
            (dataset, sample_id),
        ).fetchone()
        return self._row(r) if r else None

    def all(self, dataset: str | None = None) -> list[dict]:
        if dataset is None:
            rows = self.db.execute("SELECT * FROM annotations").fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM annotations WHERE dataset = ?", (dataset,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def upsert(self, dataset: str, sample_id: str, body: dict) -> dict:
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
        if dataset is None:
            self.db.execute("DELETE FROM annotations")
        else:
            self.db.execute("DELETE FROM annotations WHERE dataset = ?", (dataset,))
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
        out.append({"name": name, "schema": schema, "count": len(records),
                    "dir": d, "base": base, "round": rnd})

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
        [{"source": "ground_truth", "title": "Catalogue ground truth", "fields": fields_of("ground_truth")},
         {"source": "model_output", "title": "Model output", "fields": fields_of("model_output")}]
        if has_gt
        else [{"source": "model_output", "title": "Model output", "fields": fields_of("model_output")}]
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
            "notes": {"label": "Notes", "placeholder": "Describe what's wrong or what should change…"},
        },
    }


def load_view(dataset: dict, samples: list[dict]) -> dict:
    vp = dataset["dir"] / "view.json"
    if vp.is_file():
        return json.loads(vp.read_text())
    return synthesise_view(dataset, samples)


# ── HTTP handler ────────────────────────────────────────────────────────────
_MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


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
                return self._api_sample(self._dataset(qs), unquote(path.split("/api/samples/", 1)[1]))
            if path == "/api/stats":
                return self._api_stats(self._dataset(qs))
            if path == "/api/table":
                return self._api_table(self._dataset(qs))
            if path == "/api/prompts":
                return self._api_prompts(self._dataset(qs))
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
        if u.path.startswith("/api/annotations/"):
            ds = self._dataset(qs)
            sid = unquote(u.path.split("/api/annotations/", 1)[1])
            return self._json(self.store.upsert(ds["name"], sid, self._body()))
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/api/reset":
            if self._body().get("confirm") is not True:
                return self._json({"error": "Pass {confirm: true} to reset."}, 400)
            self.store.reset((qs.get("dataset") or [None])[0])
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    # -- endpoints --
    def _api_datasets(self):
        datasets = discover_datasets(self.data_dir)
        active = _active_round(datasets)
        self._json([
            {"name": d["name"], "schema": d["schema"], "count": d["count"],
             "base": d["base"], "round": d["round"], "active": d["round"] == active.get(d["base"])}
            for d in datasets
        ])

    def _api_samples(self, ds):
        ann = {a["sample_id"]: a for a in self.store.all(ds["name"])}
        self._json([
            {"id": s["id"], "document_id": s.get("document_id"),
             "annotated": (ann.get(str(s["id"]), {}).get("model_correct")) is not None}
            for s in load_samples(ds)
        ])

    def _api_sample(self, ds, sid):
        sample = next((s for s in load_samples(ds) if str(s["id"]) == sid), None)
        if sample is None:
            return self._json({"error": "not found"}, 404)
        sample = {**sample, "schema": sample.get("schema") or ds["schema"],
                  "annotation": self.store.get(ds["name"], sid)}
        self._json(sample)

    def _api_stats(self, ds):
        all_s = load_samples(ds)
        ann = self.store.all(ds["name"])
        scored_for = lambda v: sum(1 for a in ann if a["model_correct"] == v)  # noqa: E731
        good, tweaks, bad = scored_for("good_enough"), scored_for("needs_tweaks"), scored_for("not_accurate")
        scored = good + tweaks + bad
        self._json({
            "dataset": ds["name"], "schema": ds["schema"], "total": len(all_s),
            "annotated": sum(1 for a in ann if a["model_correct"] is not None),
            "flagged_marc": sum(1 for a in ann if a["catalogue_correct"] == "flagged"),
            "model": {"good_enough": good, "needs_tweaks": tweaks, "not_accurate": bad,
                      "scored": scored, "accuracy": ((good + tweaks * 0.5) / scored * 100) if scored else None},
        })

    def _api_table(self, ds):
        all_s = load_samples(ds)
        view = load_view(ds, all_s)
        tl = view.get("table_label")
        ann = {a["sample_id"]: a for a in self.store.all(ds["name"])}
        rows = []
        for s in all_s:
            a = ann.get(str(s["id"]), {})
            label = (s.get(tl["source"]) or {}).get(tl["key"]) if tl else None
            rows.append({"sample_id": str(s["id"]), "document_id": s.get("document_id"),
                         "title": label, "model_correct": a.get("model_correct"),
                         "catalogue_correct": a.get("catalogue_correct"), "notes": a.get("notes")})
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
                g = groups.setdefault(h, {"hash": h, "text": text, "count": 0, "rounds": [], "datasets": []})
                g["count"] += 1
                if sib["round"] not in g["rounds"]:
                    g["rounds"].append(sib["round"])
                if sib["name"] not in g["datasets"]:
                    g["datasets"].append(sib["name"])
        for g in groups.values():
            g["rounds"].sort()
        prompts = sorted(groups.values(), key=lambda g: max(g["rounds"]), reverse=True)
        self._json({"dataset": ds["name"], "base": ds["base"], "prompts": prompts})

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
                w.writerow([s["id"], s.get("document_id"), a.get("model_correct"),
                            a.get("catalogue_correct"), a.get("notes")])
        self._bytes(buf.getvalue().encode(), "text/csv",
                    headers={"content-disposition": f'attachment; filename="{ds["name"]}-review.csv"'})

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
        self._bytes(target.read_bytes(), _MIME.get(target.suffix.lower(), "application/octet-stream"),
                    headers={"cache-control": "public, max-age=3600"})

    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            return self._json({"error": "not found"}, 404)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        self._bytes(target.read_bytes(), _MIME.get(target.suffix.lower(), "application/octet-stream"))


def serve(data_dir: Path, port: int = 4000, open_browser: bool = True) -> None:
    data_dir = Path(data_dir).resolve()
    if not data_dir.is_dir():
        raise SystemExit(f"not a directory: {data_dir}")
    Handler.data_dir = data_dir
    Handler.store = Store(data_dir / "annotations.db")
    datasets = discover_datasets(data_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"paratext review on {url}")
    print(f"  data dir: {data_dir}  ({len(datasets)} dataset(s): {', '.join(d['name'] for d in datasets) or 'none'})")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
