"""A flat directory of images, one Sample per file."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from PIL import Image

from ..packaging import default_materialise
from ..projects import Sample
from .base import Source

IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def image_source(
    *,
    verso_filter: bool = False,
    crop: bool = False,
    suppress_show_through: bool = False,
    exts: tuple[str, ...] = IMAGE_EXTS,
) -> Source:
    """A flat directory of images, one Sample per file.

    ``verso_filter`` drops blank card backs before the model (pre-classifies them
    as ``image_type="verso"`` — the project's ``curate`` decides to drop them).
    ``crop`` crops each scan to the detected card region (needs the
    ``[detector]`` extra; falls back to a content-aware crop). ``suppress_show_through`` flattens
    faint ink bleeding through from stacked cards, so the model is less likely
    to transcribe it as a real entry. All three come from ``paratext.cards``.

    All three default to off: they are card-specific, and the bundled detector
    and verso thresholds are tuned to one collection's scans.
    """
    notices: list[str] = []

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        if not source.is_dir():
            raise FileNotFoundError(f"images dir not found: {source}")
        images = sorted(p for p in source.iterdir() if p.suffix.lower() in exts)
        if limit is not None:
            images = images[:limit]

        detector = None
        if crop:
            from ..cards import load_card_detector

            detector = load_card_detector()
            if detector is None:
                # Still crop — but content-aware, not a blind margin — and the
                # failure must reach the run summary, not just the log.
                notices.append(
                    "crop: card detector unavailable — fell back to a content-aware "
                    "crop (card located against the background). Install the "
                    "`detector` extra (paratext[detector]), then point the [detector] "
                    "config table or PARATEXT_CARD_DETECTOR at weights trained on "
                    "your own cards."
                )
        check_verso = None
        if verso_filter:
            from ..cards import is_verso

            check_verso = is_verso

        for path in images:
            img = Image.open(path).convert("RGB")
            meta: dict = {"image_path": str(path.resolve())}
            if check_verso is not None and check_verso(img):
                meta["preclassified"] = {"image_type": "verso"}
                yield Sample(id=path.stem, images=[], metadata=meta)
                continue
            if crop:
                if detector is not None:
                    bbox = detector.detect(img)
                    if bbox is not None:
                        img = detector.crop(img, bbox=bbox, padding_pct=0.10)
                    meta["detected"] = bbox is not None
                else:
                    from ..cards import crop_content

                    # Leave the scan alone when the card can't be located: an
                    # over-crop deletes text and is scored as a misreading, an
                    # under-crop only gives the model more desk to look at.
                    cropped = crop_content(img)
                    img = cropped if cropped is not None else img
                    meta["detected"] = False
                    meta["crop"] = "content" if cropped is not None else "none"
            if suppress_show_through:
                # After cropping, so levels are measured on the card not the desk.
                from ..cards import suppress_show_through as _suppress

                img = _suppress(img)
                meta["show_through_suppressed"] = True
            yield Sample(id=path.stem, images=[img], metadata=meta)

    return Source(
        iter_samples=_iter,
        # One image per record from metadata.image_path — exactly the packager's
        # generic default, so reuse it rather than keeping a second copy.
        materialise=default_materialise,
        notices=notices,
        config={
            "kind": "images",
            "verso_filter": verso_filter,
            "crop": crop,
            "suppress_show_through": suppress_show_through,
            "exts": list(exts),
        },
    )
