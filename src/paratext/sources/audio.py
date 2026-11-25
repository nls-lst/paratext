"""Sound recordings, one Sample per clip, sent to the model as audio, as a
transcript, or both."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from ..projects import Audio, Sample
from .base import Source
from .manifest import list_clips

if TYPE_CHECKING:
    from ..transcripts import Transcriber

logger = logging.getLogger(__name__)

AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff")


def audio_source(
    *,
    sample_rate: int = 16000,
    exts: tuple[str, ...] = AUDIO_EXTS,
    transcribe: "Transcriber | None" = None,
    send_audio: bool | None = None,
) -> Source:
    """Sound recordings, one Sample per clip, each decoded to mono WAV at
    ``sample_rate`` Hz.

    The source is a directory of audio files (recursive; id = filename stem) or a
    manifest, ``.jsonl`` or ``.csv``, as for ``video_source``: ``id`` and ``src``,
    optionally ``start`` and ``end`` in seconds and ``label``; other columns reach
    the transcriber under ``clip["extra"]``. A manifest lets one long recording
    yield several clips. The review UI plays the clip. Needs ffmpeg on PATH.

    ``transcribe`` (see ``paratext.transcripts``) turns each clip into timed text,
    which the model gets after the prompt and the reviewer sees as a track on the
    timeline. ``send_audio`` sends the sound itself as an ``input_audio`` part; it
    defaults to on without a transcriber and off with one, so a text-only model
    works from the transcript.
    """
    from ..ffmpeg import decode_audio, probe_duration
    from ..transcripts import transcribe_clip

    send = (transcribe is None) if send_audio is None else send_audio
    notices: list[str] = []

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        clips = list_clips(source, exts, "audio")
        if limit is not None:
            clips = clips[:limit]
        failed = []
        for clip in clips:
            try:
                start = clip.get("start", 0.0)
                end = clip.get("end") or probe_duration(clip["src"])
                wav = decode_audio(clip["src"], start, end, sample_rate)
                tx = transcribe_clip(transcribe, wav, clip, start) if transcribe else None
            except Exception as e:
                logger.warning("audio failed for %s: %s", clip["id"], e)
                failed.append(clip["id"])
                continue
            media = {"src": clip["src"], "kind": "audio", "start": start, "end": end}
            if "label" in clip:
                media["label"] = clip["label"]
            meta: dict = {"media": media}
            if tx:
                media["tracks"] = [tx["track"]]
                meta["transcript"] = tx["segments"]
            yield Sample(
                id=clip["id"],
                images=[],
                audio=[Audio(wav)] if send else [],
                text=[tx["text"]] if tx else [],
                metadata=meta,
            )
        if failed:
            notices.append(
                f"audio: {len(failed)} clip(s) could not be decoded or transcribed and were "
                f"skipped ({', '.join(failed[:5])}{', …' if len(failed) > 5 else ''}); the log "
                f"has the reason for each. Fix them, then re-run to fill them in."
            )

    def _materialise(rec: dict, out: Path, max_size: int) -> list[str]:
        return []  # nothing to show but the player, which packaging sets up from `media`

    return Source(
        iter_samples=_iter,
        materialise=_materialise,
        notices=notices,
        config={
            "kind": "audio",
            "sample_rate": sample_rate,
            "exts": list(exts),
            "transcribe": getattr(transcribe, "__name__", repr(transcribe)) if transcribe else None,
            "send_audio": send,
        },
    )
