"""Loose-JSON parsing for non-structured completions."""

from paratext.extract import _parse_loose_json


def test_plain_json():
    assert _parse_loose_json('{"a": 1}') == {"a": 1}


def test_fenced_json_block():
    assert _parse_loose_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_embedded_in_prose():
    assert _parse_loose_json('Here you go: {"a": 1} (done)') == {"a": 1}


def test_unparseable_returns_none():
    assert _parse_loose_json("not json at all") is None
