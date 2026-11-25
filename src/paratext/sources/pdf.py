"""PDFs rendered to page images."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image

from ..projects import Sample
from .base import Source

logger = logging.getLogger(__name__)


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
    to page images. ``pages(num_pages) -> indices`` selects which pages."""

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

    return Source(
        iter_samples=_iter,
        materialise=_materialise,
        config={"kind": "pdf", "scale": scale, "pages": getattr(pages, "__name__", str(pages))},
    )
