"""Review server: annotation store, dataset discovery, and view synthesis."""

import json

from paratext.review.server import (
    Store,
    discover_datasets,
    load_samples,
    synthesise_view,
)


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
