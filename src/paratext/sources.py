"""Input adapters: turn a source directory into Samples (for extraction) and
review images (for packaging), so a project rarely writes iteration code.

A `Source` bundles the two halves that must agree on a metadata shape:

    iter_samples(source, limit) -> Iterator[Sample]      # extraction time
    materialise(record, out, max_size) -> [rel_path]     # packaging time

Pass one to ``Project(source=…)`` and the framework wires both. Two are built
in: ``image_source`` (a flat directory of images, with optional verso filter and
card crop), ``pdf_source`` (PDFs rendered to page images), ``hf_dataset_source``
and ``video_source`` (videos sampled to frames).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator

from PIL import Image

from .packaging import default_materialise
from .projects import Sample

if TYPE_CHECKING:
    from .video import FrameTimes

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png")


@dataclass
class Source:
    """An extraction iterator paired with its packaging image-materialiser.

    ``notices`` collects human-readable degradations noticed during iteration
    (e.g. a requested crop that fell back). `extract` drains it into the run
    summary so a silently-degraded run can't look like a clean one.
    """

    iter_samples: Callable[[Path, int | None], Iterator[Sample]]
    materialise: Callable[[dict, Path, int], list[str]]
    notices: list[str] = field(default_factory=list)
    # What this adapter was constructed with, for `paratext inspect` — the
    # preprocessing a project applies is otherwise invisible without reading its
    # source. Descriptive only; nothing reads it back to make decisions.
    config: dict = field(default_factory=dict)


# ── Images ──────────────────────────────────────────────────────────────────
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
            from .cards import load_card_detector

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
            from .cards import is_verso

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
                    from .cards import crop_content

                    # Leave the scan alone when the card can't be located: an
                    # over-crop deletes text and is scored as a misreading, an
                    # under-crop only gives the model more desk to look at.
                    cropped = crop_content(img)
                    img = cropped if cropped is not None else img
                    meta["detected"] = False
                    meta["crop"] = "content" if cropped is not None else "none"
            if suppress_show_through:
                # After cropping, so levels are measured on the card not the desk.
                from .cards import suppress_show_through as _suppress

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


# ── Hugging Face datasets ───────────────────────────────────────────────────
HF_CACHE_ENV = "PARATEXT_HF_CACHE"


def hf_dataset_source(
    *,
    repo: str | None = None,
    path_prefix: str = "",
    exts: tuple[str, ...] = IMAGE_EXTS,
    token: str | None = None,
    revision: str | None = None,
    cache_dir: Path | None = None,
) -> Source:
    """An imagefolder-style dataset on the Hugging Face Hub, one Sample per image.

    ``repo`` is the dataset id (``owner/name``). Leave it unset to take the id
    from the run's source argument instead, so ``--source owner/name`` works
    without rebuilding the project.

    Files are listed with ``huggingface_hub`` and pulled one at a time, which
    costs no new dependency and is the exact shape ``paratext export`` writes —
    a round trip, so a published eval set can be re-run. It does **not** read
    parquet-backed datasets; those need the ``datasets`` library and a column
    map, and are a separate adapter rather than a flag on this one.

    ``token`` reaches private datasets, and is the caller's to supply — nothing
    here reads an ambient credential or writes one down.
    """
    notices: list[str] = []
    root = cache_dir or Path(os.environ.get(HF_CACHE_ENV, "")) or None

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        from huggingface_hub import HfApi, hf_hub_download
        from huggingface_hub.errors import HfHubHTTPError

        repo_id = repo or str(source)
        if repo_id.count("/") != 1 or not all(repo_id.split("/")):
            raise ValueError(
                f"not a dataset id: {repo_id!r} — expected owner/name, "
                f"e.g. NationalLibraryOfScotland/index-cards-eval"
            )
        api = HfApi(token=token)
        try:
            names = api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
        except HfHubHTTPError as e:
            raise FileNotFoundError(
                f"can't read dataset {repo_id!r}: {e}. If it is private, supply a token."
            ) from e

        wanted = sorted(
            n for n in names
            if n.lower().endswith(exts) and n.startswith(path_prefix)
        )
        if not wanted:
            where = f" under {path_prefix!r}" if path_prefix else ""
            raise FileNotFoundError(
                f"no images{where} in {repo_id!r} (looked for {', '.join(exts)}). "
                f"This adapter reads imagefolder-style datasets; a parquet-backed "
                f"dataset needs a different one."
            )
        # An imagefolder dataset keeps everything under one directory, and
        # carrying that into every id just makes them longer. Drop it only when
        # it is shared by all of them, so a nested layout keeps its structure.
        dirs = {n.rsplit("/", 1)[0] if "/" in n else "" for n in wanted}
        shared = f"{dirs.pop()}/" if len(dirs) == 1 and dirs != {""} else ""

        if limit is not None:
            wanted = wanted[:limit]

        for name in wanted:
            local = hf_hub_download(
                repo_id, name, repo_type="dataset", revision=revision,
                token=token, cache_dir=str(root) if root else None,
            )
            img = Image.open(local).convert("RGB")
            # The id has to survive a nested layout without colliding, so keep
            # what's left of the path and drop only the extension.
            stem = name[len(shared):]
            sample_id = stem[: -len(Path(stem).suffix)].replace("/", "__")
            yield Sample(
                id=sample_id,
                images=[img],
                metadata={"image_path": str(Path(local).resolve()),
                          "hf_repo": repo_id, "hf_file": name},
            )

    return Source(
        iter_samples=_iter,
        materialise=default_materialise,
        notices=notices,
        config={
            "kind": "hf-dataset",
            "repo": repo,
            "path_prefix": path_prefix,
            "revision": revision,
            "exts": list(exts),
            "token": bool(token),   # never the value
        },
    )


# ── Video ───────────────────────────────────────────────────────────────────
VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".ts")


def _is_url(src: str) -> bool:
    return src.startswith(("http://", "https://"))


def _read_manifest(path: Path) -> list[dict]:
    import csv
    import json

    if path.suffix.lower() == ".csv":
        with path.open(newline="") as f:
            rows = [{k: v for k, v in r.items() if v not in (None, "")} for r in csv.DictReader(f)]
    else:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    clips = []
    for i, r in enumerate(rows):
        if not r.get("id") or not r.get("src"):
            raise ValueError(f"{path.name} row {i + 1}: needs an id and a src")
        src = str(r["src"])
        if not _is_url(src):
            src = str((path.parent / src).resolve())
        clip = {"id": str(r["id"]), "src": src}
        for k in ("start", "end"):
            if k in r:
                clip[k] = float(r[k])
        for k in ("poster", "label"):
            if k in r:
                clip[k] = r[k]
        clips.append(clip)
    return clips


def video_source(
    *,
    frames: "FrameTimes | None" = None,
    timestamps: bool = True,
    exts: tuple[str, ...] = VIDEO_EXTS,
) -> Source:
    """Videos, one Sample per clip, each sampled to a handful of frames.

    The source is a directory of video files (recursive; id = filename stem) or
    a manifest, ``.jsonl`` or ``.csv``, with one clip per row: ``id`` and ``src``
    (a path relative to the manifest, or a URL, HLS included), optionally
    ``start`` and ``end`` in seconds, ``poster`` and ``label``. A manifest lets
    one long tape yield several clips.

    ``frames(start, end) -> times`` picks the frames; the default is eight,
    evenly spaced. ``timestamps`` prints each frame's time below it, counted
    from the start of the clip, so the model can place what it sees. Needs ffmpeg on PATH.
    """
    from .video import evenly_spaced, grab_frame, probe_duration, stamp

    pick = frames or evenly_spaced(8)

    def _frames(src: str, times: list[float], start: float) -> list[Image.Image]:
        imgs = [grab_frame(src, t) for t in times]
        if not timestamps:
            return imgs
        return [stamp(im, t - start) for im, t in zip(imgs, times)]

    def _clips(source: Path) -> list[dict]:
        if source.is_file():
            return _read_manifest(source)
        if not source.is_dir():
            raise FileNotFoundError(f"video source not found: {source}")
        seen: dict[str, Path] = {}
        for p in sorted(source.rglob("*")):
            if p.suffix.lower() in exts:
                seen.setdefault(p.stem, p)
        return [{"id": k, "src": str(p.resolve())} for k, p in sorted(seen.items())]

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        clips = _clips(source)
        if limit is not None:
            clips = clips[:limit]
        for clip in clips:
            try:
                start = clip.get("start", 0.0)
                end = clip.get("end") or probe_duration(clip["src"])
                times = pick(start, end)
                images = _frames(clip["src"], times, start)
            except Exception as e:
                logger.warning("frame sampling failed for %s: %s", clip["id"], e)
                continue
            media = {"src": clip["src"], "start": start, "end": end}
            media.update({k: clip[k] for k in ("poster", "label") if k in clip})
            yield Sample(
                id=clip["id"],
                images=images,
                metadata={"media": media, "frame_times": times},
            )

    def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
        meta = rec.get("metadata") or {}
        media, times = meta.get("media") or {}, meta.get("frame_times") or []
        if not media.get("src"):
            return []
        try:
            images = _frames(media["src"], times, media.get("start", 0.0))
        except Exception as e:
            logger.warning("frames unavailable for %s: %s", rec["id"], e)
            return []
        rels: list[str] = []
        for k, img in enumerate(images):
            rel = f"images/{rec['id']}/frame_{k}.jpg"
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            img.save(dest, format="JPEG", quality=85)
            rels.append(rel)
        return rels

    return Source(
        iter_samples=_iter,
        materialise=_materialise,
        config={
            "kind": "video",
            "frames": getattr(pick, "__name__", str(pick)),
            "timestamps": timestamps,
            "exts": list(exts),
        },
    )
