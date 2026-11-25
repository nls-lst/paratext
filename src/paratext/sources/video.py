"""Videos, one Sample per clip, each sampled to a handful of frames."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from PIL import Image

from ..projects import Sample
from .base import Source
from .manifest import read_manifest

if TYPE_CHECKING:
    from ..video import FrameTimes

logger = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".ts")


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
    from ..video import evenly_spaced, grab_frame, probe_duration, stamp

    pick = frames or evenly_spaced(8)

    def _frames(src: str, times: list[float], start: float) -> list[Image.Image]:
        imgs = [grab_frame(src, t) for t in times]
        if not timestamps:
            return imgs
        return [stamp(im, t - start) for im, t in zip(imgs, times)]

    def _clips(source: Path) -> list[dict]:
        if source.is_file():
            return read_manifest(source)
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
