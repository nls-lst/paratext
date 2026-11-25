"""The ffmpeg and ffprobe executables, shared by the time-based sources:
durations, video frames (``video.py``) and decoded audio."""

from __future__ import annotations

import io
import shutil
import subprocess
import wave


class FfmpegError(RuntimeError):
    pass


def tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FfmpegError(f"{name} not found on PATH; audio and video sources need ffmpeg")
    return path


def run(args: list[str], timeout: int) -> bytes:
    try:
        done = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FfmpegError(f"{args[0]} timed out after {timeout}s") from e
    if done.returncode != 0:
        msg = done.stderr.decode(errors="replace").strip().splitlines()
        raise FfmpegError(msg[-1] if msg else f"{args[0]} exited {done.returncode}")
    return done.stdout


def probe_duration(src: str) -> float:
    out = run(
        [tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", src],
        timeout=120,
    )
    try:
        return float(out.decode().strip())
    except ValueError:
        raise FfmpegError(f"no duration for {src}") from None


def decode_audio(src: str, start: float = 0.0, end: float | None = None,
                 rate: int = 16000) -> bytes:
    """The audio of ``src`` from ``start`` to ``end`` seconds as a mono 16-bit WAV
    at ``rate`` Hz: the shape speech models expect. A video's soundtrack works too."""
    args = [tool("ffmpeg"), "-v", "error", "-ss", f"{start:.3f}", "-i", src]
    if end is not None:
        args += ["-t", f"{end - start:.3f}"]
    # Raw samples, wrapped here: a WAV that ffmpeg writes to a pipe can't have its
    # length filled in afterwards, and readers then take the stream to be hours long.
    pcm = run(args + ["-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], timeout=1800)
    if not pcm:
        raise FfmpegError(f"no audio in {src} between {start:.1f}s and {end}")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
