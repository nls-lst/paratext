"""Show-through suppression. The risk is asymmetric — leftover show-through can
still be rejected downstream, but erased faint print is a silently lost entry —
so these pin "real ink survives" hard and only assert direction on the ghost."""

import numpy as np
from PIL import Image

from paratext.cards import suppress_show_through

PAPER, OWN_INK, GHOST = 227, 52, 190  # levels measured on NLS card scans


def _card(ghost: bool = True, own_ink: int = OWN_INK) -> Image.Image:
    a = np.full((400, 600), PAPER, dtype=np.uint8)
    a[180:200, 120:480] = own_ink  # the card's own typed line
    if ghost:
        a[240:260, 120:480] = GHOST  # bleed-through from the card behind
    return Image.fromarray(a, mode="L")


def _band(img: Image.Image, top: int, bottom: int) -> float:
    return float(np.asarray(img, dtype=np.float32)[top:bottom, 120:480].mean())


def test_own_ink_is_untouched():
    out = suppress_show_through(_card())
    assert _band(out, 180, 200) == OWN_INK


def test_faint_own_ink_survives():
    # Unevenly inked typescript is still the card's own text.
    faint = 120
    out = suppress_show_through(_card(ghost=False, own_ink=faint))
    assert _band(out, 180, 200) == faint


def test_show_through_is_flattened():
    before = _band(_card(), 240, 260)
    after = _band(suppress_show_through(_card()), 240, 260)
    assert after > before  # lighter
    assert after >= PAPER  # gone to paper-white


def test_uniform_image_is_returned_unchanged():
    blank = Image.fromarray(np.full((400, 600), PAPER, dtype=np.uint8), mode="L")
    assert np.array_equal(np.asarray(suppress_show_through(blank)), np.asarray(blank))


def test_keep_is_monotonic():
    # Lower `keep` removes more, so another collection can be tuned predictably.
    ghost_at = [_band(suppress_show_through(_card(), keep=k), 240, 260) for k in (0.9, 0.7, 0.5)]
    assert ghost_at == sorted(ghost_at)
