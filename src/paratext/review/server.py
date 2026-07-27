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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..datasets import (
    active_rounds,
    discover_datasets,
    load_samples,
    load_view,
    resolve_dataset,
    review_stats,
)
from ..store import Store, default_db_path

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




# ── HTTP handler ────────────────────────────────────────────────────────────
_MIME = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
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
        return resolve_dataset(self.data_dir, (qs.get("dataset") or [None])[0])

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
            if path == "/api/export/hf/config":
                return self._api_hf_config(self._dataset(qs))
            if path == "/.well-known/oauth-cimd":
                return self._serve_cimd()
            if path == "/oauth/callback/huggingface":
                return self._oauth_callback_page()
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
        if u.path == "/api/oauth/hf/exchange":
            return self._api_hf_exchange()
        if u.path == "/api/export/hf":
            return self._api_hf_push(self._dataset(qs))
        if u.path.startswith("/api/annotations/"):
            ds = self._dataset(qs)
            sid = unquote(u.path.split("/api/annotations/", 1)[1])
            return self._json(self.store.upsert(ds["name"], sid, self._body()))
        if u.path.startswith("/api/gold/"):
            ds = self._dataset(qs)
            sid = unquote(u.path.split("/api/gold/", 1)[1])
            return self._json(self.store.upsert_gold(ds["name"], sid, self._body()))
        return self._json({"error": "not found"}, 404)

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
        return self._json({"error": "not found"}, 404)

    # ── Endpoints ───────────────────────────────────────────────────────────
    def _api_datasets(self):
        datasets = discover_datasets(self.data_dir)
        active = active_rounds(datasets)
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
        """The zero-config escape hatch: a zip of two line-delimited JSON files —
        the records (`<name>-<scope>.jsonl`, gold answer where a human corrected
        it, else model output) and the review state alongside it
        (`<name>.review.jsonl`, verdict + correction provenance keyed by id), so
        a full-round export can still be filtered to the verified subset."""
        import io
        import zipfile

        from ..catalogue import records_for_scope

        scope = (qs.get("scope") or ["everything"])[0]
        try:
            records = records_for_scope(ds["dir"], ds["schema"], scope, db_path=self.store.db_path)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)

        rec_lines, review_lines = [], []
        for r in records:
            rec = {"id": r.sid, "document_id": r.document_id, **r.label}
            rec_lines.append(json.dumps(rec, ensure_ascii=False))
            ann = self.store.get(ds["name"], r.sid) or {}
            gold = self.store.get_gold(ds["name"], r.sid)
            review_lines.append(json.dumps({
                "id": r.sid,
                "verdict": ann.get("model_correct"),
                "notes": ann.get("notes"),
                "corrected": gold is not None,
                "corrected_fields": (gold or {}).get("fields") or [],
            }, ensure_ascii=False))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{ds['name']}-{scope}.jsonl", "\n".join(rec_lines) + "\n")
            z.writestr(f"{ds['name']}.review.jsonl", "\n".join(review_lines) + "\n")
        self._bytes(
            buf.getvalue(),
            "application/zip",
            headers={
                "content-disposition": f'attachment; filename="{ds["name"]}-{scope}.zip"',
                "x-record-count": str(len(records)),
            },
        )

    # -- Hugging Face push (OAuth) --
    # The token is the user's, obtained by "Sign in with HF" in the browser and
    # sent per push; the service stores none. See review/hf_oauth.py.
    def _api_hf_config(self, ds):
        """What the HF tab needs to start sign-in: the client id (a registered
        app if configured, else the CIMD URL), the redirect uri, scopes, and the
        config defaults + gold count."""
        from .. import hf_export
        from ..catalogue import records_for_scope
        from ..config import load_project_section
        from . import hf_oauth

        cfg = load_project_section(ds["schema"], "export")
        base = hf_oauth.base_url(cfg, self.headers)
        try:
            n = len(records_for_scope(
                ds["dir"], ds["schema"], "good_enough", db_path=self.store.db_path
            ))
        except ValueError:
            n = 0
        self._json({
            "authorize_url": hf_oauth.AUTHORIZE,
            "client_id": hf_oauth.client_id(cfg, base),
            "redirect_uri": f"{base}{hf_oauth.CALLBACK_PATH}",
            "scopes": hf_oauth.SCOPES,
            "default_repo": cfg.get("repo"),
            "default_license": cfg.get("license"),
            "gold_count": n,
            "provenance_missing": hf_export.provenance_gaps(ds["dir"]),
        })

    def _serve_cimd(self):
        """The CIMD document HF fetches to validate a registration-free client.
        Base comes from PARATEXT_HF_PUBLIC_BASE_URL or the forwarded headers —
        there's no project context on this route."""
        from . import hf_oauth

        self._json(hf_oauth.cimd_document(hf_oauth.base_url({}, self.headers)))

    def _oauth_callback_page(self):
        """The popup lands here after HF consent; hand code+state back to the
        opener and close. HF sets COOP on its pages, which severs window.opener on
        the way back — so deliver over BroadcastChannel (+ localStorage fallback),
        both same-origin and COOP-proof; postMessage is only a best-effort. The
        token exchange runs in the opener (it holds the PKCE verifier)."""
        html = (
            "<!doctype html><meta charset=utf-8><title>Signing in…</title>"
            "<script>(function(){var p=new URLSearchParams(location.search);"
            "var m={source:'paratext-hf-oauth',code:p.get('code'),state:p.get('state'),"
            "error:p.get('error'),error_description:p.get('error_description')};"
            "try{var bc=new BroadcastChannel('paratext-hf-oauth');"
            "bc.postMessage(m);bc.close();}catch(e){}"
            "try{localStorage.setItem('paratext-hf-oauth',JSON.stringify(m));}catch(e){}"
            "try{if(window.opener)window.opener.postMessage(m,location.origin);}catch(e){}"
            "try{window.close();}catch(e){}"
            "})();</script><p>Signing in… you can close this window.</p>"
        ).encode()
        self._bytes(html, "text/html; charset=utf-8")

    def _api_hf_exchange(self):
        """Proxy the PKCE code->token exchange (server-side, so no CORS and no
        client secret in the browser), then return the token plus the identity it
        resolves to. The token is handed straight back to the browser; not stored."""
        from . import hf_oauth

        body = self._body()
        try:
            tok = hf_oauth.exchange_code(
                code=body["code"], code_verifier=body["code_verifier"],
                redirect_uri=body["redirect_uri"], client_id=body["client_id"],
            )
        except KeyError as e:
            return self._json({"error": f"missing {e}"}, 400)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        access = tok.get("access_token")
        if not access:
            return self._json({"error": "no access_token in token response"}, 400)
        try:
            who = hf_oauth.userinfo(access)
        except Exception:
            who = {}
        self._json({
            "access_token": access,
            "user": {
                "name": who.get("name") or who.get("fullname"),
                "orgs": [o.get("name") for o in (who.get("orgs") or []) if o.get("name")],
            },
        })

    def _api_hf_push(self, ds):
        """Build the gold set and push it to the Hub as the signed-in user (the
        Bearer token from their browser). Builds into a temp dir — never the
        CWD-relative export/ — so concurrent pushes don't clash."""
        import shutil
        import tempfile

        from .. import hf_export
        from ..config import load_project_section

        auth = self.headers.get("authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token:
            return self._json({"error": "sign in to Hugging Face first"}, 401)
        body = self._body()
        repo = (body.get("repo") or "").strip()
        if not repo:
            return self._json({"error": "choose a target repo (owner/name)"}, 400)
        raw = load_project_section(ds["schema"], "export")
        cfg = hf_export.ExportConfig(
            repo=repo,
            license=hf_export.normalise_license(body.get("license") or raw.get("license")),
            rights=raw.get("rights"),
            min_verdict=raw.get("min_verdict", "good_enough"),
            include_negatives=bool(raw.get("include_negatives", False)),
            annotators=raw.get("annotators", "omit"),
            public=bool(body.get("public")),
        )
        dest = Path(tempfile.mkdtemp(prefix="paratext-hf-"))
        try:
            summary = hf_export.build(
                ds["dir"], ds["schema"], cfg, dest, db_path=self.store.db_path
            )
            hf_export.push_built(dest, cfg, summary, token=token)
        except (Exception, SystemExit) as e:
            return self._json({"error": str(e)}, 400)
        finally:
            shutil.rmtree(dest, ignore_errors=True)
        self._json({
            "url": summary.url, "repo": summary.repo,
            "gold": summary.gold, "corrected": summary.corrected,
        })

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
        ds = resolve_dataset(self.data_dir, parts[0])
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
    Handler.store = Store(default_db_path(data_dir, Path(db_path).resolve() if db_path else None))
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
