"""Discovering packaged review datasets, loading their samples, and resolving
the view.json contract that drives the review UI.

Kept out of the review server so exporters and the CLI can read a packaged
round without importing web code. A "dataset" here is a directory holding
samples.json (plus optional view.json and images/); rounds are `<base>-r<N>`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .projects import humanise

# Verdict set used when a dataset was packaged without a view.json — mirrors
# projects.DEFAULT_VERDICTS in the wire shape the frontend expects.
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


def active_rounds(datasets: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in datasets:
        out[d["base"]] = max(out.get(d["base"], 0), d["round"])
    return out


def resolve_dataset(data_dir: Path, name: str | None) -> dict:
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
            specs.append({"key": k, "label": humanise(k), "type": t})
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


def model_output_fields(view: dict) -> list[dict]:
    """The model-output field list from a view contract, key/label/type only."""
    for panel in view.get("panels", []):
        if panel.get("source") == "model_output":
            return [
                {k: f.get(k) for k in ("key", "label", "type")}
                for f in panel.get("fields", [])
            ]
    return []


def diff_fields(before: list[dict], after: list[dict]) -> dict:
    """What changed between two rounds' field lists, keyed on field name."""
    b = {f["key"]: f for f in before}
    a = {f["key"]: f for f in after}
    return {
        "added": [a[k] for k in a if k not in b],
        "removed": [b[k] for k in b if k not in a],
        "retyped": [
            {"key": k, "label": a[k].get("label"),
             "from": b[k].get("type"), "to": a[k].get("type")}
            for k in a
            if k in b and a[k].get("type") != b[k].get("type")
        ],
    }


def schema_history(datasets: list[dict]) -> list[dict]:
    """Field list per round for one dataset family, oldest first, each carrying
    what changed since the round before it (`changes` is None for the first)."""
    rounds = []
    for ds in sorted(datasets, key=lambda d: d.get("round") or 0):
        vp = ds["dir"] / "view.json"
        view = json.loads(vp.read_text()) if vp.is_file() else synthesise_view(
            ds, load_samples(ds)
        )
        rounds.append({
            "round": ds.get("round"),
            "dataset": ds["name"],
            "schema_version": view.get("schema_version"),
            "fields": model_output_fields(view),
        })
    prev = None
    for r in rounds:
        r["changes"] = diff_fields(prev["fields"], r["fields"]) if prev else None
        prev = r
    return rounds


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
