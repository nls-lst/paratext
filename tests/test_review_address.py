"""The review UI's ?project= links (PTX-79), checked by running address.js under node.

Skipped where node isn't installed: the module is plain ES with no DOM.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ADDRESS_JS = Path(__file__).parent.parent / "src/paratext/review/static/address.js"
NODE = shutil.which("node")

DATASETS = [
    {"name": "index-cards", "base": "index-cards", "round": 1},
    {"name": "index-cards-r3", "base": "index-cards", "round": 3},
    {"name": "index-cards-r2", "base": "index-cards", "round": 2},
    {"name": "issa", "base": "issa", "round": 1},
]


def run(calls: list[list]) -> list:
    """Each call is [function name, *args after the dataset list]."""
    script = (
        f"import * as a from {json.dumps(ADDRESS_JS.as_uri())};\n"
        f"const ds = {json.dumps(DATASETS)};\n"
        f"const calls = {json.dumps(calls)};\n"
        "console.log(JSON.stringify(calls.map(([f, ...args]) => a[f](ds, ...args))));\n"
    )
    out = subprocess.run([NODE, "--input-type=module", "-"], input=script,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_a_project_link_opens_its_newest_round():
    assert run([["datasetFromSearch", "?project=index-cards"],
                ["datasetFromSearch", "?project=issa&round="]]) == [
        {"name": "index-cards-r3"}, {"name": "issa"}]


def test_a_round_in_the_link_opens_that_round():
    assert run([["datasetFromSearch", "?project=index-cards&round=2"]]) == [
        {"name": "index-cards-r2"}]


def test_an_unknown_project_or_round_is_reported_not_guessed():
    assert run([["datasetFromSearch", "?project=nope"],
                ["datasetFromSearch", "?project=issa&round=4"],
                ["datasetFromSearch", ""]]) == [
        {"unknown": "nope"}, {"unknown": "issa round 4"}, {}]


def test_the_address_names_the_project_and_only_an_older_round():
    assert run([["searchForDataset", "index-cards-r3", ""],
                ["searchForDataset", "index-cards", "?project=issa"],
                ["searchForDataset", None, "?project=issa&round=1"]]) == [
        "?project=index-cards", "?project=index-cards&round=1", ""]


def test_other_parameters_in_the_address_are_kept():
    assert run([["searchForDataset", "issa", "?embed=1&project=old"]]) == [
        "?embed=1&project=issa"]


def test_writing_then_reading_an_address_gets_the_same_dataset():
    names = [d["name"] for d in DATASETS]
    searches = run([["searchForDataset", n, ""] for n in names])
    assert run([["datasetFromSearch", s] for s in searches]) == [{"name": n} for n in names]
