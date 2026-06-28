"""Input adapters: turn a source directory into Samples (for extraction) and
review images (for packaging), so a project rarely writes iteration code.

A `Source` bundles the two halves that must agree on a metadata shape:

    iter_samples(source, limit) -> Iterator[Sample]      # extraction time
    materialise(record, out, max_size) -> [rel_path]     # packaging time

Pass one to ``Project(source=…)`` and the framework wires both. Two are built
in: ``image_source`` (a flat directory of images, with optional verso filter and
card crop) and ``pdf_source`` (PDFs rendered to page images).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image

from .packaging import save_image
from .projects import Sample

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png")


@dataclass
class Source:
    """An extraction iterator paired with its packaging image-materialiser."""

    iter_samples: Callable[[Path, int | None], Iterator[Sample]]
    materialise: Callable[[dict, Path, int], list[str]]


# ── Images ──────────────────────────────────────────────────────────────────
def image_source(
    *,
    verso_filter: bool = False,
    crop: bool = False,
    exts: tuple[str, ...] = IMAGE_EXTS,
) -> Source:
    """A flat directory of images, one Sample per file.

    ``verso_filter`` drops blank card backs before the VLM (pre-classifies them
    as ``image_type="verso"`` — the project's ``curate`` decides to drop them).
    ``crop`` crops each scan to the detected card region (needs the ``[cards]``
    extra; falls back to a uniform crop). Both come from ``paratext.cards``.
    """

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        if not source.is_dir():
            raise FileNotFoundError(f"images dir not found: {source}")
        images = sorted(p for p in source.iterdir() if p.suffix.lower() in exts)
        if limit is not None:
            images = images[:limit]

        detector = None
        if crop:
            from .cards import load_card_detector

            detector = load_card_detector()  # None → no crop
        check_verso = None
        if verso_filter:
            from .cards import is_verso

            check_verso = is_verso

        for path in images:
            img = Image.open(path).convert("RGB")
            meta: dict = {"image_path": str(path.resolve())}
            if check_verso is not None and check_verso(img):
                meta["preclassified"] = {"image_type": "verso"}
                yield Sample(id=path.stem, images=[], metadata=meta)
                continue
            if detector is not None:
                bbox = detector.detect(img)
                if bbox is not None:
                    img = detector.crop(img, bbox=bbox, padding_pct=0.10)
                meta["detected"] = bbox is not None
            yield Sample(id=path.stem, images=[img], metadata=meta)

    def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
        src = (rec.get("metadata") or {}).get("image_path")
        if src and Path(src).exists():
            rel = f"images/{rec['id']}/image.jpg"
            save_image(Path(src), out / rel, max_size)
            return [rel]
        return []

    return Source(_iter, _materialise)


# ── PDFs ────────────────────────────────────────────────────────────────────
def first_pages_plus_last(num_pages: int) -> list[int]:
    """First three pages plus the last — title, copyright, and back matter."""
    indices = list(range(min(3, num_pages)))
    if num_pages > 3:
        indices.append(num_pages - 1)
    return indices


def pdf_source(
    *,
    pages: Callable[[int], list[int]] = first_pages_plus_last,
    scale: float = 2.0,
) -> Source:
    """PDFs under the source tree (recursive; id = filename stem), each rendered
    to page images. ``pages(num_pages) -> indices`` selects which pages. Needs
    the ``[pdf]`` extra (pypdfium2)."""

    def _render(pdf_path: Path, indices: list[int]) -> list[Image.Image]:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(pdf_path)
        try:
            return [pdf[i].render(scale=scale).to_pil().convert("RGB") for i in indices]
        finally:
            pdf.close()

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        import pypdfium2 as pdfium

        if not source.is_dir():
            raise FileNotFoundError(f"PDF source dir not found: {source}")
        seen: dict[str, Path] = {}
        for p in sorted(source.rglob("*.pdf")):
            seen.setdefault(p.stem, p)
        items = sorted(seen.items())
        if limit is not None:
            items = items[:limit]

        for doc_id, pdf_path in items:
            try:
                pdf = pdfium.PdfDocument(pdf_path)
                try:
                    n = len(pdf)
                finally:
                    pdf.close()
                indices = pages(n)
                images = _render(pdf_path, indices)
            except Exception as e:
                logger.warning("render failed for %s: %s", doc_id, e)
                continue
            yield Sample(
                id=doc_id,
                images=images,
                metadata={
                    "pdf_path": str(pdf_path.resolve()),
                    "pdf_relpath": str(pdf_path.relative_to(source)),
                    "num_pages": n,
                    "pages_rendered": indices,
                },
            )

    def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
        meta = rec.get("metadata") or {}
        pdf_path = meta.get("pdf_path")
        pages_rendered = meta.get("pages_rendered") or []
        if not (pdf_path and Path(pdf_path).exists()):
            logger.warning("PDF not found for %s: %s", rec["id"], pdf_path)
            return []
        rels: list[str] = []
        images = _render(Path(pdf_path), pages_rendered)
        for k, img in enumerate(images):
            rel = f"images/{rec['id']}/page_{k}.jpg"
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            img.save(dest, format="JPEG", quality=85)
            rels.append(rel)
        return rels

    return Source(_iter, _materialise)
