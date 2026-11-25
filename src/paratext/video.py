"""Frame sampling for video sources, via ffmpeg (see ``ffmpeg.py``)."""

from __future__ import annotations

import io
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg import FfmpegError, probe_duration, run, tool

FrameTimes = Callable[[float, float], list[float]]

# Kept for callers that catch it by its old name; ffmpeg failures of any kind
# now raise FfmpegError.
VideoError = FfmpegError

__all__ = ["FrameTimes", "VideoError", "clock", "evenly_spaced", "grab_frame",
           "probe_duration", "stamp"]


def grab_frame(src: str, t: float) -> Image.Image:
    # -ss before -i seeks by keyframe then decodes forward: fast and exact.
    out = run(
        [tool("ffmpeg"), "-v", "error", "-ss", f"{t:.3f}", "-i", src,
         "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"],
        timeout=300,
    )
    if not out:
        raise FfmpegError(f"no frame at {t:.1f}s in {src}")
    return Image.open(io.BytesIO(out)).convert("RGB")


def evenly_spaced(n: int = 8) -> FrameTimes:
    """n frames at the midpoints of n equal slices, so none is a fade-in."""

    def times(start: float, end: float) -> list[float]:
        step = (end - start) / n
        return [round(start + (i + 0.5) * step, 3) for i in range(n)]

    times.__name__ = f"evenly_spaced({n})"
    return times


def clock(t: float) -> str:
    t = max(0, round(t))
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def stamp(img: Image.Image, t: float) -> Image.Image:
    """Add the frame's time on a band below the picture, not over it."""
    band = max(20, img.height // 20)
    out = Image.new("RGB", (img.width, img.height + band), "black")
    out.paste(img, (0, 0))
    font = ImageFont.load_default(size=int(band * 0.7))
    ImageDraw.Draw(out).text((band // 3, img.height + band // 2), clock(t),
                             fill="white", font=font, anchor="lm")
    return out
