"""Input adapters: image iteration, verso pre-filter, and materialisation."""

from pathlib import Path

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


def test_crop_falls_back_to_content_aware_when_detector_unavailable(tmp_path, monkeypatch):
    """crop=True with no detector must still crop — content-aware, not the old
    blind 8% margin, which cut into headings on cards sitting near an edge — and
    raise a notice so the run summary can't look clean."""
    import paratext.cards as cards

    monkeypatch.setattr(cards, "load_card_detector", lambda **kw: None)
    # A card on a dark desk, flush to the left edge — the shape the blind margin
    # got wrong. Text starts at x=2, so any left-hand trim loses it.
    a = np.full((400, 600), 30, dtype=np.uint8)   # desk
    a[40:360, 0:430] = 205                        # card, hard against x=0
    a[120:288, 2:400][:, ::2] = 0                 # strokes
    Image.fromarray(a, "L").convert("RGB").save(tmp_path / "a.jpg", "JPEG")

    src = image_source(crop=True)
    samples = list(src.iter_samples(tmp_path, None))

    assert samples[0].metadata["crop"] == "content"
    assert samples[0].metadata["detected"] is False
    cropped = samples[0].images[0]
    assert cropped.size[0] < 600  # the desk on the right is gone
    assert any("detector unavailable" in n for n in src.notices)


def test_a_card_filling_the_frame_is_left_alone(tmp_path, monkeypatch):
    """No desk to trim means no crop. The old blind 8% margin removed content
    here regardless."""
    import paratext.cards as cards

    monkeypatch.setattr(cards, "load_card_detector", lambda **kw: None)
    _save(tmp_path / "a.jpg", textured=True)

    samples = list(image_source(crop=True).iter_samples(tmp_path, None))
    assert samples[0].images[0].size == (600, 400)


def test_no_notices_when_crop_not_requested(tmp_path):
    _save(tmp_path / "a.jpg", textured=True)
    src = image_source()
    list(src.iter_samples(tmp_path, None))
    assert src.notices == []


# ── Hugging Face datasets ───────────────────────────────────────────────────
def _fake_hub(monkeypatch, tmp_path, names):
    """Stand in for the Hub: list_repo_files returns `names`, and each download
    produces a real image file so the caller gets a usable Sample."""
    import huggingface_hub

    class FakeApi:
        def __init__(self, token=None):
            self.token = token

        def list_repo_files(self, repo_id, repo_type=None, revision=None):
            return list(names)

    def fake_download(repo_id, name, **kw):
        dest = tmp_path / name.replace("/", "_")
        Image.fromarray(np.full((8, 8, 3), 255, np.uint8)).save(dest)
        return str(dest)

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_download)


def test_hf_dataset_source_strips_the_shared_directory_from_ids(monkeypatch, tmp_path):
    from paratext.sources import hf_dataset_source

    # An imagefolder dataset keeps everything under images/; carrying that into
    # every id only makes them longer, and they should match the originals.
    _fake_hub(monkeypatch, tmp_path, ["README.md", "images/a.jpg", "images/b.jpg"])
    ids = [s.id for s in hf_dataset_source(repo="o/n").iter_samples(Path("x"), None)]
    assert ids == ["a", "b"]


def test_hf_dataset_source_keeps_structure_when_dirs_differ(monkeypatch, tmp_path):
    from paratext.sources import hf_dataset_source

    _fake_hub(monkeypatch, tmp_path, ["train/a.jpg", "test/b.jpg"])
    ids = sorted(s.id for s in hf_dataset_source(repo="o/n").iter_samples(Path("x"), None))
    assert ids == ["test__b", "train__a"]


def test_hf_dataset_source_takes_the_repo_from_the_source_argument(monkeypatch, tmp_path):
    from paratext.sources import hf_dataset_source

    # So `--source owner/name` works without rebuilding the project.
    _fake_hub(monkeypatch, tmp_path, ["images/a.jpg"])
    samples = list(hf_dataset_source().iter_samples(Path("owner/name"), None))
    assert samples[0].metadata["hf_repo"] == "owner/name"


def test_hf_dataset_source_rejects_something_that_is_not_a_repo_id(monkeypatch, tmp_path):
    import pytest

    from paratext.sources import hf_dataset_source

    _fake_hub(monkeypatch, tmp_path, ["images/a.jpg"])
    with pytest.raises(ValueError, match="expected owner/name"):
        list(hf_dataset_source().iter_samples(Path("./some/local/dir"), None))


def test_hf_dataset_source_says_so_when_there_are_no_images(monkeypatch, tmp_path):
    import pytest

    from paratext.sources import hf_dataset_source

    # A parquet-backed dataset lands here, and the message has to say why.
    _fake_hub(monkeypatch, tmp_path, ["data/train-00000.parquet", "README.md"])
    with pytest.raises(FileNotFoundError, match="imagefolder-style"):
        list(hf_dataset_source(repo="o/n").iter_samples(Path("x"), None))


def test_hf_dataset_source_never_records_the_token_value(monkeypatch, tmp_path):
    from paratext.sources import hf_dataset_source

    # config is surfaced by `paratext inspect`; a credential must not ride along.
    src = hf_dataset_source(repo="o/n", token="hf_secret_value")
    assert src.config["token"] is True
    assert "hf_secret_value" not in str(src.config)


def test_hf_dataset_source_honours_limit(monkeypatch, tmp_path):
    from paratext.sources import hf_dataset_source

    _fake_hub(monkeypatch, tmp_path, [f"images/{i}.jpg" for i in range(10)])
    assert len(list(hf_dataset_source(repo="o/n").iter_samples(Path("x"), 3))) == 3
