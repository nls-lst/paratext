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
        {"kind": "images", "crop": True},
        {"kind": "pdf"},
    ],
)
def test_render_project_is_valid_python(kwargs):
    files = render_project("Demo Project", **kwargs)
    init = files["demo_project/project.py"]
    ast.parse(init)  # raises SyntaxError if the template is malformed
    assert "from .project import PROJECT" in files["demo_project/__init__.py"]
    assert 'name="demo-project"' in init
    assert "PROJECT = Project(" in init
    assert files["demo_project/prompt.md"].strip()
    if kwargs.get("verso"):
        assert "is_verso" in init
    if kwargs.get("crop"):
        assert "load_card_detector" in init
    if kwargs["kind"] == "pdf":
        assert "pypdfium2" in init
