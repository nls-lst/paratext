"""The `paratext init` generator must emit valid, importable project code."""

import ast

import pytest

from paratext.scaffold import render_project, to_module_name


def test_module_name_slug():
    assert to_module_name("My Cards Project!") == "my_cards_project"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "images"},
        {"kind": "images", "verso": True},
        {"kind": "images", "verso": True, "crop": True},
        {"kind": "pdf"},
    ],
)
def test_render_project_is_valid_python(kwargs):
    files = render_project("Demo Project", **kwargs)
    init = files["demo_project/__init__.py"]
    ast.parse(init)  # raises SyntaxError if the template is malformed
    ast.parse(files["demo_project/schema.py"])
    assert "demo_project/project.py" not in files  # collapsed into __init__.py
    assert 'name="demo-project"' in init
    assert "from .schema import Record" in init
    assert "PROJECT = Project(" in init
    assert files["demo_project/prompt.md"].strip()
    if kwargs["kind"] == "pdf":
        assert "pdf_source(" in init
    else:
        assert f"image_source(verso_filter={bool(kwargs.get('verso'))}" in init
