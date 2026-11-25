"""Videos, one Sample per clip, each sampled to a handful of frames."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from PIL import Image

from ..projects import Audio, Sample
from .base import Source
from .manifest import list_clips

if TYPE_CHECKING:
    from ..transcripts import Transcriber
    from ..video import FrameTimes

logger = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".ts")


def video_source(
    *,
    frames: "FrameTimes | None" = None,
    timestamps: bool = True,
    exts: tuple[str, ...] = VIDEO_EXTS,
    soundtrack: bool = False,
    sample_rate: int = 16000,
    transcribe: "Transcriber | None" = None,
) -> Source:
    """Videos, one Sample per clip, each sampled to a handful of frames.

    The source is a directory of video files (recursive; id = filename stem) or
    a manifest, ``.jsonl`` or ``.csv``, with one clip per row: ``id`` and ``src``
    (a path relative to the manifest, or a URL, HLS included), optionally
    ``start`` and ``end`` in seconds, ``poster`` and ``label``. A manifest lets
    one long tape yield several clips.

    ``frames(start, end) -> times`` picks the frames; the default is eight,
    evenly spaced. ``timestamps`` prints each frame's time below it, counted
    from the start of the clip, so the model can place what it sees.
    ``soundtrack`` also sends the clip's sound, as mono WAV at ``sample_rate`` Hz
    after the frames, so the model hears what it sees; it needs a model that takes
    audio. ``transcribe`` (see ``paratext.transcripts``) turns the sound into timed
    text, which the model reads after the frames and the reviewer sees as a track
    on the timeline; it works with or without ``soundtrack``. With either, a clip
    without sound fails rather than going without it, and the run summary says
    which. Other manifest columns reach the transcriber under ``clip["extra"]``.
    Needs ffmpeg on PATH.
    """
    from ..ffmpeg import decode_audio
    from ..transcripts import transcribe_clip
    from ..video import evenly_spaced, grab_frame, probe_duration, stamp

    pick = frames or evenly_spaced(8)

    def _frames(src: str, times: list[float], start: float) -> list[Image.Image]:
        imgs = [grab_frame(src, t) for t in times]
        if not timestamps:
            return imgs
        return [stamp(im, t - start) for im, t in zip(imgs, times)]

    notices: list[str] = []

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        clips = list_clips(source, exts, "video")
        if limit is not None:
            clips = clips[:limit]
        failed = []
        for clip in clips:
            try:
                start = clip.get("start", 0.0)
                end = clip.get("end") or probe_duration(clip["src"])
                times = pick(start, end)
                images = _frames(clip["src"], times, start)
                wav = decode_audio(clip["src"], start, end, sample_rate) \
                    if soundtrack or transcribe else None
                tx = transcribe_clip(transcribe, wav, clip, start) if transcribe else None
            except Exception as e:
                logger.warning("sampling failed for %s: %s", clip["id"], e)
                failed.append(clip["id"])
                continue
            media = {"src": clip["src"], "start": start, "end": end}
            media.update({k: clip[k] for k in ("poster", "label") if k in clip})
            meta: dict = {"media": media, "frame_times": times}
            if tx:
                media["tracks"] = [tx["track"]]
                meta["transcript"] = tx["segments"]
            yield Sample(
                id=clip["id"],
                images=images,
                audio=[Audio(wav)] if soundtrack else [],
                text=[tx["text"]] if tx else [],
                metadata=meta,
            )
        if failed:
            notices.append(
                f"video: {len(failed)} clip(s) could not be sampled and were skipped "
                f"({', '.join(failed[:5])}{', …' if len(failed) > 5 else ''}); the log has "
                f"the reason for each. Fix them, then re-run to fill them in."
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
        notices=notices,
        config={
            "kind": "video",
            "frames": getattr(pick, "__name__", str(pick)),
            "timestamps": timestamps,
            "exts": list(exts),
            "soundtrack": soundtrack,
            "transcribe": getattr(transcribe, "__name__", repr(transcribe)) if transcribe else None,
            **({"sample_rate": sample_rate} if soundtrack else {}),
        },
    )
