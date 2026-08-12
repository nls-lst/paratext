"""Review server: annotation store, dataset discovery, and view synthesis."""

import json

from paratext.datasets import discover_datasets, load_samples, synthesise_view
from paratext.store import Store


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "a.db")
    assert store.get("ds", "x") is None
    store.upsert("ds", "x", {"model_correct": "good_enough", "notes": "ok",
                             "corrections": {"heading": "Fixed"}})
    a = store.get("ds", "x")
    assert a["model_correct"] == "good_enough"
    assert a["corrections"] == {"heading": "Fixed"}
    assert a["updated_at"]
    store.reset("ds")
    assert store.get("ds", "x") is None


def test_gold_labels_roundtrip(tmp_path):
    store = Store(tmp_path / "a.db")
    assert store.get_gold("ds", "x") is None
    assert store.all_gold("ds") == []
    store.upsert_gold("ds", "x", {"output": {"heading": "Fixed", "entries": []},
                                  "fields": ["heading"], "annotator": "sam"})
    g = store.get_gold("ds", "x")
    assert g["output"] == {"heading": "Fixed", "entries": []}
    assert g["fields"] == ["heading"] and g["annotator"] == "sam" and g["updated_at"]
    assert [r["sample_id"] for r in store.all_gold("ds")] == ["x"]
    # Upsert replaces; delete removes; the corrections column is untouched.
    store.upsert_gold("ds", "x", {"output": {"heading": "Again"}, "fields": ["heading"]})
    assert store.get_gold("ds", "x")["output"] == {"heading": "Again"}
    store.delete_gold("ds", "x")
    assert store.get_gold("ds", "x") is None


def test_gold_survives_reset_scope(tmp_path):
    store = Store(tmp_path / "a.db")
    store.upsert_gold("ds", "x", {"output": {"a": 1}})
    store.reset("other")  # different dataset — gold stays
    assert store.get_gold("ds", "x") is not None
    store.reset("ds")  # same dataset — gold cleared too
    assert store.get_gold("ds", "x") is None


def test_review_stats_counts_corrected_and_eval_gold():
    from paratext.datasets import review_stats

    anns = [
        {"sample_id": "1", "model_correct": "good_enough", "catalogue_correct": None},
        {"sample_id": "2", "model_correct": "not_accurate", "catalogue_correct": None},
        {"sample_id": "3", "model_correct": "needs_tweaks", "catalogue_correct": None},
    ]
    stats = review_stats(5, anns, gold_ids={"2", "3"})
    assert stats["corrected"] == 2
    # eval gold = good_enough (1) ∪ corrected (2,3) = 3 distinct samples
    assert stats["eval_gold"] == 3
    # Back-compat: no gold_ids → corrected 0, eval_gold = good_enough count.
    assert review_stats(5, anns)["eval_gold"] == 1


def _write_dataset(d, name, records, view=None):
    sub = d / name
    sub.mkdir(parents=True)
    (sub / "samples.json").write_text(json.dumps(records))
    if view is not None:
        (sub / "view.json").write_text(json.dumps(view))


def test_discover_single_and_multi(tmp_path):
    # single dataset: data_dir itself holds samples.json
    (tmp_path / "samples.json").write_text(json.dumps([{"id": "1", "schema": "demo"}]))
    single = discover_datasets(tmp_path)
    assert len(single) == 1 and single[0]["name"] == tmp_path.name

    # multi: subdirs, with a round suffix
    parent = tmp_path / "data"
    _write_dataset(parent, "cards", [{"id": "1"}])
    _write_dataset(parent, "cards-r2", [{"id": "1"}, {"id": "2"}])
    multi = {d["name"]: d for d in discover_datasets(parent)}
    assert multi["cards-r2"]["base"] == "cards" and multi["cards-r2"]["round"] == 2
    assert multi["cards"]["round"] == 1


def test_load_samples_rewrites_image_paths(tmp_path):
    _write_dataset(tmp_path, "ds", [{"id": "s1", "images": ["images/s1/card.jpg"]}])
    ds = discover_datasets(tmp_path)[0]
    rewritten = load_samples(ds)[0]["images"]
    assert rewritten == ["images/ds/s1/card.jpg"]


def test_synthesise_view_infers_types_and_layout(tmp_path):
    samples = [
        {"id": "1", "ground_truth": {"title": "T"},
         "model_output": {"title": "T", "flagged": True, "entries": []}},
        {"id": "2", "ground_truth": {"title": "U"},
         "model_output": {"title": "U", "flagged": False, "entries": [{"x": 1}]}},
    ]
    view = synthesise_view({"schema": "demo", "base": "demo"}, samples)
    assert view["layout"] == "stacked" and view["ground_truth"] is True
    model_panel = next(p for p in view["panels"] if p["source"] == "model_output")
    types = {f["key"]: f["type"] for f in model_panel["fields"]}
    # `entries` is empty in the first sample but an object-list in the second
    assert types == {"title": "string", "flagged": "bool", "entries": "entries"}


def test_serve_honours_host_and_db(tmp_path, monkeypatch):
    # serve() should bind the requested host/port and put the annotation store at
    # the given --db path (rather than the default <data_dir>/annotations.db).
    import json as _json

    from paratext.review import server as srv

    (tmp_path / "samples.json").write_text(_json.dumps([{"id": "1", "schema": "demo"}]))
    captured = {}

    class FakeHTTPD:
        def __init__(self, addr, handler):
            captured["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt  # unblock serve() immediately

    monkeypatch.setattr(srv, "ThreadingHTTPServer", FakeHTTPD)
    db = tmp_path / "custom" / "annotations.db"
    db.parent.mkdir()
    srv.serve(tmp_path, port=4000, open_browser=False, host="0.0.0.0", db_path=db)

    assert captured["addr"] == ("0.0.0.0", 4000)
    assert db.exists()  # store created at the custom path
    assert not (tmp_path / "annotations.db").exists()  # not the default location


def test_review_cli_host_db_flags_and_defaults():
    import paratext.cli as cli

    parser, *_ = cli._build_parser()
    a = parser.parse_args(["review", "--host", "0.0.0.0", "--db", "/tmp/x.db", "somedir"])
    assert a.host == "0.0.0.0" and str(a.db) == "/tmp/x.db"
    d = parser.parse_args(["review", "somedir"])
    assert d.host == "127.0.0.1" and d.db is None  # safe defaults (local + nginx)


def test_api_projects_describes_installed_projects():
    """The Projects page reads installed state, so a stale install is visible."""
    from paratext.inspect import describe_all

    projects = {p["name"]: p for p in describe_all()}
    assert "card-template" in projects
    p = projects["card-template"]
    assert p["schema_version"] == "v1"
    # The providing *distribution*, which is `paratext-cli` — the import package
    # and the CLI are both `paratext`.
    assert p["entry_point"]["package"] == "paratext-cli"
    assert p["source"]["kind"] == "images"
    # The bundled example must ship with the card-specific preprocessing off.
    assert p["source"]["crop"] is False
    assert p["source"]["verso_filter"] is False
    assert p["audit"] == []
    assert {f["key"] for f in p["view"]["panels"][0]["fields"]} == {"heading", "text"}


def test_describe_all_survives_a_broken_project(monkeypatch):
    """One broken plug-in must not blank the whole page."""
    from paratext import inspect as inspect_mod

    monkeypatch.setattr(inspect_mod, "describe", lambda p: 1 / 0)
    out = {p["name"]: p for p in inspect_mod.describe_all()}
    assert "ZeroDivisionError" in out["card-template"]["error"]


def test_serve_allows_missing_default_root(tmp_path, monkeypatch):
    """A fresh install has no ./review yet — Projects must still be reachable."""
    import paratext.review.server as srv

    monkeypatch.chdir(tmp_path)
    started = {}

    class _FakeServer:
        def __init__(self, addr, handler):
            started["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(srv, "ThreadingHTTPServer", _FakeServer)
    srv.serve(tmp_path / "review", port=0, open_browser=False, allow_empty=True)
    assert (tmp_path / "review").is_dir()
    assert started["addr"] == ("127.0.0.1", 0)


def test_serve_rejects_missing_explicit_dir(tmp_path):
    """An explicitly-passed path that isn't there is still a typo, not a fresh install."""
    import pytest

    import paratext.review.server as srv

    with pytest.raises(SystemExit):
        srv.serve(tmp_path / "nope", port=0, open_browser=False, allow_empty=False)


def test_store_is_safe_under_concurrent_access(tmp_path):
    """One connection is shared across a ThreadingHTTPServer; without a lock,
    concurrent requests raise sqlite3.InterfaceError ("bad parameter or other
    API misuse"). Seen live on /api/table, which the stats page fetches
    alongside /api/stats."""
    import threading

    store = Store(tmp_path / "c.db")
    for i in range(50):
        store.upsert("ds", f"s{i}", {"model_correct": "good_enough"})

    errors = []

    def hammer():
        try:
            for _ in range(40):
                store.all("ds")
                store.all_gold("ds")
                store.upsert("ds", "s0", {"model_correct": "needs_tweaks"})
        except Exception as e:  # noqa: BLE001 — the point is to catch anything
            errors.append(e)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent access failed: {errors[:3]}"
