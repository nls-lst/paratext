"""Round resolution for `run`/`package`: a round == a prompt version."""

import json

import paratext.cli as cli


def _mk_round(root, project, n, prompt_hash, model=None):
    d = root / f"{project}-r{n}"
    d.mkdir(parents=True)
    (d / "samples.json").write_text(json.dumps([{"id": "x", "prompt_hash": prompt_hash}]))
    if model is not None:
        (d / "provenance.json").write_text(
            json.dumps({"prompt_hash": prompt_hash, "model": model})
        )
    return d


def test_first_run_is_round_one(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "REVIEW_ROOT", tmp_path / "review")
    out, rnd, reuse, _ = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r1" and rnd == 1 and reuse is False


def test_same_prompt_reuses_current_round(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    out, rnd, reuse, _ = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r1" and rnd == 1 and reuse is True


def test_changed_prompt_rolls_to_next_round(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    out, rnd, reuse, _ = cli._resolve_round("demo", "hashB", None)
    assert out.name == "demo-r2" and rnd == 2 and reuse is False


def test_rounds_are_per_project(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    _mk_round(review, "demo", 2, "hashB")
    _mk_round(review, "other", 1, "hashZ")
    # a new prompt for demo goes to r3; `other` is unaffected
    out, rnd, *_ = cli._resolve_round("demo", "hashC", None)
    assert out.name == "demo-r3" and rnd == 3
    out, rnd, reuse, _ = cli._resolve_round("other", "hashZ", None)
    assert out.name == "other-r1" and reuse is True


def test_forced_round_overrides(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    # --round 5 targets r5 even though it doesn't exist yet
    out, rnd, reuse, _ = cli._resolve_round("demo", "hashA", 5)
    assert out.name == "demo-r5" and rnd == 5 and reuse is False
    # forcing an existing round reports reuse
    out, rnd, reuse, _ = cli._resolve_round("demo", "anything", 1)
    assert out.name == "demo-r1" and reuse is True


def test_rounds_are_a_linear_history(tmp_path, monkeypatch):
    """Resolution compares against the latest round only, so reverting to an
    earlier prompt starts a fresh round rather than hopping back."""
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    _mk_round(review, "demo", 2, "hashB")
    # back to hashA (== r1's prompt, but not the latest) -> new round r3
    out, rnd, reuse, _ = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r3" and rnd == 3 and reuse is False


# ── A round is a run configuration, not just a prompt ────────────────────────
# Annotations are keyed (dataset, sample_id), so reusing a round after a model
# swap leaves cataloguer verdicts attached by id to output nobody reviewed —
# silently mismatched rather than visibly clobbered.
def test_same_prompt_same_model_still_reuses(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA", model="qwen3-vl-30b")
    out, rnd, reuse, reason = cli._resolve_round("demo", "hashA", None, model="qwen3-vl-30b")
    assert out.name == "demo-r1" and rnd == 1 and reuse is True and reason is None


def test_changed_model_rolls_to_a_new_round(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA", model="qwen3-vl-30b")
    out, rnd, reuse, reason = cli._resolve_round("demo", "hashA", None, model="qwen3.8-27b")
    assert out.name == "demo-r2" and rnd == 2 and reuse is False
    assert "model changed" in reason and "qwen3-vl-30b → qwen3.8-27b" in reason


def test_a_round_that_doesnt_record_its_model_is_not_reused(tmp_path, monkeypatch):
    # Packaged before provenance.json existed: we can't confirm it matches, and
    # a spurious extra round is far cheaper than a silent mismatch.
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")  # no provenance.json
    out, rnd, reuse, reason = cli._resolve_round("demo", "hashA", None, model="qwen3.8-27b")
    assert out.name == "demo-r2" and reuse is False
    assert "doesn't record which model" in reason


def test_no_model_given_falls_back_to_prompt_only(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA", model="qwen3-vl-30b")
    out, rnd, reuse, reason = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r1" and reuse is True and reason is None


def test_forced_round_ignores_the_model_check(tmp_path, monkeypatch):
    # --round N is an explicit instruction; it stays an override.
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA", model="qwen3-vl-30b")
    out, rnd, reuse, reason = cli._resolve_round("demo", "hashA", 1, model="other")
    assert out.name == "demo-r1" and rnd == 1 and reuse is True and reason is None


def test_changed_prompt_reports_why(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA", model="m")
    _, _, reuse, reason = cli._resolve_round("demo", "hashB", None, model="m")
    assert reuse is False and reason == "the prompt changed"


def _view(fields, version="v1"):
    return {
        "contract_version": 1,
        "schema": "cards",
        "schema_version": version,
        "panels": [{"source": "model_output", "title": "Model output", "fields": fields}],
    }


def _round_dir(tmp_path, name, n, fields):
    import json

    d = tmp_path / name
    d.mkdir()
    (d / "view.json").write_text(json.dumps(_view(fields)))
    (d / "samples.json").write_text("[]")
    return {"name": name, "base": "cards", "round": n, "dir": d}


def test_diff_fields_reports_added_removed_and_retyped():
    from paratext.datasets import diff_fields

    before = [{"key": "a", "label": "A", "type": "string"},
              {"key": "b", "label": "B", "type": "string"}]
    after = [{"key": "a", "label": "A", "type": "integer"},
             {"key": "c", "label": "C", "type": "string"}]
    d = diff_fields(before, after)
    assert [f["key"] for f in d["added"]] == ["c"]
    assert [f["key"] for f in d["removed"]] == ["b"]
    assert d["retyped"] == [{"key": "a", "label": "A", "from": "string", "to": "integer"}]


def test_diff_fields_is_empty_when_nothing_moved():
    from paratext.datasets import diff_fields

    fields = [{"key": "a", "label": "A", "type": "string"}]
    assert diff_fields(fields, list(fields)) == {"added": [], "removed": [], "retyped": []}


def test_schema_history_orders_rounds_and_diffs_each_against_the_last(tmp_path):
    from paratext.datasets import schema_history

    r1 = _round_dir(tmp_path, "cards-r1", 1, [{"key": "a", "label": "A", "type": "string"}])
    r2 = _round_dir(tmp_path, "cards-r2", 2, [
        {"key": "a", "label": "A", "type": "string"},
        {"key": "b", "label": "B", "type": "integer"},
    ])
    # Out of order in, oldest first out.
    hist = schema_history([r2, r1])
    assert [r["round"] for r in hist] == [1, 2]
    assert hist[0]["changes"] is None  # nothing to compare the first round to
    assert [f["key"] for f in hist[1]["changes"]["added"]] == ["b"]


def test_schema_history_of_a_single_round(tmp_path):
    from paratext.datasets import schema_history

    r1 = _round_dir(tmp_path, "cards-r1", 1, [{"key": "a", "label": "A", "type": "string"}])
    hist = schema_history([r1])
    assert len(hist) == 1 and hist[0]["changes"] is None
