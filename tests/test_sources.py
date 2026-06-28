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
