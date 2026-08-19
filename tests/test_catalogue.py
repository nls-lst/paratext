"""MARC / Dublin Core export: field mapping, wizard, serialization (paratext.catalogue)."""

import json
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from paratext import catalogue
from paratext.records import Record
from paratext.store import Store

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

    # $a carries the ISBD separator because a subtitle follows it
    assert subfields("245", "a") == ["T : "] and subfields("245", "b") == ["S"]
    assert subfields("100", "a") == ["A, A"]  # first author → main entry
    assert subfields("700", "a") == ["B, B"]  # second → added entry
    # 264 carries ISBD punctuation too: "L : P, 1900"
    assert subfields("264", "a") == ["L : "] and subfields("264", "b") == ["P, "]
    assert subfields("264", "c") == ["1900."]
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


def test_export_bytes_scopes_and_marc(tmp_path, monkeypatch):
    """MARC/DC export builds in memory, honours scope, and reads gold from the
    passed db_path (not dataset_dir/annotations.db)."""
    from paratext.catalogue import export_bytes, records_for_scope

    d = tmp_path / "card-template-r1"
    d.mkdir()
    (d / "samples.json").write_text(json.dumps([
        {"id": "1", "model_output": {"heading": "A", "text": "x"}},
        {"id": "2", "model_output": {"heading": "B", "text": "y"}},
    ]))
    (d / "provenance.json").write_text(json.dumps({"project": "card-template"}))
    gold_db = tmp_path / "gold.db"
    store = Store(gold_db)
    store.upsert("card-template-r1", "1", {"model_correct": "good_enough"})

    # everything = both samples; good_enough = only the verified one — from gold_db
    assert len(records_for_scope(d, "card-template", "everything", db_path=gold_db)) == 2
    assert len(records_for_scope(d, "card-template", "good_enough", db_path=gold_db)) == 1

    # card fields aren't standard MARC names, so give a mapping (as the CLI would).
    monkeypatch.setattr(catalogue, "load_project_section",
                        lambda p, s: {"marc": {"heading": "245$a", "text": "500$a"}})
    xml, n = export_bytes(d, "card-template", "marc", "everything", db_path=gold_db)
    assert n == 2 and xml.startswith(b"<?xml")
    assert b"MARC21/slim" in xml


# ── 245 nonfiling indicator ──────────────────────────────────────────────────
# ind2 tells a catalogue how many leading characters to skip when sorting, so
# "The Bruce" files under B. The count includes the article's trailing space.
@pytest.mark.parametrize("title,expected", [
    ("The Bruce", "4"),
    ("An Account of the Highlands", "3"),
    ("A History of Scotland", "2"),
    ("Waverley", "0"),
    ("", "0"),
    ("the bruce", "4"),          # case-insensitive
    ("  The Bruce", "4"),        # leading whitespace ignored
    ("Theatre Royal", "0"),      # "The" without a space is not an article
    ("Anderson's Almanac", "0"),
    ("Aberdeen", "0"),
    ("A", "0"),                  # bare article, nothing to skip past
])
def test_nonfiling_indicator(title, expected):
    assert catalogue.nonfiling_indicator(title) == expected


def _indicators(root, tag):
    for df in root.iter(f"{MARC_NS}datafield"):
        if df.get("tag") == tag:
            return df.get("ind1"), df.get("ind2")
    return None


def _build(label, mapping):
    root = catalogue.build_marc([_rec(label)], mapping).getroot()
    return ET.fromstring(ET.tostring(root))


def test_245_indicators_reflect_the_article_and_the_main_entry():
    mapping = {"title": "245$a", "personal_authors": "100$a|700$a"}
    root = _build({"title": "The Bruce", "personal_authors": ["Barbour, John"]}, mapping)
    assert _indicators(root, "245") == ("1", "4")  # 1XX present → title added entry


def test_245_ind1_is_zero_without_a_1xx():
    root = _build({"title": "An Account"}, {"title": "245$a"})
    assert _indicators(root, "245") == ("0", "3")


def test_corporate_names_are_in_direct_order():
    # 110/710 ind1=2 ("name in direct order"), unlike a personal name's 1
    # ("surname first"). Both were emitting 1 before.
    mapping = {"corporate_authors": "110$a|710$a", "title": "245$a"}
    root = _build(
        {"title": "Reports", "corporate_authors": ["Bank of Scotland", "Royal Society"]},
        mapping,
    )
    assert _indicators(root, "110") == ("2", " ")
    assert _indicators(root, "710") == ("2", " ")


def test_personal_names_keep_indicator_one():
    mapping = {"personal_authors": "100$a|700$a", "title": "245$a"}
    root = _build({"title": "Poems", "personal_authors": ["Burns, Robert", "Scott, W"]}, mapping)
    assert _indicators(root, "100") == ("1", " ")
    assert _indicators(root, "700") == ("1", " ")


def test_title_without_a_subtitle_gets_no_separator():
    root = _build({"title": "Waverley"}, {"title": "245$a", "subtitle": "245$b"})
    a = [sf.text for df in root.iter(f"{MARC_NS}datafield") if df.get("tag") == "245"
         for sf in df if sf.get("code") == "a"]
    assert a == ["Waverley"]


def test_separator_is_not_doubled_on_a_title_that_already_ends_in_a_colon():
    root = _build({"title": "Waverley :", "subtitle": "a novel"},
                  {"title": "245$a", "subtitle": "245$b"})
    a = [sf.text for df in root.iter(f"{MARC_NS}datafield") if df.get("tag") == "245"
         for sf in df if sf.get("code") == "a"]
    assert a == ["Waverley : "]


# ── 264 ISBD punctuation ─────────────────────────────────────────────────────
# "Place : Publisher, Date". The separator belongs to the subfield it follows,
# so which subfield carries it depends on which neighbours exist.
_IMPRINT = {"publication_place": "264$a", "publisher": "264$b", "publication_date": "264$c"}


def _imprint(**label):
    root = _build(label, _IMPRINT)
    df = next(d for d in root.iter(f"{MARC_NS}datafield") if d.get("tag") == "264")
    return {sf.get("code"): sf.text for sf in df}


def test_place_publisher_and_date():
    assert _imprint(publication_place="Edinburgh", publisher="Blackwood",
                    publication_date="1791") == {
        "a": "Edinburgh : ", "b": "Blackwood, ", "c": "1791."}


def test_date_without_a_publisher_puts_the_comma_on_the_place():
    assert _imprint(publication_place="Edinburgh", publication_date="1791") == {
        "a": "Edinburgh, ", "c": "1791."}


def test_date_without_a_place_puts_the_comma_on_the_publisher():
    assert _imprint(publisher="Blackwood", publication_date="1791") == {
        "b": "Blackwood, ", "c": "1791."}


def test_place_and_publisher_without_a_date_take_only_the_colon():
    assert _imprint(publication_place="Edinburgh", publisher="Blackwood") == {
        "a": "Edinburgh : ", "b": "Blackwood"}


def test_a_lone_date_still_gets_its_full_stop():
    assert _imprint(publication_date="1791") == {"c": "1791."}


def test_a_lone_place_is_left_alone():
    assert _imprint(publication_place="Edinburgh") == {"a": "Edinburgh"}


def test_imprint_punctuation_is_not_doubled():
    # The card may already carry the ISBD marks; transcribing them shouldn't
    # produce "Edinburgh : : Blackwood, , 1791".
    assert _imprint(publication_place="Edinburgh :", publisher="Blackwood,",
                    publication_date="1791") == {
        "a": "Edinburgh : ", "b": "Blackwood, ", "c": "1791."}


# ── Leader ───────────────────────────────────────────────────────────────────
def test_leader_is_24_characters():
    # Fixed-length field: a miscount silently shifts every position after it.
    assert len(catalogue.LEADER) == 24


def test_leader_positions():
    ldr = catalogue.LEADER
    assert ldr[5:8] == "nam"   # new / language material / monograph
    assert ldr[9] == "a"       # Unicode
    assert ldr[17] == "5"      # encoding level: partial (preliminary)
    assert ldr[18] == "i"      # ISBD punctuation included
    assert ldr[19] == " "      # multipart level: not specified
    assert ldr[20:] == "4500"  # entry map


def test_leader_position_19_is_a_space_not_a_hash():
    # MARC docs render blank as "#"; the byte on the wire must be 0x20.
    assert "#" not in catalogue.LEADER


def test_leader_reaches_the_serialized_record():
    root = _build({"title": "Waverley"}, {"title": "245$a"})
    leader = root.find(f"{MARC_NS}record/{MARC_NS}leader")
    # Exact match, not a strip() — indentation leaking into a fixed-length field
    # would shift every position in it.
    assert leader is not None and leader.text == catalogue.LEADER


def test_date_full_stop_is_not_doubled():
    assert _imprint(publication_date="1791.")["c"] == "1791."


def test_date_full_stop_follows_a_bracketed_date():
    assert _imprint(publication_date="[1791]")["c"] == "[1791]."
