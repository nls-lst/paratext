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


def _marc_indicators(tag: str, has_author: bool) -> tuple[str, str]:
    if tag == "245":
        return ("1" if has_author else "0", "0")
    if tag in ("100", "110", "700", "710"):
        return ("1", " ")
    if tag == "264":
        return (" ", "1")
    return (" ", " ")


def _datafield(tag: str, sub: str, value: str, has_author: bool) -> ET.Element:
    i1, i2 = _marc_indicators(tag, has_author)
    df = ET.Element("datafield", tag=tag, ind1=i1, ind2=i2)
    ET.SubElement(df, "subfield", code=sub).text = value
    return df


def _record_to_marc(label: dict, mapping: dict[str, str], control_no: str | None) -> ET.Element:
    rec = ET.Element("record")
    ET.SubElement(rec, "leader").text = "00000nam a2200000 a 4500"
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
            i1, i2 = _marc_indicators(main_tag, has_author)
            merged[main_tag] = ET.Element("datafield", tag=main_tag, ind1=i1, ind2=i2)
        ET.SubElement(merged[main_tag], "subfield", code=main_sub).text = values[0]
        for extra in values[1:]:
            extras.append((added_tag, _datafield(added_tag, added_sub, extra, has_author)))
    for df in merged.values():  # tidy subfield order within a datafield (264 → $a$b$c)
        df[:] = sorted(df, key=lambda sf: sf.get("code", ""))
    ordered = list(merged.items()) + extras
    for _tag, df in sorted(ordered, key=lambda x: x[0]):
        rec.append(df)
    return rec


def _record_to_dc(label: dict, mapping: dict[str, str], identifier: str | None) -> ET.Element:
    ns = "http://purl.org/dc/elements/1.1/"
    el = ET.Element("{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
    if identifier:
        ET.SubElement(el, f"{{{ns}}}identifier").text = identifier
    for f, element in mapping.items():
        for v in _as_list(label.get(f)):
            if f in ("isbn", "issn"):
                v = f"{f.upper()}:{v}"
            ET.SubElement(el, f"{{{ns}}}{element}").text = v
    return el


def _indent(elem: ET.Element) -> None:
    ET.indent(elem, space="  ")


def build_marc(records, mapping) -> ET.ElementTree:
    root = ET.Element("collection", xmlns="http://www.loc.gov/MARC21/slim")
    for rec in records:
        root.append(_record_to_marc(rec.label, mapping, rec.document_id or rec.sid))
    _indent(root)
    return ET.ElementTree(root)


def build_dc(records, mapping) -> ET.ElementTree:
    ET.register_namespace("oai_dc", "http://www.openarchives.org/OAI/2.0/oai_dc/")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    root = ET.Element("records")
    for rec in records:
        root.append(_record_to_dc(rec.label, mapping, rec.document_id or rec.sid))
    _indent(root)
    return ET.ElementTree(root)


def run(dataset_dir: Path, project: str, fmt: str, *, no_wizard: bool = False) -> CatalogueSummary:
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

    sel = select_records(dataset_dir, project)  # gold only (good_enough + corrected)
    tree = build_marc(sel.records, mapping) if fmt == "marc" else build_dc(sel.records, mapping)

    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    ext = "marcxml" if fmt == "marc" else "dc.xml"
    dest = EXPORT_ROOT / f"{sel.name}.{ext}"
    tree.write(dest, encoding="utf-8", xml_declaration=True)
    return CatalogueSummary(
        format=fmt, records=len(sel.records), path=dest, mapped=mapping, skipped=unmapped
    )
