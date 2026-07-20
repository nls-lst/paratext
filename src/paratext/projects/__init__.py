"""Project plug-ins. A project owns a prompt, an output schema (Pydantic), and
a way to enumerate samples from a source directory.

Adding a new project: create `paratext/projects/<name>/__init__.py` exporting
a Project instance, then register the name in REGISTRY below. Put the prompt in
a `prompt.md` beside the module and load it with `load_prompt(__file__)`.
"""

from __future__ import annotations

import re
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image
from pydantic import BaseModel


def load_prompt(module_file: str) -> str:
    """Load a project's prompt from `prompt.md` next to its module.

    Prompts live in markdown, not Python string literals, so non-developers
    can edit them and so prompt wording carries its own git history separate
    from schema/code changes. Pass `__file__` from the project module.

    Surrounding whitespace is stripped so trivial editor reformatting (a
    trailing newline, say) doesn't churn the prompt hash that drives the
    round-to-round diff in review.
    """
    return (Path(module_file).parent / "prompt.md").read_text(encoding="utf-8").strip()


@dataclass
class Sample:
    """One unit of work fed to the model."""

    id: str
    images: list[Image.Image]
    metadata: dict


@dataclass
class Curation:
    """A project's per-record decision when packaging for review.

    ``action`` is one of:
      - ``"keep"``       — include in samples.json (the default).
      - ``"drop"``       — exclude entirely; not materialised. ``reason`` keys
                           the skipped-count breakdown (e.g. a blank verso).
      - ``"quarantine"`` — materialised and recoverable in
                           samples-ephemera.json, but kept out of the review
                           set. ``reason`` keys the breakdown.
    """

    action: str = "keep"
    reason: str | None = None


KEEP = Curation("keep")


@dataclass
class Project:
    """A project bundles its prompt, schema, and how to read its source.

    The common case is just ``name``, ``schema_version``, ``prompt``, ``schema``
    and a ``source`` (see ``paratext.sources``). Everything else is optional:
    ``view`` defaults to showing all schema fields, and the packaging hooks have
    generic defaults — override only what your project genuinely needs.
    """

    name: str
    schema_version: str
    prompt: str
    schema: type[BaseModel]
    # A `paratext.sources.Source` supplies both iter_samples and an image
    # materialiser. Or pass `iter_samples` directly for a bespoke reader.
    source: "object | None" = None
    iter_samples: "Callable[[Path, int | None], Iterator[Sample]] | None" = None
    # Per-project hint for whether `enable_thinking` should be passed to chat APIs.
    disable_thinking: bool = True
    # Optional review/display contract spec; drives view.json. Defaults to one
    # panel showing every schema field (see default_view / build_view).
    view: "View | None" = None
    # Image encoding for the model call. Raise image_max_size when faint or small
    # detail matters (e.g. dense handwriting); 1024 suits most inputs.
    image_max_size: int = 1024
    image_quality: int = 85
    # ── Packaging hooks (all optional; the framework supplies generic defaults).
    # `package` calls these to turn an extraction JSONL into the review
    # dataset without knowing anything project-specific. See packaging.py.
    #   curate(record)               -> Curation (keep/drop/quarantine)
    #   materialise_images(rec, out, max_size) -> [rel_path]; saves files under out
    #   build_record(rec, images_rel)-> dict written into samples.json
    #   ground_truth(record)         -> dict | None attached as `ground_truth`
    curate: "Callable[[dict], Curation] | None" = None
    materialise_images: "Callable[[dict, Path, int], list[str]] | None" = None
    build_record: "Callable[[dict, list[str]], dict] | None" = None
    ground_truth: "Callable[[dict], dict | None] | None" = None

    def __post_init__(self):
        # A Source fills in iteration + image materialisation unless overridden.
        if self.source is not None:
            if self.iter_samples is None:
                self.iter_samples = self.source.iter_samples
            if self.materialise_images is None:
                self.materialise_images = self.source.materialise
        if self.iter_samples is None:
            raise ValueError(f"project {self.name}: pass source= or iter_samples=")


# ── Plugin discovery ───────────────────────────────────────────────────────
# Projects register themselves via the ``paratext.projects`` entry-point group,
# so they can live in any installed package — including a separate one — without
# the framework importing them by name. An entry point resolves to either a
# ``Project`` instance or a zero-arg callable returning one. Example, in a
# project package's pyproject.toml:
#
#     [project.entry-points."paratext.projects"]
#     index-cards = "my_pkg.index_cards:PROJECT"
ENTRY_POINT_GROUP = "paratext.projects"


def _entry_points() -> dict[str, object]:
    from importlib.metadata import entry_points

    return {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}


def project_names() -> list[str]:
    """Names of all installed/registered projects, sorted."""
    return sorted(_entry_points())


def get_project(name: str) -> Project:
    eps = _entry_points()
    ep = eps.get(name)
    if ep is None:
        known = ", ".join(sorted(eps)) or "(none installed)"
        raise ValueError(f"Unknown project: {name}. Known: {known}")
    obj = ep.load()
    return obj() if not isinstance(obj, Project) and callable(obj) else obj


# ── Review/display contract (view.json) ────────────────────────────────────
# The pipeline is the single source of truth for how a dataset is reviewed.
# `package` emits a per-dataset view.json from a project's View spec + its
# Pydantic schema; the review app renders generically from it. Field labels
# and types are *derived* from the schema — only curation lives in the View.
CONTRACT_VERSION = 1


@dataclass
class Verdict:
    value: str
    label: str
    hotkey: str
    notes: bool = False  # reveal the notes box when this verdict is chosen
    negative: bool = False  # style as a "bad" verdict


DEFAULT_VERDICTS = [
    Verdict("good_enough", "Good enough", "1"),
    Verdict("needs_tweaks", "Needs tweaks", "2", notes=True),
    Verdict("not_accurate", "Not accurate", "3", notes=True, negative=True),
]


@dataclass
class Panel:
    """One pane of fields backed by a record key (model_output | ground_truth).
    `fields` is an ordered list of schema field keys to display."""

    source: str
    title: str
    fields: list[str]
    flag: str | None = None  # optional catalogue flag control (the value)
    flag_label: str | None = None


@dataclass
class View:
    """Declarative review/display spec for a project."""

    layout: str  # "stacked" | "split"
    title: str
    id_label: str
    panels: list[Panel]
    ground_truth: bool = False
    labels: dict[str, str] = field(default_factory=dict)
    verdicts: list[Verdict] = field(default_factory=lambda: list(DEFAULT_VERDICTS))
    notes_label: str = "Notes"
    notes_placeholder: str = "Describe what's wrong or what should change…"
    table_label: tuple[str, str] | None = None  # (source, field key) for the stats table
    exports: list[dict] = field(default_factory=list)
    # Field keys rendered as a <details>, omitted entirely when empty.
    collapsed: list[str] = field(default_factory=list)


def _humanize(key: str) -> str:
    s = key.replace("_", " ")
    return s[:1].upper() + s[1:]


def _unwrap_optional(ann):
    """Strip Optional[X] / X | None down to X."""
    origin = typing.get_origin(ann)
    if origin is typing.Union or origin is getattr(types, "UnionType", None):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _field_spec(
    key: str, model: type[BaseModel], labels: dict[str, str], humanize: bool = True
) -> dict:
    """Describe one field — {key, label, type[, item_fields]} — from the schema."""
    ann = _unwrap_optional(model.model_fields[key].annotation)
    label = labels.get(key) or (_humanize(key) if humanize else key)
    spec: dict = {"key": key, "label": label}
    if ann is bool:
        spec["type"] = "bool"
    elif typing.get_origin(ann) is typing.Literal:
        # A fixed set of allowed values (e.g. image_type) — the review editor
        # renders these as a <select> so gold labels can't drift to a typo.
        spec["type"] = "enum"
        spec["options"] = [str(a) for a in typing.get_args(ann)]
    elif typing.get_origin(ann) is list:
        (inner,) = typing.get_args(ann) or (str,)
        inner = _unwrap_optional(inner)
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            spec["type"] = "entries"
            spec["item_fields"] = [
                _field_spec(k, inner, {}, humanize=False) for k in inner.model_fields
            ]
        else:
            spec["type"] = "list"
    elif ann in (int, float):
        spec["type"] = "number"
    else:
        spec["type"] = "string"  # str, Literal, etc.
    return spec


def default_view(project: Project) -> View:
    """A no-frills View: one panel listing every schema field. Used when a
    project doesn't define its own `view` (curation: order/hide/labels/GT)."""
    return View(
        layout="split",
        title=_humanize(project.name),
        id_label="ID",
        panels=[
            Panel(
                source="model_output",
                title="Model output",
                fields=list(project.schema.model_fields),
            )
        ],
    )


def build_view(project: Project) -> dict:
    """Build the view.json contract dict from a project's View spec + schema.
    Falls back to `default_view` (all fields) when the project sets no view."""
    v = project.view or default_view(project)
    panels: list[dict] = []
    for p in v.panels:
        fields = [_field_spec(k, project.schema, v.labels) for k in p.fields]
        for f in fields:
            if f["key"] in v.collapsed:
                f["collapsed"] = True
        panel: dict = {"source": p.source, "title": p.title, "fields": fields}
        if p.flag:
            panel["flag"] = {"value": p.flag, "label": p.flag_label or "Flag"}
        panels.append(panel)
    out: dict = {
        "contract_version": CONTRACT_VERSION,
        "schema": project.name,
        "schema_version": project.schema_version,
        "title": v.title,
        "id_label": v.id_label,
        "layout": v.layout,
        "ground_truth": v.ground_truth,
        "panels": panels,
        "scoring": {
            "verdicts": [vars(vd) for vd in v.verdicts],
            "notes": {"label": v.notes_label, "placeholder": v.notes_placeholder},
        },
    }
    if v.table_label:
        out["table_label"] = {"source": v.table_label[0], "key": v.table_label[1]}
    if v.exports:
        out["exports"] = list(v.exports)
    return out


# ── Project consistency audit ────────────────────────────────────────────────
# A project names its fields in three places — the Pydantic schema (structure,
# sent to the model as response_format), the prompt (instructions), and the View
# (presentation) — with no compile-time link between the string field names. This
# audit is the link: run it from a project's test suite so a field rename can't
# silently leave the prompt or view referring to a field that no longer exists.
def audit_project(project: Project) -> list[str]:
    """Cross-check a project's View and prompt against its schema. Returns a list of
    human-readable problems (empty == consistent).

    - Every field the View references (panel fields, custom labels, table_label)
      must be a real schema field — the View derives labels/types from the schema,
      so a stale key breaks view.json rendering.
    - Every field shown in a ``model_output`` panel must be named in the prompt, so
      a rename can't leave the prompt instructing a field the model no longer emits
      — and so prompts name fields exactly as the JSON keys the model must return.
    """
    problems: list[str] = []
    fields = set(project.schema.model_fields)
    view = project.view or default_view(project)

    referenced = {k for p in view.panels for k in p.fields} | set(view.labels) | set(view.collapsed)
    if view.table_label:
        referenced.add(view.table_label[1])
    for key in sorted(referenced - fields):
        problems.append(f"view references field {key!r} that is not in the schema")

    model_shown = {k for p in view.panels if p.source == "model_output" for k in p.fields}
    for key in sorted(model_shown):
        if not re.search(rf"\b{re.escape(key)}\b", project.prompt):
            problems.append(f"prompt never names model_output field {key!r}")
    return problems
