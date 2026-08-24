"""`paratext export --format marc|dc` — catalogue-record export.

Turns a reviewed round's gold records (the same human-approved set HF export ships,
via `records.select_records`) into **MARCXML** or **Dublin Core** so the metadata can
flow into a library catalogue / discovery layer. No new dependency: records are
serialized with the stdlib `xml.etree.ElementTree`.

Schema fields are mapped to MARC tags / DC elements. Fields with standard names
(title, author, publisher, …) are inferred automatically (`CANONICAL`); the rest are
filled by an interactive wizard and the answers persisted to `paratext.toml` under
`[project.<name>.export.marc]` / `[.dc]`. Unmapped fields are skipped with a warning,
never a hard error.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import load_project_section, local_config_path
from .projects import get_project
from .records import select_records

# Where export artifacts are written (shared with hf_export's EXPORT_ROOT default).
EXPORT_ROOT = Path("export")

# Canonical field-name synonyms → targets. `marc` is a "tag$sub" spec; a "|"-joined
# pair (e.g. "100$a|700$a") means: first value → first tag, remaining list values →
# second tag (author main-vs-added entries). `dc` is a Dublin Core element name.
# `None` = no sensible target for that format (skipped unless the wizard sets one).
CANONICAL: dict[str, dict] = {
    "title": {"marc": "245$a", "dc": "title"},
    "subtitle": {"marc": "245$b", "dc": "title"},
    "author": {"marc": "100$a|700$a", "dc": "creator"},
    "authors": {"marc": "100$a|700$a", "dc": "creator"},
    "creator": {"marc": "100$a|700$a", "dc": "creator"},
    "personal_author": {"marc": "100$a|700$a", "dc": "creator"},
    "personal_authors": {"marc": "100$a|700$a", "dc": "creator"},
    "corporate_author": {"marc": "110$a|710$a", "dc": "creator"},
    "corporate_authors": {"marc": "110$a|710$a", "dc": "creator"},
    "contributor": {"marc": "700$a", "dc": "contributor"},
    "publisher": {"marc": "264$b", "dc": "publisher"},
    "publication_place": {"marc": "264$a", "dc": None},
    "place": {"marc": "264$a", "dc": None},
    "publication_date": {"marc": "264$c", "dc": "date"},
    "date": {"marc": "264$c", "dc": "date"},
    "year": {"marc": "264$c", "dc": "date"},
    "isbn": {"marc": "020$a", "dc": "identifier"},
    "issn": {"marc": "022$a", "dc": "identifier"},
    "edition": {"marc": "250$a", "dc": None},
    "extent": {"marc": "300$a", "dc": "format"},
    "material_type": {"marc": "655$a", "dc": "type"},
    "type": {"marc": "655$a", "dc": "type"},
    "genre": {"marc": "655$a", "dc": "type"},
    "subject": {"marc": "650$a", "dc": "subject"},
    "subjects": {"marc": "650$a", "dc": "subject"},
    "language": {"marc": "041$a", "dc": "language"},
    "description": {"marc": "520$a", "dc": "description"},
    "notes": {"marc": "500$a", "dc": "description"},
    "note": {"marc": "500$a", "dc": "description"},
    "series": {"marc": "490$a", "dc": "relation"},
}

# Common targets shown in the wizard cheat-sheet.
MARC_HINTS = (
    "245$a title · 245$b subtitle · 100$a person · 110$a org · 264$a place · "
    "264$b publisher · 264$c date · 020$a ISBN · 250$a edition · 300$a extent · "
    "490$a series · 500$a note · 520$a summary · 650$a subject · 655$a genre · "
    "041$a language"
)
DC_ELEMENTS = (
    "title creator subject description publisher contributor date type format "
    "identifier source language relation coverage rights"
)


@dataclass
class CatalogueSummary:
    format: str
    records: int
    path: Path
    mapped: dict[str, str]
    skipped: list[str]  # schema fields with no target (dropped from records)


def _norm(name: str) -> str:
    return name.strip().lower()


def infer_target(field_name: str, fmt: str) -> str | None:
    """Best-guess MARC tag / DC element for a schema field by its name, or None."""
    entry = CANONICAL.get(_norm(field_name))
    return entry.get(fmt) if entry else None


def resolve_mapping(project: str, fmt: str) -> tuple[dict[str, str], list[str]]:
    """Return (field -> target) for every schema field of `project` in format `fmt`.

    Precedence per field: an explicit config value under
    `[project.<name>.export.<fmt>]` (a `""` there means *skip*, kept out of the map),
    else canonical inference, else it stays unmapped (returned in the second list).
    """
    schema_fields = list(get_project(project).schema.model_fields)
    cfg = load_project_section(project, "export").get(fmt) or {}
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    for f in schema_fields:
        if f in cfg:
            target = str(cfg[f]).strip()
            if target:  # "" in config = explicit skip
                mapping[f] = target
        else:
            target = infer_target(f, fmt)
            if target:
                mapping[f] = target
            else:
                unmapped.append(f)
    return mapping, unmapped


def resolve_ai_note(project: str, override: str | None = None, *, date=None) -> str | None:
    """Text for the AI-assistance note, or None when the record should carry none.

    Precedence: an explicit `override` (the CLI flag or the export modal) beats
    `ai-note` under `[project.<name>.export]`. `true` there means the default
    wording; a string replaces it; `false`/absent means no note. `{date}` in the
    wording is filled with dd/mm/yy.
    """
    from datetime import date as _date

    value: object
    if override is not None:
        value = override
    else:
        value = load_project_section(project, "export").get("ai_note")
    if value is None or value is False:
        return None
    text = DEFAULT_AI_NOTE if value is True else str(value).strip()
    if not text:
        return None
    return text.replace("{date}", (date or _date.today()).strftime("%d/%m/%y"))


# ── Wizard ────────────────────────────────────────────────────────────────────
def run_wizard(project: str, fmt: str, unmapped: list[str]) -> dict[str, str]:
    """Interactively map the `unmapped` fields; returns the chosen field->target
    (a field the user skips is recorded as `""` so it isn't asked again). Caller
    persists the result. No-op returning {} on a non-TTY."""
    if not unmapped or not sys.stdin.isatty():
        return {}
    hints = MARC_HINTS if fmt == "marc" else DC_ELEMENTS
    kind = "MARC tag (e.g. 500$a)" if fmt == "marc" else "DC element (e.g. subject)"
    print(f"\n{len(unmapped)} field(s) have no {fmt.upper()} mapping. Common targets:")
    print(f"  {hints}")
    chosen: dict[str, str] = {}
    for f in unmapped:
        ans = input(f"  {f} → {kind} (Enter to skip): ").strip()
        chosen[f] = ans  # "" = skip, recorded so we don't ask next time
    return chosen


def persist_mapping(project: str, fmt: str, chosen: dict[str, str]) -> Path | None:
    """Append a `[project.<name>.export.<fmt>]` block to paratext.toml so the mapping
    (including skips as empty strings) is reused. Returns the config path, or None."""
    if not chosen:
        return None
    path = local_config_path()
    lines = [f'\n[project.{project}.export.{fmt}]']
    for f, target in chosen.items():
        lines.append(f'{f} = "{target}"')
    with path.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


# ── Serialization ─────────────────────────────────────────────────────────────
def _as_list(value) -> list[str]:
    """Normalise a field value to a list of non-empty strings."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v not in (None, "")]
    if isinstance(value, bool):
        return [("true" if value else "false")]
    return [str(value)]


def _split_marc(spec: str) -> list[tuple[str, str]]:
    """"245$a" → [("245","a")]; "100$a|700$a" → [("100","a"),("700","a")]."""
    out = []
    for part in spec.split("|"):
        tag, _, sub = part.partition("$")
        out.append((tag.strip(), (sub or "a").strip()))
    return out


# 245 second indicator = how many leading characters a sort should skip, so a
# title filed under its first significant word. The count includes the trailing
# space: "The " is 4, "An " 3, "A " 2, anything else 0.
_NONFILING = (("the ", "4"), ("an ", "3"), ("a ", "2"))


def nonfiling_indicator(title: str) -> str:
    """MARC 245 ind2 for `title` — the number of characters to skip when sorting."""
    lowered = (title or "").lstrip().lower()
    for article, indicator in _NONFILING:
        if lowered.startswith(article):
            return indicator
    return "0"


def _marc_indicators(tag: str, has_author: bool, title: str = "") -> tuple[str, str]:
    if tag == "245":
        # ind1 = whether a title added entry is needed: 0 when the title is the
        # main entry, 1 when a 1XX holds it.
        return ("1" if has_author else "0", nonfiling_indicator(title))
    if tag in ("100", "700"):
        return ("1", " ")  # personal name, surname-first
    if tag in ("110", "710"):
        return ("2", " ")  # corporate name in direct order
    if tag == "264":
        return (" ", "1")
    return (" ", " ")


def _datafield(tag: str, sub: str, value: str, has_author: bool, title: str = "") -> ET.Element:
    i1, i2 = _marc_indicators(tag, has_author, title)
    df = ET.Element("datafield", tag=tag, ind1=i1, ind2=i2)
    ET.SubElement(df, "subfield", code=sub).text = value
    return df


def _first_value(label: dict, mapping: dict[str, str], tag: str, sub: str) -> str:
    """The first mapped value destined for `tag$sub` — used for the 245 rules,
    which need the title text itself, not just its presence."""
    for field, spec in mapping.items():
        if _split_marc(spec)[0] == (tag, sub):
            values = _as_list(label.get(field))
            if values:
                return values[0]
    return ""


# MARC 21 leader, 24 characters. Positions that carry meaning for what paratext
# emits (the rest are fixed or filled in by the receiving system):
#   05    n  record status: new
#   06    a  type of record: language material
#   07    m  bibliographic level: monograph
#   09    a  character coding: Unicode
#   17    5  encoding level: partial (preliminary) — these are machine
#            extractions awaiting cataloguer review, not full-level records
#   18    i  descriptive cataloguing form: ISBD punctuation included, which is
#            what _punctuate_isbd puts in 245 and 264
#   19  ' '  multipart resource record level: not specified
# NB position 19 is a literal space. MARC documentation writes blank as "#", but
# the character on the wire is 0x20 — an actual "#" would be invalid data.
LEADER = "00000nam a22000005i 4500"


# Provenance note for AI-assisted records, written as MARC 588 (ind1=0, "source
# of description note") and Dublin Core `description`. Opt-in: nothing is added
# unless a note is configured or requested, because a record with no machine
# involvement should not carry the claim. `{date}` is substituted at export time.
DEFAULT_AI_NOTE = "Some metadata created with AI assistance on {date}"
AI_NOTE_TAG = "588"


def _append_text(sub: ET.Element | None, separator: str) -> None:
    """Append an ISBD `separator` to one subfield, if it has text.

    Idempotent on the punctuation itself: a model that transcribed the mark off
    the page would otherwise produce " : : ".
    """
    if sub is None or not sub.text:
        return
    text = sub.text.rstrip()
    mark = separator.strip()
    if text.endswith(mark):
        text = text[: -len(mark)].rstrip()
    sub.text = text + separator


def _append_isbd(df: ET.Element, code: str, separator: str) -> None:
    """Append an ISBD `separator` to subfield `code` of `df`."""
    _append_text(df.find(f"subfield[@code='{code}']"), separator)


def _punctuate_isbd(merged: dict[str, ET.Element]) -> None:
    """Add the ISBD separators that make concatenated subfields read as prose:
    ``Title : subtitle.`` and ``Place : Publisher, Date.``

    The separator belongs to the subfield it *follows*, so what gets punctuated
    depends on which neighbours are present — with no publisher, the comma before
    a date falls to the place instead. The date itself always closes the field
    with a full stop.
    """
    title = merged.get("245")
    if title is not None:
        if title.find("subfield[@code='b']") is not None:
            _append_isbd(title, "a", " : ")
        # The title statement closes with a full stop on whichever subfield ends
        # it — $b when there's a subtitle, otherwise $a. Subfields were sorted
        # into code order above, so the last element is the last subfield.
        if len(title):
            _append_text(title[-1], ".")

    imprint = merged.get("264")
    if imprint is None:
        return
    present = {c for c in "abc" if imprint.find(f"subfield[@code='{c}']") is not None}
    if {"a", "b"} <= present:
        _append_isbd(imprint, "a", " : ")
    if "c" in present and present & {"a", "b"}:
        _append_isbd(imprint, "b" if "b" in present else "a", ", ")
    if "c" in present:
        # The imprint statement closes with a full stop, whether or not anything
        # precedes the date. No trailing space — it terminates the field.
        _append_isbd(imprint, "c", ".")


def _record_to_marc(
    label: dict, mapping: dict[str, str], control_no: str | None, ai_note: str | None = None
) -> ET.Element:
    rec = ET.Element("record")
    ET.SubElement(rec, "leader").text = LEADER
    if control_no:
        ET.SubElement(rec, "controlfield", tag="001").text = control_no
    has_author = any(
        _split_marc(mapping[f])[0][0] in ("100", "110")
        for f in mapping
        if _as_list(label.get(f))
    )
    # Subfields destined for the same main tag are merged into one datafield (e.g.
    # 245$a + 245$b, or 264$a/$b/$c); each extra list value becomes its own repeatable
    # added-entry datafield (e.g. authors after the first → 700).
    title = _first_value(label, mapping, "245", "a")
    merged: dict[str, ET.Element] = {}
    extras: list[tuple[str, ET.Element]] = []
    for f, spec in mapping.items():
        values = _as_list(label.get(f))
        if not values:
            continue
        targets = _split_marc(spec)
        main_tag, main_sub = targets[0]
        added_tag, added_sub = targets[1] if len(targets) > 1 else targets[0]
        if main_tag not in merged:
            i1, i2 = _marc_indicators(main_tag, has_author, title)
            merged[main_tag] = ET.Element("datafield", tag=main_tag, ind1=i1, ind2=i2)
        ET.SubElement(merged[main_tag], "subfield", code=main_sub).text = values[0]
        for extra in values[1:]:
            extras.append(
                (added_tag, _datafield(added_tag, added_sub, extra, has_author, title))
            )
    for df in merged.values():  # tidy subfield order within a datafield (264 → $a$b$c)
        df[:] = sorted(df, key=lambda sf: sf.get("code", ""))
    _punctuate_isbd(merged)
    ordered = list(merged.items()) + extras
    if ai_note:
        # ind1=0 is "source of description note"; joins the sort so it lands in
        # tag order with everything else rather than being appended at the end.
        note = ET.Element("datafield", tag=AI_NOTE_TAG, ind1="0", ind2=" ")
        ET.SubElement(note, "subfield", code="a").text = ai_note
        ordered.append((AI_NOTE_TAG, note))
    for _tag, df in sorted(ordered, key=lambda x: x[0]):
        rec.append(df)
    return rec


def _record_to_dc(
    label: dict, mapping: dict[str, str], identifier: str | None, ai_note: str | None = None
) -> ET.Element:
    ns = "http://purl.org/dc/elements/1.1/"
    el = ET.Element("{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
    if identifier:
        ET.SubElement(el, f"{{{ns}}}identifier").text = identifier
    for f, element in mapping.items():
        for v in _as_list(label.get(f)):
            if f in ("isbn", "issn"):
                v = f"{f.upper()}:{v}"
            ET.SubElement(el, f"{{{ns}}}{element}").text = v
    if ai_note:
        ET.SubElement(el, f"{{{ns}}}description").text = ai_note
    return el


def _indent(elem: ET.Element) -> None:
    ET.indent(elem, space="  ")


def build_marc(records, mapping, ai_note: str | None = None) -> ET.ElementTree:
    root = ET.Element("collection", xmlns="http://www.loc.gov/MARC21/slim")
    for rec in records:
        root.append(_record_to_marc(rec.label, mapping, rec.document_id or rec.sid, ai_note))
    _indent(root)
    return ET.ElementTree(root)


def build_dc(records, mapping, ai_note: str | None = None) -> ET.ElementTree:
    ET.register_namespace("oai_dc", "http://www.openarchives.org/OAI/2.0/oai_dc/")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    root = ET.Element("records")
    for rec in records:
        root.append(_record_to_dc(rec.label, mapping, rec.document_id or rec.sid, ai_note))
    _indent(root)
    return ET.ElementTree(root)


def run(
    dataset_dir: Path,
    project: str,
    fmt: str,
    *,
    no_wizard: bool = False,
    ai_note: str | None = None,
) -> CatalogueSummary:
    """Select gold records and write a MARCXML / DC collection file. Fills unmapped
    fields via the wizard (interactive only) and persists the mapping."""
    mapping, unmapped = resolve_mapping(project, fmt)
    if unmapped and not no_wizard:
        chosen = run_wizard(project, fmt, unmapped)
        if chosen:
            persist_mapping(project, fmt, chosen)
            mapping.update({f: t for f, t in chosen.items() if t.strip()})
            unmapped = [f for f in unmapped if not chosen.get(f, "").strip()]
    if unmapped:
        print(f"warning: {len(unmapped)} field(s) unmapped and dropped from the "
              f"{fmt.upper()} records: {', '.join(unmapped)}")
    if not mapping:
        raise SystemExit(
            f"no fields mapped to {fmt.upper()} — nothing to export. Set "
            f"[project.{project}.export.{fmt}] in paratext.toml or run interactively."
        )

    note = resolve_ai_note(project, ai_note)
    sel = select_records(dataset_dir, project)  # gold only (good_enough + corrected)
    tree = (
        build_marc(sel.records, mapping, note)
        if fmt == "marc"
        else build_dc(sel.records, mapping, note)
    )

    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    ext = "marcxml" if fmt == "marc" else "dc.xml"
    dest = EXPORT_ROOT / f"{sel.name}.{ext}"
    tree.write(dest, encoding="utf-8", xml_declaration=True)
    return CatalogueSummary(
        format=fmt, records=len(sel.records), path=dest, mapped=mapping, skipped=unmapped
    )


# ── Scope-aware, in-memory export (used by the review UI's export modal) ─────
# The CLI `run` above writes gold only to a file. The GUI needs three record
# scopes and the bytes in hand (browser download), so these build from a dataset
# directory without touching disk.
_SCOPES = {
    "good_enough": "records verified good enough",
    "needs_tweaks": "good enough plus needs-tweaks",
    "everything": "every record in the round, reviewed or not",
}


@dataclass
class _PlainRecord:
    """The minimal shape build_marc/build_dc need (label + an id)."""

    label: dict
    document_id: str | None
    sid: str


def records_for_scope(
    dataset_dir: Path, project: str, scope: str, db_path: Path | None = None
) -> list:
    """Select records for one export scope. `good_enough`/`needs_tweaks` reuse
    `select_records`; `everything` includes unreviewed rows (model output), and
    a human-corrected answer still wins over the model where one exists.

    `db_path` points at the gold store (the review service keeps it outside the
    dataset dir); defaults to `<dataset_dir>/annotations.db`."""
    if scope not in _SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {sorted(_SCOPES)}")
    if scope != "everything":
        return select_records(dataset_dir, project, min_verdict=scope, db_path=db_path).records

    from .store import Store, default_db_path

    samples = json.loads((dataset_dir / "samples.json").read_text())
    schema_fields = list(get_project(project).schema.model_fields)
    store = Store(default_db_path(dataset_dir, db_path))
    name = dataset_dir.name
    out: list = []
    for s in samples:
        sid = str(s["id"])
        gold = (store.get_gold(name, sid) or {}).get("output") or {}
        model_output = s.get("model_output") or {}
        label = {f: gold.get(f, model_output.get(f)) for f in schema_fields}
        out.append(_PlainRecord(label=label, document_id=s.get("document_id"), sid=sid))
    return out


def export_bytes(
    dataset_dir: Path,
    project: str,
    fmt: str,
    scope: str,
    db_path: Path | None = None,
    mapping: dict | None = None,
    ai_note: str | None = None,
) -> tuple[bytes, int]:
    """Build a MARCXML / DC collection for one scope and return (xml_bytes, n).
    `mapping` (field -> target) overrides the inferred mapping when given — this
    is how the export modal applies the user's edits; an empty target skips a
    field. No wizard, no file written."""
    import io

    if mapping is None:
        mapping, _unmapped = resolve_mapping(project, fmt)
    else:
        mapping = {f: t for f, t in mapping.items() if (t or "").strip()}
    if not mapping:
        raise ValueError(f"no fields mapped to {fmt.upper()} for {project}")
    note = resolve_ai_note(project, ai_note)
    records = records_for_scope(dataset_dir, project, scope, db_path=db_path)
    tree = (
        build_marc(records, mapping, note)
        if fmt == "marc"
        else build_dc(records, mapping, note)
    )
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue(), len(records)
