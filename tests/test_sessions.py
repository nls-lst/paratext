"""Per-attendee workspaces for workshop mode."""

import pytest

from paratext.review.sessions import Sessions, new_session_id, valid_session_id


@pytest.mark.parametrize(
    "sid,ok",
    [
        (new_session_id(), True),
        ("a" * 16, True),
        ("short", False),
        ("", False),
        (None, False),
        ("../../etc/passwd", False),      # the reason this check exists
        ("with/slash1234567", False),
        ("with space123456", False),
        ("a" * 65, False),
    ],
)
def test_valid_session_id(sid, ok):
    assert valid_session_id(sid) is ok


def test_a_traversing_cookie_never_resolves_to_a_path(tmp_path):
    s = Sessions(tmp_path)
    assert s.get("../../etc") is None
    assert s.exists("../../etc") is False


def test_create_then_get_round_trips(tmp_path):
    s = Sessions(tmp_path)
    made = s.create()
    assert made.data_dir.is_dir()
    found = s.get(made.id)
    assert found is not None and found.id == made.id


def test_get_or_create_flags_a_new_session(tmp_path):
    s = Sessions(tmp_path)
    first, created = s.get_or_create(None)
    assert created is True
    again, created = s.get_or_create(first.id)
    assert created is False and again.id == first.id


def test_an_unknown_id_yields_a_fresh_session(tmp_path):
    # A stale cookie from a previous container must not 500 the page.
    s = Sessions(tmp_path)
    session, created = s.get_or_create(new_session_id())
    assert created is True and session.data_dir.is_dir()


def test_sessions_do_not_share_state(tmp_path):
    s = Sessions(tmp_path)
    a, b = s.create(), s.create()
    a.write_state({"prompt": "mine"})
    assert b.read_state() == {}
    assert a.read_state()["prompt"] == "mine"
    assert a.db_path != b.db_path


def test_state_survives_a_reread_and_tolerates_junk(tmp_path):
    s = Sessions(tmp_path)
    session = s.create()
    assert session.read_state() == {}          # nothing written yet
    session.write_state({"fields": [{"name": "title"}]})
    assert s.get(session.id).read_state()["fields"] == [{"name": "title"}]
    session.state_path.write_text("{not json")
    assert session.read_state() == {}


def test_examples_are_seeded_into_each_session(tmp_path):
    example = tmp_path / "shipped" / "cards-r1"
    (example / "images").mkdir(parents=True)
    (example / "samples.json").write_text("[]")

    s = Sessions(tmp_path / "sessions", examples=[example])
    session = s.create()
    seeded = session.data_dir / "cards-r1"
    assert seeded.is_dir()
    assert (seeded / "samples.json").read_text() == "[]"


def test_reset_removes_one_session_only(tmp_path):
    s = Sessions(tmp_path)
    a, b = s.create(), s.create()
    assert s.reset(a.id) is True
    assert s.get(a.id) is None and s.get(b.id) is not None
    assert s.reset(a.id) is False       # already gone
    assert s.all_ids() == [b.id]


def _round(tmp_path, name, n, fields, prompt):
    import json

    d = tmp_path / name
    (d / "images").mkdir(parents=True)
    (d / "samples.json").write_text("[]")
    (d / "provenance.json").write_text(json.dumps({"prompt": prompt}))
    (d / "view.json").write_text(json.dumps({
        "schema_version": "v1",
        "panels": [{"source": "model_output",
                    "fields": [{"key": k, "label": k, "type": "string"} for k in fields]}],
    }))
    return {"name": name, "base": "cards", "round": n, "dir": d}


def test_workshop_defaults_seed_from_the_newest_round(tmp_path):
    from paratext.review.server import _workshop_defaults

    r1 = _round(tmp_path, "cards-r1", 1, ["title"], "old prompt")
    r2 = _round(tmp_path, "cards-r2", 2, ["title", "author"], "new prompt")
    d = _workshop_defaults([r1, r2], {"model": "m", "base_url": "u", "source": "/imgs"})

    assert d["prompt"] == "new prompt"
    assert [f["name"] for f in d["fields"]] == ["title", "author"]
    assert d["project"] == "cards" and d["model"] == "m" and d["source"] == "/imgs"


def test_workshop_defaults_survive_having_no_rounds(tmp_path):
    from paratext.review.server import _workshop_defaults

    d = _workshop_defaults([], {})
    assert d["prompt"] == "" and d["fields"] == [] and d["api_key"] == "EMPTY"


class _FakeHandler:
    """Just enough of the handler to exercise the cookie rule."""

    from paratext.review.server import Handler

    _behind_https = Handler._behind_https
    session_cookie = Handler.session_cookie

    def __init__(self, headers):
        self.headers = headers


def test_cookie_is_lax_on_a_plain_http_server():
    c = _FakeHandler({}).session_cookie("abc")
    assert "SameSite=Lax" in c and "Secure" not in c and "Partitioned" not in c


def test_cookie_is_cross_site_safe_behind_https():
    # A Space opened from its Hub page is an iframe on another origin, so the
    # cookie must be SameSite=None; without Secure a browser rejects that.
    c = _FakeHandler({"x-forwarded-proto": "https"}).session_cookie("abc")
    assert "SameSite=None" in c and "Secure" in c and "Partitioned" in c
    assert "SameSite=Lax" not in c


def test_a_proxy_chain_still_counts_as_https():
    c = _FakeHandler({"x-forwarded-proto": "https, http"}).session_cookie("abc")
    assert "SameSite=None" in c


def test_http_forwarded_proto_stays_lax():
    c = _FakeHandler({"x-forwarded-proto": "http"}).session_cookie("abc")
    assert "SameSite=Lax" in c and "Secure" not in c


def test_the_cookie_carries_the_session_id():
    assert "pt_session=abc123;" in _FakeHandler({}).session_cookie("abc123")
