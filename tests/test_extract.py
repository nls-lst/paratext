"""Loose-JSON parsing for non-structured completions."""

import pytest
from pydantic import BaseModel

import paratext.extract as extract
from paratext.extract import _parse_loose_json
from paratext.io import read_provenance
from paratext.projects import Project, Sample
from paratext.runner import DEFAULT_MAX_TOKENS


def test_plain_json():
    assert _parse_loose_json('{"a": 1}') == {"a": 1}


def test_fenced_json_block():
    assert _parse_loose_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_embedded_in_prose():
    assert _parse_loose_json('Here you go: {"a": 1} (done)') == {"a": 1}


def test_unparseable_returns_none():
    assert _parse_loose_json("not json at all") is None


# ── max_tokens / extra_body resolution ───────────────────────────────────────
# The precedence chain (caller > project > framework default) and the extra_body
# merge both happen inside run(), before any model call, so they're checked here
# by capturing what run() would have passed to the runner.
class _Schema(BaseModel):
    title: str


def _project(**over) -> Project:
    kwargs = dict(
        name="t",
        schema_version="1",
        prompt="return title",
        schema=_Schema,
        iter_samples=lambda source, limit: iter([Sample("a", [], {})]),
    )
    kwargs.update(over)
    return Project(**kwargs)


@pytest.fixture
def captured(monkeypatch):
    """Run the pipeline against a stubbed model call, returning its kwargs."""
    calls: list[dict] = []

    def _fake(client, **kwargs):
        calls.append(kwargs)
        return _Schema(title="x")

    monkeypatch.setattr(extract, "call_structured", _fake)
    return calls


def _run(project, tmp_path, **over):
    extract.run(
        project,
        source=tmp_path,
        output=tmp_path / "out.jsonl",
        base_url="http://localhost:8000/v1",
        api_key="EMPTY",
        model="m",
        skip_preflight=True,
        **over,
    )


def test_max_tokens_defaults_to_the_framework_ceiling(tmp_path, captured):
    _run(_project(), tmp_path)
    assert captured[0]["max_tokens"] == DEFAULT_MAX_TOKENS


def test_a_project_can_raise_its_own_ceiling(tmp_path, captured):
    _run(_project(max_tokens=32768), tmp_path)
    assert captured[0]["max_tokens"] == 32768


def test_the_caller_beats_the_project(tmp_path, captured):
    _run(_project(max_tokens=32768), tmp_path, max_tokens=1024)
    assert captured[0]["max_tokens"] == 1024


def test_disable_thinking_sends_the_vllm_dialect(tmp_path, captured):
    _run(_project(), tmp_path)
    assert captured[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_config_extra_body_layers_over_the_project_hint(tmp_path, captured):
    # The point of the passthrough: a user on a provider that doesn't speak vLLM
    # can add its dialect without the project knowing that provider exists.
    _run(_project(), tmp_path, extra_body={"reasoning": {"enabled": False}})
    assert captured[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning": {"enabled": False},
    }


def test_extra_body_is_none_when_there_is_nothing_to_send(tmp_path, captured):
    _run(_project(disable_thinking=False), tmp_path)
    assert captured[0]["extra_body"] is None


def test_max_tokens_is_recorded_in_provenance(tmp_path, captured):
    _run(_project(), tmp_path, max_tokens=4096)
    assert read_provenance(tmp_path / "out.jsonl")["max_tokens"] == 4096


def _header(prompt_hash="aaa", model="m1"):
    return {"project": "p", "schema_version": "v1", "prompt_hash": prompt_hash,
            "prompt": "…", "model": model, "base_url": "u", "max_tokens": 8}


def test_guard_allows_a_matching_resume(tmp_path):
    from paratext.extract import _guard_stale_output
    from paratext.io import write_provenance_header

    out = tmp_path / "x.jsonl"
    write_provenance_header(out, _header())
    _guard_stale_output(out, _header(), "p", False)  # no raise
    assert out.exists()


def test_guard_refuses_a_changed_prompt(tmp_path):
    import pytest

    from paratext.extract import _guard_stale_output
    from paratext.io import write_provenance_header

    out = tmp_path / "x.jsonl"
    write_provenance_header(out, _header(prompt_hash="aaa"))
    with pytest.raises(SystemExit, match="prompt changed"):
        _guard_stale_output(out, _header(prompt_hash="bbb"), "p", False)


def test_guard_refuses_a_changed_model(tmp_path):
    import pytest

    from paratext.extract import _guard_stale_output
    from paratext.io import write_provenance_header

    out = tmp_path / "x.jsonl"
    write_provenance_header(out, _header(model="m1"))
    with pytest.raises(SystemExit, match="model changed"):
        _guard_stale_output(out, _header(model="m2"), "p", False)


def test_re_extract_discards_the_stale_file(tmp_path):
    from paratext.extract import _guard_stale_output
    from paratext.io import write_provenance_header

    out = tmp_path / "x.jsonl"
    write_provenance_header(out, _header(prompt_hash="aaa"))
    _guard_stale_output(out, _header(prompt_hash="bbb"), "p", True)
    assert not out.exists()


def test_guard_is_a_no_op_for_a_new_file(tmp_path):
    from paratext.extract import _guard_stale_output

    _guard_stale_output(tmp_path / "nope.jsonl", _header(), "p", False)
