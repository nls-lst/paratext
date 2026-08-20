"""Reusable preprocessing for scanned index-card collections.

Two independent, opt-in tools that any card project can use:

  - ``is_verso(image)`` — a pure-NumPy blank-back filter with **no ML
    dependency**. It drops blank versos (the backs of cards) before any
    detector or model call. The thresholds are exposed as arguments because they
    are calibrated to a particular scanning setup; recalibrate for yours.

  - ``load_card_detector()`` — a torchvision **RetinaNet** (BSD-licensed) that
    crops a scan to the card region. The weights download from the Hugging Face
    Hub on first use (cached); the runtime needs the ``[detector]`` extra
    (``torch`` + ``torchvision``). If either is unavailable the loader returns
    ``None`` so callers fall back to a uniform-margin crop.

Both are deliberately schema-agnostic — they know nothing about any project's
prompt or output fields.

Both are also **calibrated to one collection**: the default weights are trained
on National Library of Scotland catalogue cards, and the verso thresholds come
from that same material. Neither is expected to transfer unchanged to another
library's scans — point the ``[detector]`` config table at your own weights and
recalibrate the thresholds before relying on them.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Reference weights for the card detector, trained on NLS catalogue cards. This
# is a starting point, not a general-purpose card detector: another collection's
# cards will likely need their own weights. Override with the `[detector]` table
# in paratext.toml (`repo`/`file` for the Hub, `weights` for a local path), the
# PARATEXT_CARD_DETECTOR env var, or the `weights=` argument.
DEFAULT_DETECTOR_REPO = "NationalLibraryOfScotland/card-detector-retinanet"
DEFAULT_DETECTOR_FILE = "card_detector_retinanet.pt"


# ── Verso pre-filter ───────────────────────────────────────────────────────
# A verso (blank back of a card) has no text — just blank card, maybe faint
# reversed show-through. A recto has typed text. So detect "blankness" directly,
# independent of the binding/background:
#   - the centre-right has near-zero texture (uniform), and
#   - the card centre has essentially no dark (ink) pixels.
# The reference thresholds below were calibrated against 1035 human-labelled
# NLS images (97 versos / 938 cards) spanning two scan configs: ZERO false
# positives (never drops a real card) at ~96% verso recall; misses fall through
# to the model / a human (the safe way). Other collections will want to recheck.
VERSO_TEXTURE_MAX = 18.0  # centre-right std below this = blank (no entries text)
VERSO_DARKTEXT_MAX = 0.02  # central dark-pixel fraction below this = no ink/text


def is_verso(
    image: Image.Image,
    *,
    texture_max: float = VERSO_TEXTURE_MAX,
    darktext_max: float = VERSO_DARKTEXT_MAX,
) -> bool:
    """True if the image is a blank verso (uniform centre + no dark text), so it
    can skip the detector and the model. Border-independent — works across a
    collection's scan-config changes (e.g. a black binding band vs a manilla
    background). Tune ``texture_max`` / ``darktext_max`` for your scans."""
    a = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = a.shape
    cr_std = a[int(0.35 * h) : int(0.65 * h), int(0.55 * w) : int(0.90 * w)].std()
    centre = a[int(0.30 * h) : int(0.72 * h), int(0.18 * w) : int(0.82 * w)]
    dark_frac = float((centre < 90).mean())
    return bool(cr_std < texture_max and dark_frac < darktext_max)


# ── Show-through suppression ───────────────────────────────────────────────
# Calibrated on NLS cards 0255/0269/0291 against cataloguer-confirmed ground
# truth. Reduces show-through, does not eliminate it: darker ghosts survive, so
# the prompt's structural checks still matter.
SHOW_THROUGH_KEEP = 0.70  # cutoff, as a fraction of the ink→paper range


def suppress_show_through(
    image: Image.Image, *, keep: float = SHOW_THROUGH_KEEP
) -> Image.Image:
    """Flatten faint show-through from stacked cards to paper-white, leaving the
    card's own ink untouched.

    ``keep`` sets the cutoff between the darkest ink (0.0) and paper (1.0);
    anything lighter is whitened. LOWER removes more show-through but risks
    erasing genuinely faint print, which is the costlier error. Recalibrate per
    collection — see ``tests/test_show_through.py``."""
    a = np.asarray(image.convert("L"), dtype=np.float32)
    # Levels come from the card, not the frame: the dark desk and binding would
    # drag the ink level down and leave the cutoff too low to suppress anything.
    h, w = a.shape
    centre = a[int(0.30 * h) : int(0.72 * h), int(0.18 * w) : int(0.82 * w)]
    paper = float(np.percentile(centre, 85))
    ink = float(np.percentile(centre, 2))
    if paper - ink < 1.0:  # near-uniform (blank/verso): leave alone
        return image
    # Soft threshold, not a contrast stretch: a stretch darkens the ghost and
    # amplifies paper grain, making show-through easier for the model to read.
    cutoff = ink + (paper - ink) * keep
    ramp = max((paper - ink) * 0.08, 6.0)  # floor stops low-contrast cards speckling
    t = np.clip((a - cutoff) / max(ramp, 1e-6), 0.0, 1.0)
    out = a * (1.0 - t) + 255.0 * t
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="L")


# ── Crop helpers ───────────────────────────────────────────────────────────
def crop_uniform(img: Image.Image, margin_pct: float = 0.08) -> Image.Image:
    """Trim a fixed margin off every edge.

    A blind fraction: it cannot tell a margin from a heading, so on scans where
    the text runs close to an edge it removes content. Kept for callers that
    want the old behaviour; :func:`crop_content` is the better fallback.
    """
    w, h = img.size
    mx, my = int(w * margin_pct), int(h * margin_pct)
    return img.crop((mx, my, w - mx, h - my))


def _otsu(values: "np.ndarray") -> float:
    """Otsu's threshold — the grey level splitting the histogram into two classes
    with the smallest combined spread. Here: card against the darker desk."""
    hist = np.bincount(values.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    levels = np.arange(256)
    total = hist.sum()
    if total == 0:
        return 127.0
    w_bg = np.cumsum(hist)
    w_fg = total - w_bg
    sum_bg = np.cumsum(hist * levels)
    sum_all = sum_bg[-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_bg = sum_bg / w_bg
        mean_fg = (sum_all - sum_bg) / w_fg
        between = w_bg * w_fg * (mean_bg - mean_fg) ** 2
    between[~np.isfinite(between)] = 0.0
    return float(np.argmax(between))


def content_box(
    img: Image.Image,
    *,
    pad_pct: float = 0.01,
    coverage: float = 0.5,
    min_area: float = 0.15,
) -> tuple[int, int, int, int] | None:
    """Locate the card against the darker background; returns an (x0,y0,x1,y1) box.

    Returns None when the result wouldn't be trustworthy, so a caller can leave
    the scan alone rather than guess. That asymmetry is deliberate: an
    over-crop silently deletes text and is scored as a misreading, while an
    under-crop only costs the model some desk to look at.

    A card is bright and fills most of its rows and columns, so a row/column
    coverage profile over an Otsu mask locates it without any ML. `coverage` is
    the fraction of a row (or column) that must be card-bright for it to count
    as inside; `min_area` rejects a box too small to be the card.
    """
    w, h = img.size
    if w < 32 or h < 32:
        return None
    # Downscale first: the card boundary is a coarse feature, and this keeps the
    # profile cheap on a 2400px scan.
    small = img.convert("L")
    small.thumbnail((512, 512), Image.Resampling.BILINEAR)
    grey = np.asarray(small, dtype=np.float32)
    # Otsu assumes two classes. On a scan with no card/desk contrast — a blank
    # frame, an all-dark misfeed — it splits noise and "finds" the whole image,
    # so require a real spread before trusting it.
    if float(grey.max() - grey.min()) < 20.0:
        return None
    mask = grey > _otsu(grey)

    def span(profile: "np.ndarray") -> tuple[int, int] | None:
        inside = np.flatnonzero(profile >= coverage)
        return (int(inside[0]), int(inside[-1])) if inside.size else None

    cols = span(mask.mean(axis=0))
    rows = span(mask.mean(axis=1))
    if cols is None or rows is None:
        return None

    sw, sh = small.size
    x0, x1 = (c * w / sw for c in (cols[0], cols[1] + 1))
    y0, y1 = (r * h / sh for r in (rows[0], rows[1] + 1))
    px, py = w * pad_pct, h * pad_pct
    box = (
        max(0, int(x0 - px)), max(0, int(y0 - py)),
        min(w, int(x1 + px)), min(h, int(y1 + py)),
    )
    if (box[2] - box[0]) * (box[3] - box[1]) < min_area * w * h:
        return None
    return box


def crop_content(img: Image.Image, **kw) -> Image.Image | None:
    """Crop to :func:`content_box`, or None when no trustworthy box was found."""
    box = content_box(img, **kw)
    return None if box is None else img.crop(box)


def _crop_bbox(img: Image.Image, bbox: list[float], padding_pct: float = 0.02) -> Image.Image:
    w, h = img.size
    x, y, bw, bh = bbox
    px, py = int(bw * padding_pct), int(bh * padding_pct)
    return img.crop((
        max(0, int(x) - px),
        max(0, int(y) - py),
        min(w, int(x + bw) + px),
        min(h, int(y + bh) + py),
    ))


# ── Detector ───────────────────────────────────────────────────────────────
class CardDetector:
    """Permissive (torchvision RetinaNet ResNet50-FPN v2, BSD) card detector.

    Prefer :func:`load_card_detector`, which handles the optional runtime and
    weight download and degrades to ``None`` gracefully."""

    def __init__(
        self,
        weights: str | Path,
        device: str = "cpu",
        conf: float = 0.5,
        max_side: int = 800,
    ):
        import torch
        from torchvision.models.detection import retinanet_resnet50_fpn_v2

        path = Path(weights)
        if not path.exists():
            raise FileNotFoundError(f"card detector weights not found at {path}")
        model = retinanet_resnet50_fpn_v2(weights=None, num_classes=2)
        model.load_state_dict(torch.load(path, map_location=device))
        model.eval().to(device)
        self._torch = torch
        self.model = model
        self.device = device
        self.conf = conf
        self.max_side = max_side

    def detect(self, image: Image.Image) -> list[float] | None:
        """Return [x, y, w, h] (original-image coords) of the best card, or None."""
        import torchvision.transforms.functional as TF

        w, h = image.size
        s = min(1.0, self.max_side / max(w, h))
        im = image.resize((max(1, int(w * s)), max(1, int(h * s)))) if s < 1.0 else image
        with self._torch.no_grad():
            out = self.model([TF.to_tensor(im).to(self.device)])[0]
        scores = out["scores"]
        if int((scores > self.conf).sum()) == 0:
            return None
        i = int(scores.argmax())
        x1, y1, x2, y2 = (v / s for v in out["boxes"][i].tolist())
        return [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]

    def crop(
        self,
        image: Image.Image,
        bbox: list[float] | None = None,
        padding_pct: float = 0.02,
        fallback_margin: float = 0.08,
    ) -> Image.Image:
        """Crop to the detected card, or a uniform margin if nothing is found."""
        if bbox is None:
            bbox = self.detect(image)
        if bbox is None:
            return crop_uniform(image, fallback_margin)
        return _crop_bbox(image, bbox, padding_pct)


def load_card_detector(
    *,
    repo_id: str | None = None,
    filename: str | None = None,
    weights: str | Path | None = None,
    device: str = "cpu",
    conf: float = 0.5,
) -> CardDetector | None:
    """Load the RetinaNet card detector, or return ``None`` to fall back to a
    uniform crop.

    Weights resolution, highest first: the ``weights`` argument →
    ``PARATEXT_CARD_DETECTOR`` env var → ``weights`` in the ``[detector]`` table
    of paratext.toml (a local path) → download ``filename`` from the ``repo_id``
    Hugging Face repo (cached). Any failure (missing ``[detector]`` runtime,
    offline, bad weights) is logged and yields ``None`` rather than raising, so
    the pipeline still runs.

    ``repo_id``/``filename`` likewise fall back to the ``[detector]`` table
    (``repo`` / ``file``), then to the reference weights."""
    from .config import load_table

    cfg = load_table("detector")
    repo_id = repo_id or cfg.get("repo") or DEFAULT_DETECTOR_REPO
    filename = filename or cfg.get("file") or DEFAULT_DETECTOR_FILE
    # A local path beats the Hub: training your own is the expected case once
    # you move off the reference weights, and re-uploading to run is friction.
    path = weights or os.environ.get("PARATEXT_CARD_DETECTOR") or cfg.get("weights")
    if path is None:
        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(repo_id=repo_id, filename=filename)
        except Exception as e:
            logger.warning("card detector weights unavailable (%s); using uniform crop.", e)
            return None
    try:
        return CardDetector(path, device=device, conf=conf)
    except Exception as e:
        logger.warning("card detector runtime unavailable (%s); using uniform crop.", e)
        return None
