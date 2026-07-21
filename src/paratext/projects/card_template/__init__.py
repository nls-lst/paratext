"""Index-card template project — a worked example to copy and edit.

A collection-agnostic starting point: classify and transcribe scanned catalogue
cards. The schema is in ``schema.py``, the prompt in ``prompt.md``; this file
wires them to an image source and keeps only the cards.

Run with ``paratext run -p card-template`` after pointing
``[project.card-template]`` at a flat directory of card images.

The card-specific preprocessing (``crop``, ``verso_filter``) is left **off**
here. Both are tuned to one collection's scans — the bundled detector is
trained on National Library of Scotland cards — so they need calibrating
against your own material before they help. See the Scanned cards section of
the README.
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
    name="card-template",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=CardExtraction,
    source=image_source(),
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
