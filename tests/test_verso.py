"""Deterministic verso pre-filter (blankness heuristic, border-independent)."""

import numpy as np
from PIL import Image

from paratext.cards import is_verso


def _page(centre_textured: bool, page: int = 210) -> Image.Image:
    """Grayscale page; the centre is either blank (verso) or carries dark
    'text' strokes (recto). The left/background tone is irrelevant to the rule."""
    a = np.full((400, 600), page, dtype=np.uint8)
    if centre_textured:
        a[120:288, 108:492][:, ::2] = 0  # dark vertical strokes in the centre
    return Image.fromarray(a, mode="L")


def test_blank_page_is_verso():
    # No centre texture, no dark ink → verso, regardless of background tone.
    assert is_verso(_page(centre_textured=False, page=210))


def test_manilla_blank_is_verso():
    # A lighter "manilla" background must still read as verso (border-independent).
    assert is_verso(_page(centre_textured=False, page=150))


def test_card_with_text_is_not_verso():
    # Dark text in the centre → a real card, not a verso.
    assert not is_verso(_page(centre_textured=True))
