"""Schema as data, for workshop mode.

A normal project's schema is a Pydantic class in `schema.py`, loaded from an
installed package. That cannot be edited in a running server, so workshop mode
carries the schema as a list of field dicts and builds the model per run.
"""

from __future__ import annotations

import keyword
import re

from pydantic import BaseModel, Field, create_model

# The types a workshop attendee can choose, and what they mean in the model.
TYPES: dict[str, type] = {
    "text": str,
    "number": int,
    "decimal": float,
    "yes/no": bool,
    "list": list[str],
}
DEFAULT_TYPE = "text"

# Inferred from the field name so nobody has to choose a type before they know
# what one is. Always shown, always overridable — a wrong guess is visible.
# Deliberately no bare "number": in a catalogue a call number, accession
# number or ISBN is text, and guessing integer there breaks the run.
_NUMBER = re.compile(r"(^|_)(count|year|pages|quantity|total)($|_)")
_DECIMAL = re.compile(r"(^|_)(price|cost|amount|rate|score|weight|height|width)($|_)")
_BOOLEAN = re.compile(r"^(is|has|was|had|can|should)_")
_LIST = re.compile(
    r"(^|_)(authors|subjects|names|topics|keywords|tracings|entries|contents"
    r"|illustrations|languages|places|editors|contributors)($|_)"
)


def infer_type(name: str) -> str:
    """Guess a field's type from its name. Falls back to text, which is right
    far more often than not for catalogue metadata."""
    n = (name or "").strip().lower()
    if _BOOLEAN.match(n):
        return "yes/no"
    if _LIST.search(n):
        return "list"
    if _DECIMAL.search(n):
        return "decimal"
    if _NUMBER.search(n):
        return "number"
    return DEFAULT_TYPE


def normalise_name(raw: str) -> str:
    """A field name the model and Python can both take: snake_case, no leading
    digit, not a keyword."""
    n = re.sub(r"[^0-9a-zA-Z]+", "_", (raw or "").strip().lower()).strip("_")
    n = re.sub(r"_+", "_", n)
    if not n:
        return ""
    if n[0].isdigit():
        n = f"f_{n}"
    if keyword.iskeyword(n):
        n = f"{n}_"
    return n


def normalise_fields(fields: list[dict]) -> list[dict]:
    """Clean a submitted field list: usable names, known types, no duplicates,
    order preserved. Unnamed rows are dropped rather than rejected — the editor
    always has a blank row at the bottom."""
    out: list[dict] = []
    seen: set[str] = set()
    for f in fields or []:
        name = normalise_name(f.get("name", ""))
        if not name or name in seen:
            continue
        seen.add(name)
        ftype = f.get("type") or infer_type(name)
        if ftype not in TYPES:
            ftype = infer_type(name)
        out.append({
            "name": name,
            "type": ftype,
            "description": (f.get("description") or "").strip(),
        })
    return out


def build_schema(fields: list[dict], name: str = "WorkshopRecord") -> type[BaseModel]:
    """Build a Pydantic model from a normalised field list.

    Every field is optional: a card that doesn't carry one should come back null,
    not fail validation mid-demo.
    """
    fields = normalise_fields(fields)
    if not fields:
        raise ValueError("a schema needs at least one field")
    spec: dict = {}
    for f in fields:
        py = TYPES[f["type"]]
        spec[f["name"]] = (
            py | None,
            Field(None, description=f["description"] or None),
        )
    return create_model(name, **spec)
