"""Layered config resolution."""

from pathlib import Path

import paratext.config as cfg


def test_coerce_paths_types():
    d = cfg.coerce_paths(
        {"source": "/a/b", "output": "out.jsonl", "limit": "5", "no_structured": "true"}
    )
    assert isinstance(d["source"], Path)
    assert isinstance(d["output"], Path)
    assert d["limit"] == 5
    assert d["no_structured"] is True


def test_project_section_overrides_top_level():
    base: dict = {}
    layer = {
        "model": "top",
        "base-url": "http://x",  # kebab-case normalises to snake
        "project": {"index-cards": {"source": "/x", "model": "proj"}},
    }
    cfg._merge_layer(base, layer, "index-cards")
    assert base["model"] == "proj"  # project section wins over top-level
    assert base["base_url"] == "http://x"
    assert base["source"] == "/x"


def test_unrecognised_keys_ignored():
    base: dict = {}
    cfg._merge_layer(base, {"bogus": 1, "model": "m"}, None)
    assert "bogus" not in base
    assert base["model"] == "m"


def test_load_defaults_precedence(tmp_path, monkeypatch):
    (tmp_path / "paratext.toml").write_text(
        'model = "toml-model"\n[project.index-cards]\nsource = "/from/toml"\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PARATEXT_MODEL", "env-model")
    out = cfg.load_defaults("index-cards")
    assert out["model"] == "env-model"  # env beats the TOML
    assert out["source"] == "/from/toml"  # from the [project.index-cards] section
