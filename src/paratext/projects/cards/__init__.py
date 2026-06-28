"""Generic index-cards starter project.

A worked, collection-agnostic example: classify and transcribe scanned
catalogue cards. The schema is in ``schema.py``, the prompt in ``prompt.md``;
this file just wires them to an image source (verso filter + optional crop) and
keeps only the cards.

Run with ``paratext run -p cards`` after pointing ``[project.cards]`` at a flat
directory of card images. For cropping, ``pip install paratext[cards]``.
"""

from __future__ import annotations

from paratext.projects import Curation, Panel, Project, View, load_prompt
from paratext.sources import image_source

from .schema import CardExtraction

__all__ = ["PROJECT"]


def _curate(rec: dict) -> Curation:
    """Keep cards; drop versos/blanks/other (and verso pre-filter hits)."""
    image_type = (rec.get("extraction") or {}).get("image_type")
    if image_type and image_type != "card":
        return Curation("drop", image_type)
    return Curation("keep")


PROJECT = Project(
    name="cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=CardExtraction,
    source=image_source(verso_filter=True, crop=True),
    curate=_curate,
    # Show just the transcription fields; image_type is internal triage.
    view=View(
        layout="split",
        title="Index card",
        id_label="Image ID",
        panels=[Panel(source="model_output", title="Model output", fields=["heading", "text"])],
    ),
    image_max_size=2048,
    image_quality=90,
)
