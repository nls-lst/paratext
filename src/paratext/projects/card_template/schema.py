"""Output schema for the generic index-cards project. Edit these fields (and
keep prompt.md in step) to fit your collection."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CardExtraction(BaseModel):
    image_type: Literal["card", "verso", "blank", "other"] = Field(
        ..., description="What the image shows; only `card` is reviewed downstream"
    )
    heading: Optional[str] = Field(None, description="Main heading / filing term, verbatim")
    text: Optional[str] = Field(None, description="Faithful line-by-line transcription")
