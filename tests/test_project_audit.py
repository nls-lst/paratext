"""audit_project links a project's schema, prompt, and view, so a field rename in
one can't silently drift from the others (paratext.projects.audit_project)."""

from typing import Literal, Optional

import pytest
from pydantic import BaseModel

from paratext.projects import (
    Panel,
    Project,
    View,
    _field_spec,
    audit_project,
    build_view,
    get_project,
    project_names,
)


@pytest.mark.parametrize("name", project_names())
def test_installed_projects_are_consistent(name):
    problems = audit_project(get_project(name))
    assert not problems, f"{name}: " + "; ".join(problems)


def test_field_spec_emits_enum_options_for_literal():
    class M(BaseModel):
        kind: Literal["a", "b", "c"]
        opt_kind: Optional[Literal["x", "y"]] = None
        name: Optional[str] = None

    assert _field_spec("kind", M, {}) == {
        "key": "kind", "label": "Kind", "type": "enum", "options": ["a", "b", "c"]}
    # Optional[Literal] is unwrapped to the same enum spec.
    assert _field_spec("opt_kind", M, {})["type"] == "enum"
    assert _field_spec("opt_kind", M, {})["options"] == ["x", "y"]
    # Plain strings stay strings.
    assert _field_spec("name", M, {})["type"] == "string"


class _Schema(BaseModel):
    heading: str | None = None
    text: str | None = None


def _project(view, prompt="Return the heading and text fields."):
    return Project(
        name="t",
        schema_version="v1",
        prompt=prompt,
        schema=_Schema,
        iter_samples=lambda p, n: iter(()),
        view=view,
    )


def _view(fields):
    return View(
        title="T",
        id_label="ID",
        panels=[Panel(source="model_output", title="M", fields=fields)],
    )


def test_audit_flags_view_field_absent_from_schema():
    problems = audit_project(_project(_view(["heading", "nope"])))
    assert any("nope" in p and "schema" in p for p in problems)


def test_audit_flags_model_field_missing_from_prompt():
    problems = audit_project(_project(_view(["heading", "text"]), prompt="Only the heading."))
    assert any("text" in p and "prompt" in p for p in problems)


def test_audit_passes_a_consistent_project():
    assert audit_project(_project(_view(["heading", "text"]))) == []


def test_layout_follows_panel_count_unless_set():
    one = _view(["heading"])
    two = View(
        title="T",
        id_label="ID",
        panels=[
            Panel(source="ground_truth", title="G", fields=["heading"]),
            Panel(source="model_output", title="M", fields=["heading"]),
        ],
    )
    assert build_view(_project(one))["layout"] == "split"
    assert build_view(_project(two))["layout"] == "stacked"
    one.layout = "stacked"
    assert build_view(_project(one))["layout"] == "stacked"
