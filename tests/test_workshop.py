"""Schema-as-data for workshop mode."""

import pytest

from paratext.workshop import (
    build_schema,
    infer_type,
    normalise_fields,
    normalise_name,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("title", "text"),
        ("author", "text"),
        ("call_number", "text"),      # 'number' only counts as its own word
        ("page_count", "number"),
        ("year", "number"),
        ("is_illustrated", "yes/no"),
        ("has_plates", "yes/no"),
        ("subjects", "list"),
        ("tracings", "list"),
        ("price", "decimal"),
    ],
)
def test_infer_type(name, expected):
    assert infer_type(name) == expected


def test_infer_type_falls_back_to_text():
    assert infer_type("something_unguessable") == "text"
    assert infer_type("") == "text"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Page Count", "page_count"),
        ("  Title  ", "title"),
        ("call-number", "call_number"),
        ("2nd copy", "f_2nd_copy"),   # a name can't start with a digit
        ("class", "class_"),          # nor be a keyword
        ("!!!", ""),
    ],
)
def test_normalise_name(raw, expected):
    assert normalise_name(raw) == expected


def test_normalise_fields_drops_blanks_and_duplicates_keeping_order():
    fields = normalise_fields([
        {"name": "title"},
        {"name": ""},                      # the editor's trailing blank row
        {"name": "Title"},                 # same field, different case
        {"name": "page count"},
    ])
    assert [f["name"] for f in fields] == ["title", "page_count"]


def test_normalise_fields_infers_a_missing_or_unknown_type():
    fields = normalise_fields([
        {"name": "page_count"},
        {"name": "year", "type": "nonsense"},
        {"name": "title", "type": "list"},   # explicit and valid — kept
    ])
    assert [f["type"] for f in fields] == ["number", "number", "list"]


def test_build_schema_makes_every_field_optional():
    Model = build_schema([{"name": "title"}, {"name": "page_count"}])
    m = Model()  # nothing supplied — must not raise
    assert m.title is None and m.page_count is None


def test_build_schema_applies_types_and_descriptions():
    Model = build_schema([
        {"name": "page_count"},
        {"name": "subjects", "description": "what it is about"},
    ])
    props = Model.model_json_schema()["properties"]
    assert {"type": "integer"} in props["page_count"]["anyOf"]
    assert {"type": "array", "items": {"type": "string"}} in props["subjects"]["anyOf"]
    assert props["subjects"]["description"] == "what it is about"


def test_build_schema_coerces_and_validates():
    Model = build_schema([{"name": "page_count"}, {"name": "is_illustrated"}])
    assert Model(page_count="312").page_count == 312
    with pytest.raises(Exception):
        Model(page_count="not a number")


def test_build_schema_needs_at_least_one_field():
    with pytest.raises(ValueError, match="at least one field"):
        build_schema([])
    with pytest.raises(ValueError, match="at least one field"):
        build_schema([{"name": "   "}])


def test_workshop_run_disables_thinking_like_extract():
    # extract.run builds this from the project; the workshop path calls
    # call_structured directly, so it has to send the same hint or the model
    # reasons anyway and spends the token budget getting to the answer.
    import inspect

    from paratext.review import runs

    src = inspect.getsource(runs.extract_and_package)
    assert "enable_thinking" in src
    assert "extra_body=extra_body" in src


def test_workshop_run_caps_tokens_well_below_the_default():
    from paratext.review import runs
    from paratext.runner import DEFAULT_MAX_TOKENS

    # A card measures ~180 output tokens. The low cap is what makes a runaway
    # fail in seconds rather than spending ~85s of a workshop session.
    assert runs.WORKSHOP_MAX_TOKENS < DEFAULT_MAX_TOKENS
    assert runs.WORKSHOP_TIMEOUT_S < 600  # the SDK default read timeout


def test_friendly_failure_translates_a_runaway():
    from paratext.review.runs import friendly_failure

    # What the attendee actually hit: the model repeated itself until the JSON
    # was cut off. The pydantic trace names neither the cause nor the cure.
    exc = ValueError(
        "1 validation error for WorkshopRecord Invalid JSON: EOF while parsing "
        "a string at line 1 column 809 [type=json_invalid, input_value='{\"author\"...']"
    )
    msg = friendly_failure("01_003-actors-english-adh_00110", exc)
    assert msg.startswith("Card 01 —")
    assert "ran out of room" in msg
    assert "prompt" in msg
    assert "json_invalid" not in msg
    assert "pydantic" not in msg


def test_friendly_failure_translates_the_token_cap():
    from paratext.review.runs import friendly_failure

    exc = ValueError("model hit the 1024-token output cap before finishing.")
    msg = friendly_failure("04_x", exc)
    assert "ran out of room" in msg
    assert "--max-tokens" not in msg  # not reachable from a workshop Space


def test_friendly_failure_keeps_an_unknown_error_short():
    from paratext.review.runs import friendly_failure

    msg = friendly_failure("07_x", ValueError("something odd\nstack line\nstack line"))
    assert msg == "Card 07 — something odd"


def test_card_label_falls_back_to_the_id():
    from paratext.review.runs import _card_label

    assert _card_label("03_actors_0196") == "Card 03"
    assert _card_label("advocates-index-card-55") == "advocates-index-card-55"


def test_oauth_scopes_cover_inference():
    # Without `inference-api` the push works and every model call 401s — the
    # failure is at run time, long after consent, so assert it here.
    from paratext.review.hf_oauth import SCOPES

    assert "inference-api" in SCOPES.split()
    assert "write-repos" in SCOPES.split()  # still needed to publish


def test_run_prefers_the_callers_token_over_a_configured_key():
    # A deployment that sets no key makes signing in mandatory; a local
    # `paratext review --workshop` with a key configured still runs.
    import inspect

    from paratext.review import server

    src = inspect.getsource(server.Handler._api_workshop_run)
    assert 'api_key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""' in src
    assert 'api_key = api_key or cfg.get("api_key") or ""' in src
    assert "api_key=api_key" in src          # the caller's, not cfg["api_key"]
    assert 'api_key=cfg["api_key"]' not in src


def test_run_refuses_with_401_when_nobody_is_paying():
    import inspect

    from paratext.review import server

    src = inspect.getsource(server.Handler._api_workshop_run)
    assert "401" in src
    assert "your own inference" in src


def test_state_tells_the_browser_whether_sign_in_is_required():
    import inspect

    from paratext.review import server

    src = inspect.getsource(server.Handler._api_workshop_state)
    assert "needs_token" in src


def test_the_local_server_placeholder_is_not_treated_as_a_credential(monkeypatch):
    # "EMPTY" is what HARDCODED_DEFAULTS uses for local servers that ignore the
    # key. Left in place it makes a public deployment look authenticated, and
    # every run gets charged to whoever last configured a real key.
    import argparse

    from paratext import cli

    args = argparse.Namespace(workshop=True, workshop_source=None)
    monkeypatch.setattr(cli, "load_defaults", lambda _: {})
    assert cli._workshop_endpoint(args)["api_key"] is None


def test_a_real_configured_key_still_comes_through(monkeypatch):
    import argparse

    from paratext import cli

    args = argparse.Namespace(workshop=True, workshop_source=None)
    monkeypatch.setattr(cli, "load_defaults", lambda _: {"api_key": "a-real-key"})
    assert cli._workshop_endpoint(args)["api_key"] == "a-real-key"
