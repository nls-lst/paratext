"""Round resolution for `run`/`package`: a round == a prompt version."""

import json

import paratext.cli as cli


def _mk_round(root, project, n, prompt_hash):
    d = root / f"{project}-r{n}"
    d.mkdir(parents=True)
    (d / "samples.json").write_text(json.dumps([{"id": "x", "prompt_hash": prompt_hash}]))
    return d


def test_first_run_is_round_one(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "REVIEW_ROOT", tmp_path / "review")
    out, rnd, reuse = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r1" and rnd == 1 and reuse is False


def test_same_prompt_reuses_current_round(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    out, rnd, reuse = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r1" and rnd == 1 and reuse is True


def test_changed_prompt_rolls_to_next_round(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    out, rnd, reuse = cli._resolve_round("demo", "hashB", None)
    assert out.name == "demo-r2" and rnd == 2 and reuse is False


def test_rounds_are_per_project(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    _mk_round(review, "demo", 2, "hashB")
    _mk_round(review, "other", 1, "hashZ")
    # a new prompt for demo goes to r3; `other` is unaffected
    out, rnd, _ = cli._resolve_round("demo", "hashC", None)
    assert out.name == "demo-r3" and rnd == 3
    out, rnd, reuse = cli._resolve_round("other", "hashZ", None)
    assert out.name == "other-r1" and reuse is True


def test_forced_round_overrides(tmp_path, monkeypatch):
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    # --round 5 targets r5 even though it doesn't exist yet
    out, rnd, reuse = cli._resolve_round("demo", "hashA", 5)
    assert out.name == "demo-r5" and rnd == 5 and reuse is False
    # forcing an existing round reports reuse
    out, rnd, reuse = cli._resolve_round("demo", "anything", 1)
    assert out.name == "demo-r1" and reuse is True


def test_rounds_are_a_linear_history(tmp_path, monkeypatch):
    """Resolution compares against the latest round only, so reverting to an
    earlier prompt starts a fresh round rather than hopping back."""
    review = tmp_path / "review"
    monkeypatch.setattr(cli, "REVIEW_ROOT", review)
    _mk_round(review, "demo", 1, "hashA")
    _mk_round(review, "demo", 2, "hashB")
    # back to hashA (== r1's prompt, but not the latest) -> new round r3
    out, rnd, reuse = cli._resolve_round("demo", "hashA", None)
    assert out.name == "demo-r3" and rnd == 3 and reuse is False
