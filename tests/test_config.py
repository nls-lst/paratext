"""Layered config resolution."""

from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "given,expected",
    [
        # The mistake that prompted this: a full endpoint URL. The client appends
        # /chat/completions itself, so this would 404 on a doubled path.
        ("https://openrouter.ai/api/v1/chat/completions", "https://openrouter.ai/api/v1"),
        ("https://openrouter.ai/api/v1/chat/completions/", "https://openrouter.ai/api/v1"),
        ("http://localhost:8000/v1/completions", "http://localhost:8000/v1"),
        ("http://localhost:8000/v1/models", "http://localhost:8000/v1"),
        ("http://localhost:8000/v1/embeddings", "http://localhost:8000/v1"),
        ("localhost:8000/v1", "http://localhost:8000/v1"),  # missing scheme
    ],
)
def test_normalise_base_url_corrects_and_reports(given, expected):
    from paratext.config import normalise_base_url

    url, note = normalise_base_url(given)
    assert url == expected
    assert note and expected in note


@pytest.mark.parametrize(
    "given",
    [
        "http://localhost:8000/v1",
        "https://openrouter.ai/api/v1",
        "https://example.org/v1/",  # trailing slash is trimmed silently
    ],
)
def test_normalise_base_url_stays_quiet_when_already_right(given):
    from paratext.config import normalise_base_url

    url, note = normalise_base_url(given)
    assert url == given.rstrip("/")
    assert note is None


def _write_config(tmp_path, body):
    (tmp_path / "paratext.toml").write_text(body)


def test_api_key_in_file_flags_a_remote_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, 'api-key = "sk-or-secret"\n')
    assert cfg.api_key_in_file(None, "https://openrouter.ai/api/v1") is True


def test_api_key_in_file_flags_a_per_project_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, '[project.my-cards]\napi-key = "sk-or-secret"\n')
    assert cfg.api_key_in_file("my-cards", "https://openrouter.ai/api/v1") is True


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://box.local/v1"],
)
def test_api_key_in_file_ignores_local_servers(tmp_path, monkeypatch, base_url):
    # Local servers ignore the key, so there's no secret to leak.
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, 'api-key = "EMPTY"\n')
    assert cfg.api_key_in_file(None, base_url) is False


def test_api_key_in_file_quiet_when_the_key_is_not_in_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, 'model = "m"\n')
    monkeypatch.setenv("PARATEXT_API_KEY", "sk-or-secret")  # env is the right place
    assert cfg.api_key_in_file(None, "https://openrouter.ai/api/v1") is False
