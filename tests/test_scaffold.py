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
    files = render_project("Demo Project", fields=["title", "author name"], **kwargs)
    init = files["demo_project/__init__.py"]
    ast.parse(init)  # raises SyntaxError if the template is malformed
    schema = files["demo_project/schema.py"]
    ast.parse(schema)
    assert "demo_project/project.py" not in files  # collapsed into __init__.py
    assert 'name="demo-project"' in init
    assert "from .schema import Record" in init
    assert "PROJECT = Project(" in init
    assert files["demo_project/prompt.md"].strip()
    # seeded fields become schema attributes (slugified)
    assert "title: Optional[str]" in schema and "author_name: Optional[str]" in schema
    if kwargs["kind"] == "pdf":
        assert "pdf_source(" in init
    else:
        assert f"image_source(verso_filter={bool(kwargs.get('verso'))}" in init


def test_offer_config_writes_block(tmp_path, monkeypatch):
    import tomllib

    from paratext import scaffold

    monkeypatch.chdir(tmp_path)
    answers = iter(["y", "/data/mycards", "http://localhost:8000/v1", "Qwen3-VL-30B"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    scaffold._offer_config("my-cards")

    toml = (tmp_path / "paratext.toml").read_text()
    tomllib.loads(toml)  # valid TOML
    assert "[project.my-cards]" in toml
    assert 'source = "/data/mycards"' in toml
    assert 'base-url = "http://localhost:8000/v1"' in toml and 'model = "Qwen3-VL-30B"' in toml


def test_offer_config_inherits_existing_endpoint(tmp_path, monkeypatch):
    from paratext import scaffold

    monkeypatch.chdir(tmp_path)
    (tmp_path / "paratext.toml").write_text('base-url = "http://host/v1"\nmodel = "M"\n')
    answers = iter(["y", "/data/x"])  # add? yes; source — no endpoint prompts expected
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    scaffold._offer_config("my-cards")

    toml = (tmp_path / "paratext.toml").read_text()
    assert toml.count("base-url") == 1  # endpoint not duplicated
    assert "[project.my-cards]" in toml and 'source = "/data/x"' in toml


def test_offer_config_skips_existing_project(tmp_path, monkeypatch):
    from paratext import scaffold

    monkeypatch.chdir(tmp_path)
    (tmp_path / "paratext.toml").write_text(
        'base-url = "x"\n\n[project.my-cards]\nsource = "old"\n'
    )
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    scaffold._offer_config("my-cards")

    toml = (tmp_path / "paratext.toml").read_text()
    assert toml.count("[project.my-cards]") == 1 and 'source = "old"' in toml


def test_insert_entry_point_appends_new_table(tmp_path):
    import tomllib

    from paratext import scaffold

    pp = tmp_path / "pyproject.toml"
    text = '[project]\nname = "demo"\n'
    pp.write_text(text)
    assert scaffold._insert_entry_point(pp, text, "my-cards", "my_cards") is True
    parsed = tomllib.loads(pp.read_text())
    assert parsed["project"]["entry-points"]["paratext.projects"]["my-cards"] == "my_cards:PROJECT"


def test_insert_entry_point_into_existing_table(tmp_path):
    import tomllib

    from paratext import scaffold

    pp = tmp_path / "pyproject.toml"
    text = (
        '[project]\nname = "demo"\n\n'
        '[project.entry-points."paratext.projects"]\n'
        'existing = "existing:PROJECT"\n'
    )
    pp.write_text(text)
    assert scaffold._insert_entry_point(pp, text, "my-cards", "my_cards") is True
    eps = tomllib.loads(pp.read_text())["project"]["entry-points"]["paratext.projects"]
    assert eps == {"existing": "existing:PROJECT", "my-cards": "my_cards:PROJECT"}
