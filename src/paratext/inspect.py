"""Describe installed projects — what `paratext inspect` and the review UI's
Projects page both read from.

A project's behaviour is spread across a schema, a prompt, a source adapter and
a View, in a package that may not be the one you are editing. This module
flattens all of that into one plain dict per project so it can be read without
opening the source.

It reports the **installed** state, which is the point: an edit that hasn't been
reinstalled won't show up here, and that discrepancy is usually the bug.

Read-only by design — nothing here mutates a project or its config.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from .extract import _prompt_hash
from .projects import ENTRY_POINT_GROUP, Project, audit_project, build_view, default_view


def _entry_point_info(name: str) -> dict:
    """Where this project was loaded from — module path and providing package."""
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name != name:
            continue
        dist = getattr(ep, "dist", None)
        return {
            "value": ep.value,
            "package": getattr(dist, "name", None),
            "version": getattr(dist, "version", None),
        }
    return {}


def describe(project: Project) -> dict:
    """Flatten one project into a JSON-serialisable description."""
    view = project.view or default_view(project)
    # build_view derives field labels/types from the schema, so the fields shown
    # here are exactly the ones the review UI will render.
    panels = build_view(project)["panels"]

    source = project.source
    return {
        "name": project.name,
        "schema_version": project.schema_version,
        "entry_point": _entry_point_info(project.name),
        "schema_class": f"{project.schema.__module__}.{project.schema.__qualname__}",
        "prompt": project.prompt,
        "prompt_hash": _prompt_hash(project.prompt),
        "source": dict(getattr(source, "config", {}) or {}) if source else {"kind": "custom"},
        "images": {"max_size": project.image_max_size, "quality": project.image_quality},
        "view": {"layout": view.layout, "ground_truth": view.ground_truth, "panels": panels},
        "audit": audit_project(project),
    }


def describe_all() -> list[dict]:
    """Describe every installed project, newest import errors included.

    A project that fails to import is reported as an entry with an ``error``
    rather than raising — one broken plug-in must not blank the whole page.
    """
    from .projects import get_project, project_names

    out: list[dict] = []
    for name in project_names():
        try:
            out.append(describe(get_project(name)))
        except Exception as e:
            out.append({"name": name, "error": f"{type(e).__name__}: {e}"})
    return out
