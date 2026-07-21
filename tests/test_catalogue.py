"""MARC / Dublin Core export: field mapping, wizard, serialization (paratext.catalogue)."""

import json
from xml.etree import ElementTree as ET

from PIL import Image

from paratext import catalogue
from paratext.records import Record
from paratext.review.server import Store

MARC_NS = "{http://www.loc.gov/MARC21/slim}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"


def _rec(label):
    return Record("1", "doc1", label, "verified", "good_enough", [], "", "h", None, [])


def test_infer_target_standard_names():
    assert catalogue.infer_target("title", "marc") == "245$a"
    assert catalogue.infer_target("personal_authors", "marc") == "100$a|700$a"
    assert catalogue.infer_target("publisher", "dc") == "publisher"
    assert catalogue.infer_target("PublicationDate".lower(), "marc") is None  # not a synonym
    assert catalogue.infer_target("publication_date", "marc") == "264$c"
    assert catalogue.infer_target("heading", "marc") is None  # non-standard → wizard


def test_resolve_mapping_config_precedence_and_skip(monkeypatch):
    monkeypatch.setattr(catalogue, "load_project_section",
                        lambda p, s: {"marc": {"heading": "245$a", "text": "500$a",
                                               "image_type": ""}})
    mapping, unmapped = catalogue.resolve_mapping("card-template", "marc")
    assert mapping == {"heading": "245$a", "text": "500$a"}  # image_type "" = explicit skip
    assert unmapped == []


def test_resolve_mapping_unmapped_when_no_config(monkeypatch):
    monkeypatch.setattr(catalogue, "load_project_section", lambda p, s: {})
    mapping, unmapped = catalogue.resolve_mapping("card-template", "marc")
    assert mapping == {}  # cards fields have no standard names
    assert set(unmapped) == {"image_type", "heading", "text"}


def test_marc_serialization_and_added_entries():
    mapping = {"title": "245$a", "subtitle": "245$b", "personal_authors": "100$a|700$a",
               "publisher": "264$b", "publication_place": "264$a",
               "publication_date": "264$c", "isbn": "020$a"}
    label = {"title": "T", "subtitle": "S", "personal_authors": ["A, A", "B, B"],
             "publisher": "P", "publication_place": "L", "publication_date": "1900",
             "isbn": "123"}
    root = catalogue.build_marc([_rec(label)], mapping).getroot()
    root = ET.fromstring(ET.tostring(root))  # prove it round-trips through a parser

    def subfields(tag, code):
        out = []
        for df in root.iter(f"{MARC_NS}datafield"):
            if df.get("tag") == tag:
                out += [sf.text for sf in df if sf.get("code") == code]
        return out

    assert subfields("245", "a") == ["T"] and subfields("245", "b") == ["S"]
    assert subfields("100", "a") == ["A, A"]  # first author → main entry
    assert subfields("700", "a") == ["B, B"]  # second → added entry
    assert subfields("264", "a") == ["L"] and subfields("264", "c") == ["1900"]
    assert subfields("020", "a") == ["123"]
    # 264 subfields tidied into $a $b $c order
    df264 = next(d for d in root.iter(f"{MARC_NS}datafield") if d.get("tag") == "264")
    assert [sf.get("code") for sf in df264] == ["a", "b", "c"]


def test_dc_serialization_repeats_and_isbn_prefix():
    mapping = {"title": "title", "personal_authors": "creator",
               "publication_date": "date", "isbn": "identifier"}
    label = {"title": "T", "personal_authors": ["A", "B"], "publication_date": "1900", "isbn": "9"}
    root = catalogue.build_dc([_rec(label)], mapping).getroot()
    assert [e.text for e in root.iter(f"{DC_NS}creator")] == ["A", "B"]
    ids = [e.text for e in root.iter(f"{DC_NS}identifier")]
    assert "doc1" in ids and "ISBN:9" in ids  # control id + prefixed isbn


def test_wizard_non_interactive_returns_empty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert catalogue.run_wizard("card-template", "marc", ["heading"]) == {}


def test_wizard_interactive_collects_answers(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["245$a", ""])  # heading → 245$a; notes → Enter = skip
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert catalogue.run_wizard("card-template", "marc", ["heading", "notes"]) == {
        "heading": "245$a", "notes": ""}


def test_persist_mapping_writes_block(tmp_path, monkeypatch):
    toml = tmp_path / "paratext.toml"
    monkeypatch.setattr(catalogue, "local_config_path", lambda: toml)
    catalogue.persist_mapping("card-template", "marc", {"heading": "245$a", "image_type": ""})
    text = toml.read_text()
    assert "[project.card-template.export.marc]" in text
    assert 'heading = "245$a"' in text and 'image_type = ""' in text


def _mk_round(tmp_path):
    d = tmp_path / "cards-r1"
    (d / "images").mkdir(parents=True)
    samples = []
    for sid, h in [("a", "Hume, David"), ("b", "Smith, Adam")]:
        rel = f"images/{sid}.jpg"
        Image.new("RGB", (8, 8), "white").save(d / rel)
        samples.append({"id": sid, "document_id": sid, "images": [rel], "prompt_hash": "h",
                        "model_output": {"image_type": "card", "heading": h, "text": "l"}})
    (d / "samples.json").write_text(json.dumps(samples))
    store = Store(d / "annotations.db")
    store.upsert("cards-r1", "a", {"model_correct": "good_enough"})
    store.upsert("cards-r1", "b", {"model_correct": "good_enough"})
    return d


def test_run_writes_marcxml(tmp_path, monkeypatch):
    d = _mk_round(tmp_path)
    monkeypatch.setattr(catalogue, "EXPORT_ROOT", tmp_path / "export")
    monkeypatch.setattr(catalogue, "load_project_section",
                        lambda p, s: {"marc": {"heading": "245$a", "text": "500$a",
                                               "image_type": ""}})
    summary = catalogue.run(d, "card-template", "marc", no_wizard=True)
    assert summary.records == 2 and summary.path.exists()
    assert summary.path.name == "cards-r1.marcxml"
    root = ET.parse(summary.path).getroot()
    assert len(list(root)) == 2  # a <record> per gold row
    headings = [sf.text for sf in root.iter(f"{MARC_NS}subfield")
                if sf.text in ("Hume, David", "Smith, Adam")]
    assert set(headings) == {"Hume, David", "Smith, Adam"}
