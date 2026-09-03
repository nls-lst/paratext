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
