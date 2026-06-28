"""Reusable preprocessing for scanned index-card collections.

Two independent, opt-in tools that any card project can use:

  - ``is_verso(image)`` — a pure-NumPy blank-back filter with **no ML
    dependency**. It drops blank versos (the backs of cards) before any
    detector or VLM call. The thresholds are exposed as arguments because they
    are calibrated to a particular scanning setup; recalibrate for yours.

  - ``load_card_detector()`` — a torchvision **RetinaNet** (BSD-licensed) that
    crops a scan to the card region. The weights download from the Hugging Face
    Hub on first use (cached); the runtime needs the ``[cards]`` extra
    (``torch`` + ``torchvision``). If either is unavailable the loader returns
    ``None`` so callers fall back to a uniform-margin crop.

Both are deliberately schema-agnostic — they know nothing about any project's
prompt or output fields.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Default Hugging Face model repo for the card detector. Override per-call or
# via the PARATEXT_CARD_DETECTOR env var (a local weights path).
DEFAULT_DETECTOR_REPO = "nls-lst/card-detector-retinanet"
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
# to the VLM / a human (the safe way). Other collections will want to recheck.
VERSO_TEXTURE_MAX = 18.0  # centre-right std below this = blank (no entries text)
VERSO_DARKTEXT_MAX = 0.02  # central dark-pixel fraction below this = no ink/text


def is_verso(
    image: Image.Image,
    *,
    texture_max: float = VERSO_TEXTURE_MAX,
    darktext_max: float = VERSO_DARKTEXT_MAX,
) -> bool:
    """True if the image is a blank verso (uniform centre + no dark text), so it
    can skip the detector and the VLM. Border-independent — works across a
    collection's scan-config changes (e.g. a black binding band vs a manilla
    background). Tune ``texture_max`` / ``darktext_max`` for your scans."""
    a = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = a.shape
    cr_std = a[int(0.35 * h) : int(0.65 * h), int(0.55 * w) : int(0.90 * w)].std()
    centre = a[int(0.30 * h) : int(0.72 * h), int(0.18 * w) : int(0.82 * w)]
    dark_frac = float((centre < 90).mean())
    return bool(cr_std < texture_max and dark_frac < darktext_max)


# ── Crop helpers ───────────────────────────────────────────────────────────
def crop_uniform(img: Image.Image, margin_pct: float = 0.08) -> Image.Image:
    """Fallback crop when no detector is available: trim a uniform margin."""
    w, h = img.size
    mx, my = int(w * margin_pct), int(h * margin_pct)
    return img.crop((mx, my, w - mx, h - my))


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
    repo_id: str = DEFAULT_DETECTOR_REPO,
    filename: str = DEFAULT_DETECTOR_FILE,
    weights: str | Path | None = None,
    device: str = "cpu",
    conf: float = 0.5,
) -> CardDetector | None:
    """Load the RetinaNet card detector, or return ``None`` to fall back to a
    uniform crop.

    Weights resolution: ``weights`` arg → ``PARATEXT_CARD_DETECTOR`` env var →
    download ``filename`` from the ``repo_id`` Hugging Face repo (cached). Any
    failure (missing ``[cards]`` runtime, offline, bad weights) is logged and
    yields ``None`` rather than raising, so the pipeline still runs."""
    path = weights or os.environ.get("PARATEXT_CARD_DETECTOR")
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
