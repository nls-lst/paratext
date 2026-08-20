"""Show-through suppression. The risk is asymmetric — leftover show-through can
still be rejected downstream, but erased faint print is a silently lost entry —
so these pin "real ink survives" hard and only assert direction on the ghost."""

import numpy as np
from PIL import Image

from paratext.cards import content_box, crop_content, suppress_show_through

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


# ── Content-aware crop ───────────────────────────────────────────────────────
# The blind 8% `crop_uniform` cut into headings on scans where the card sits
# close to an edge, which scored as a misreading. `content_box` locates the card
# against the darker background instead.
def _card_on_desk(size=(400, 300), box=(10, 40, 380, 260), desk=40, card=230):
    """A bright card on a dark desk, the card hard against the left margin."""
    a = np.full((size[1], size[0]), desk, dtype=np.uint8)
    x0, y0, x1, y1 = box
    a[y0:y1, x0:x1] = card
    return Image.fromarray(a, mode="L").convert("RGB")


def test_content_box_finds_the_card():
    img = _card_on_desk()
    x0, y0, x1, y1 = content_box(img)
    # within a few px of the true edges (downscale + 1% pad)
    assert abs(x0 - 10) < 20 and abs(y0 - 40) < 20
    assert abs(x1 - 380) < 20 and abs(y1 - 260) < 20


def test_content_box_keeps_a_card_flush_to_the_left_edge():
    # The regression: a heading starting at x=2 must survive.
    img = _card_on_desk(box=(0, 40, 380, 260))
    assert content_box(img)[0] == 0


def test_content_box_gives_up_rather_than_guessing():
    # A uniformly dark scan has no card to find; returning None lets the caller
    # leave the image alone instead of cropping blind.
    flat = Image.fromarray(np.full((300, 400), 30, dtype=np.uint8), mode="L").convert("RGB")
    assert content_box(flat) is None


def test_content_box_rejects_a_box_that_is_too_small():
    img = _card_on_desk(box=(180, 140, 220, 170))  # a speck, not a card
    assert content_box(img) is None


def test_crop_content_returns_none_when_the_box_does():
    flat = Image.fromarray(np.full((300, 400), 30, dtype=np.uint8), mode="L").convert("RGB")
    assert crop_content(flat) is None


def test_crop_content_crops_to_the_box():
    img = _card_on_desk()
    out = crop_content(img)
    assert out is not None and out.size < img.size


def test_tiny_images_are_refused():
    assert content_box(Image.new("RGB", (16, 16), "white")) is None
