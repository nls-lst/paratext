"""Input adapters: image iteration, verso pre-filter, and materialisation."""

import numpy as np
from PIL import Image

from paratext.sources import image_source


def _save(path, textured):
    a = np.full((400, 600), 200, dtype=np.uint8)
    if textured:
        a[120:288, 108:492][:, ::2] = 0  # dark strokes in the centre → a "card"
    Image.fromarray(a, "L").convert("RGB").save(path, "JPEG")


def test_image_source_iterates_and_filters_verso(tmp_path):
    _save(tmp_path / "card.jpg", textured=True)
    _save(tmp_path / "back.jpg", textured=False)  # blank → verso

    src = image_source(verso_filter=True, crop=False)
    samples = {s.id: s for s in src.iter_samples(tmp_path, None)}

    assert set(samples) == {"card", "back"}
    # verso is pre-classified and carries no image for the VLM
    assert samples["back"].metadata["preclassified"] == {"image_type": "verso"}
    assert samples["back"].images == []
    assert samples["card"].images  # a real card keeps its image
    assert "preclassified" not in samples["card"].metadata


def test_image_source_limit_and_materialise(tmp_path):
    _save(tmp_path / "a.jpg", textured=True)
    src = image_source()
    samples = list(src.iter_samples(tmp_path, 1))
    assert len(samples) == 1

    out = tmp_path / "ds"
    rec = {"id": "a", "metadata": {"image_path": str(tmp_path / "a.jpg")}}
    rels = src.materialise(rec, out, 256)
    assert rels == ["images/a/image.jpg"]
    assert (out / "images/a/image.jpg").is_file()


def test_crop_falls_back_to_uniform_when_detector_unavailable(tmp_path, monkeypatch):
    """crop=True with no detector must still crop (uniformly) and say so — the
    documented fallback, and a notice so the run summary can't look clean."""
    import paratext.cards as cards

    monkeypatch.setattr(cards, "load_card_detector", lambda **kw: None)
    _save(tmp_path / "a.jpg", textured=True)

    src = image_source(crop=True)
    samples = list(src.iter_samples(tmp_path, None))

    assert samples[0].metadata["crop"] == "uniform"
    assert samples[0].metadata["detected"] is False
    assert samples[0].images[0].size < (600, 400)  # actually cropped
    assert any("detector unavailable" in n for n in src.notices)


def test_no_notices_when_crop_not_requested(tmp_path):
    _save(tmp_path / "a.jpg", textured=True)
    src = image_source()
    list(src.iter_samples(tmp_path, None))
    assert src.notices == []
