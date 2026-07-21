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


def test_detector_weights_resolve_from_config(tmp_path, monkeypatch):
    """[detector] weights = "/path" points at local weights without needing the
    Hub or the env var — the expected case once you train your own."""
    import paratext.cards as cards

    monkeypatch.setattr(
        "paratext.config.load_table",
        lambda section: {"weights": "/tmp/mine.pt"} if section == "detector" else {},
    )
    monkeypatch.delenv("PARATEXT_CARD_DETECTOR", raising=False)

    seen = {}

    class _Det:
        def __init__(self, path, **kw):
            seen["path"] = path

    monkeypatch.setattr(cards, "CardDetector", _Det)
    cards.load_card_detector()
    assert seen["path"] == "/tmp/mine.pt"


def test_env_var_beats_config_weights(tmp_path, monkeypatch):
    import paratext.cards as cards

    monkeypatch.setattr(
        "paratext.config.load_table",
        lambda section: {"weights": "/tmp/from-config.pt"} if section == "detector" else {},
    )
    monkeypatch.setenv("PARATEXT_CARD_DETECTOR", "/tmp/from-env.pt")

    seen = {}

    class _Det:
        def __init__(self, path, **kw):
            seen["path"] = path

    monkeypatch.setattr(cards, "CardDetector", _Det)
    cards.load_card_detector()
    assert seen["path"] == "/tmp/from-env.pt"
