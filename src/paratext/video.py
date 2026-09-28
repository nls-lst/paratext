"""Frame sampling for video sources, via the ffmpeg and ffprobe executables."""

from __future__ import annotations

import io
import shutil
import subprocess
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

FrameTimes = Callable[[float, float], list[float]]


class VideoError(RuntimeError):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise VideoError(f"{name} not found on PATH; video sources need ffmpeg installed")
    return path


def _run(args: list[str], timeout: int) -> bytes:
    try:
        done = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise VideoError(f"{args[0]} timed out after {timeout}s") from e
    if done.returncode != 0:
        msg = done.stderr.decode(errors="replace").strip().splitlines()
        raise VideoError(msg[-1] if msg else f"{args[0]} exited {done.returncode}")
    return done.stdout


def probe_duration(src: str) -> float:
    out = _run(
        [_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", src],
        timeout=120,
    )
    try:
        return float(out.decode().strip())
    except ValueError:
        raise VideoError(f"no duration for {src}") from None


def grab_frame(src: str, t: float) -> Image.Image:
    # -ss before -i seeks by keyframe then decodes forward: fast and exact.
    out = _run(
        [_tool("ffmpeg"), "-v", "error", "-ss", f"{t:.3f}", "-i", src,
         "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"],
        timeout=300,
    )
    if not out:
        raise VideoError(f"no frame at {t:.1f}s in {src}")
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
