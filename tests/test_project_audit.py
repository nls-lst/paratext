"""audit_project links a project's schema, prompt, and view, so a field rename in
one can't silently drift from the others (paratext.projects.audit_project)."""

import pytest
from pydantic import BaseModel

from paratext.projects import (
    Panel,
    Project,
    View,
    audit_project,
    get_project,
    project_names,
)


@pytest.mark.parametrize("name", project_names())
def test_installed_projects_are_consistent(name):
    problems = audit_project(get_project(name))
    assert not problems, f"{name}: " + "; ".join(problems)


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
        layout="split",
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
