"""Sound recordings, one Sample per clip, sent to the model as audio."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from ..projects import Audio, Sample
from .base import Source
from .manifest import read_manifest

logger = logging.getLogger(__name__)

AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff")


def audio_source(
    *,
    sample_rate: int = 16000,
    exts: tuple[str, ...] = AUDIO_EXTS,
) -> Source:
    """Sound recordings, one Sample per clip, each decoded to mono WAV at
    ``sample_rate`` Hz and sent to the model as an ``input_audio`` part.

    The source is a directory of audio files (recursive; id = filename stem) or a
    manifest, ``.jsonl`` or ``.csv``, as for ``video_source``: ``id`` and ``src``,
    optionally ``start`` and ``end`` in seconds and ``label``. A manifest lets one
    long recording yield several clips, which is also how to keep each request to
    a size the model's server accepts. The review UI plays the clip. Needs ffmpeg
    on PATH.
    """
    from ..ffmpeg import decode_audio, probe_duration

    notices: list[str] = []

    def _clips(source: Path) -> list[dict]:
        if source.is_file():
            return read_manifest(source)
        if not source.is_dir():
            raise FileNotFoundError(f"audio source not found: {source}")
        seen: dict[str, Path] = {}
        for p in sorted(source.rglob("*")):
            if p.suffix.lower() in exts:
                seen.setdefault(p.stem, p)
        return [{"id": k, "src": str(p.resolve())} for k, p in sorted(seen.items())]

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        clips = _clips(source)
        if limit is not None:
            clips = clips[:limit]
        failed = []
        for clip in clips:
            try:
                start = clip.get("start", 0.0)
                end = clip.get("end") or probe_duration(clip["src"])
                wav = decode_audio(clip["src"], start, end, sample_rate)
            except Exception as e:
                logger.warning("audio decoding failed for %s: %s", clip["id"], e)
                failed.append(clip["id"])
                continue
            media = {"src": clip["src"], "kind": "audio", "start": start, "end": end}
            if "label" in clip:
                media["label"] = clip["label"]
            yield Sample(id=clip["id"], images=[], audio=[Audio(wav)], metadata={"media": media})
        if failed:
            notices.append(
                f"audio: {len(failed)} clip(s) could not be decoded and were skipped "
                f"({', '.join(failed[:5])}{', …' if len(failed) > 5 else ''}); the log has "
                f"ffmpeg's reason for each. Check the files play, then re-run to fill them in."
            )

    def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
        return []  # nothing to show but the player, which packaging sets up from `media`

    return Source(
        iter_samples=_iter,
        materialise=_materialise,
        notices=notices,
        config={"kind": "audio", "sample_rate": sample_rate, "exts": list(exts)},
    )
