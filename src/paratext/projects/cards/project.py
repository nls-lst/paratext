"""Generic index-cards starter project.

A worked, collection-agnostic example: classify and transcribe scanned
catalogue cards. It wires the reusable `paratext.cards` toolkit (the
deterministic verso pre-filter + the optional RetinaNet crop) to a minimal
schema and a neutral prompt, so a card library can run the pipeline out of the
box and then fork the prompt/schema for its own cataloguing rules.

Run it with ``paratext run -p cards`` after pointing ``[project.cards]`` at a
flat directory of card images. For card cropping, ``pip install paratext[cards]``
(downloads the detector from the Hugging Face Hub on first use).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Literal, Optional

from PIL import Image
from pydantic import BaseModel, Field

from ...cards import is_verso, load_card_detector
from ...packaging import save_image
from .. import Curation, Panel, Project, Sample, View, load_prompt

SCHEMA_VERSION = "v1"


# ── Schema ─────────────────────────────────────────────────────────────────
class CardExtraction(BaseModel):
    image_type: Literal["card", "verso", "blank", "other"] = Field(
        ..., description="What the image shows; only `card` is reviewed downstream"
    )
    heading: Optional[str] = Field(None, description="Main heading / filing term, verbatim")
    text: Optional[str] = Field(None, description="Faithful line-by-line transcription")


PROMPT = load_prompt(__file__)  # see prompt.md beside this module


# ── Sample iteration ──────────────────────────────────────────────────────
def _iter_samples(source: Path, limit: int | None) -> Iterator[Sample]:
    if not source.is_dir():
        raise FileNotFoundError(f"images dir not found: {source}")

    images = sorted(
        p for p in source.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if limit is not None:
        images = images[:limit]

    detector = load_card_detector()  # None → uniform crop (no `[cards]` extra / weights)
    for img_path in images:
        img = Image.open(img_path).convert("RGB")
        # Deterministic verso pre-filter: blank backs skip the detector and VLM.
        if is_verso(img):
            yield Sample(
                id=img_path.stem,
                images=[],
                metadata={
                    "image_path": str(img_path.resolve()),
                    "detected": False,
                    "preclassified": {"image_type": "verso"},
                },
            )
            continue
        bbox = detector.detect(img) if detector is not None else None
        if bbox is not None:
            img = detector.crop(img, bbox=bbox, padding_pct=0.10)
        yield Sample(
            id=img_path.stem,
            images=[img],
            metadata={"image_path": str(img_path.resolve()), "detected": bbox is not None},
        )


# ── Packaging hooks ────────────────────────────────────────────────────────
def _curate(rec: dict) -> Curation:
    image_type = (rec.get("extraction") or {}).get("image_type")
    if image_type and image_type != "card":
        return Curation("drop", image_type)
    return Curation("keep")


def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
    src = (rec.get("metadata") or {}).get("image_path")
    if src and Path(src).exists():
        rel = f"images/{rec['id']}/card.jpg"
        save_image(Path(src), out / rel, max_size)
        return [rel]
    return []


def _build_record(rec: dict, images_rel: list[str]) -> dict:
    return {
        "id": rec["id"],
        "document_id": rec["id"],
        "image_path": (rec.get("metadata") or {}).get("image_path"),
        "model_output": rec.get("extraction") or {},
        "images": images_rel,
    }


VIEW = View(
    layout="split",
    ground_truth=False,
    title="Index card",
    id_label="Image ID",
    panels=[Panel(source="model_output", title="Model output", fields=["heading", "text"])],
)

PROJECT = Project(
    name="cards",
    schema_version=SCHEMA_VERSION,
    prompt=PROMPT,
    schema=CardExtraction,
    iter_samples=_iter_samples,
    disable_thinking=True,
    view=VIEW,
    curate=_curate,
    materialise_images=_materialise,
    build_record=_build_record,
    image_max_size=2048,
    image_quality=90,
)
