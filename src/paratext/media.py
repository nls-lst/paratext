"""A sample's `media`: a video or sound recording the review UI plays in place
of its images. The shape is documented in docs/review-views.md; only `src` is
required."""

from __future__ import annotations

_KEYS = {"src", "type", "kind", "start", "end", "poster", "label", "tracks"}
# Extensions that mean a sound recording when `kind` isn't given; anything else
# plays in a video element, which also plays sound.
_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus")


class MediaError(ValueError):
    pass


def _seconds(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise MediaError(f"{what} must be a non-negative number of seconds, got {v!r}")
    return v


def normalise_media(m: dict) -> dict:
    """Validate a media dict and fill in its defaults."""
    if not isinstance(m, dict):
        raise MediaError(f"media must be an object, got {type(m).__name__}")
    unknown = set(m) - _KEYS
    if unknown:
        raise MediaError(f"unknown media keys: {', '.join(sorted(unknown))}")
    src = m.get("src")
    if not isinstance(src, str) or not src:
        raise MediaError("media needs a src")

    out: dict = {"src": src}
    out["type"] = m.get("type") or ("hls" if src.split("?")[0].endswith(".m3u8") else "file")
    if out["type"] not in ("hls", "file"):
        raise MediaError(f"media type must be 'hls' or 'file', got {out['type']!r}")
    path = src.split("?")[0].lower()
    out["kind"] = m.get("kind") or ("audio" if path.endswith(_AUDIO_EXTS) else "video")
    if out["kind"] not in ("audio", "video"):
        raise MediaError(f"media kind must be 'audio' or 'video', got {out['kind']!r}")
    out["start"] = _seconds(m.get("start", 0), "media start")
    if m.get("end") is not None:
        out["end"] = _seconds(m["end"], "media end")
        if out["end"] <= out["start"]:
            raise MediaError("media end must come after start")
    for key in ("poster", "label"):
        if m.get(key):
            out[key] = m[key]

    tracks = m.get("tracks") or []
    if tracks and "end" not in out:
        raise MediaError("media tracks need an end, to draw the clip on the timeline")
    out["tracks"] = [_track(t, i) for i, t in enumerate(tracks)]
    return out


def _track(t: dict, i: int) -> dict:
    if not isinstance(t, dict) or not isinstance(t.get("name"), str):
        raise MediaError(f"media track {i} needs a name")
    out = {"name": t["name"], "items": []}
    if t.get("note"):
        out["note"] = t["note"]
    for j, it in enumerate(t.get("items") or []):
        what = f"track {t['name']!r} item {j}"
        item = {
            "start": _seconds(it.get("start"), f"{what} start"),
            "text": str(it.get("text", "")),
        }
        if it.get("end") is not None:
            item["end"] = _seconds(it["end"], f"{what} end")
        out["items"].append(item)
    return out
