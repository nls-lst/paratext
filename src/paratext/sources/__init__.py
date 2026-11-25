"""Input adapters: turn a source directory into Samples (for extraction) and
review images (for packaging), so a project rarely writes iteration code.

A `Source` bundles the two halves that must agree on a metadata shape:

    iter_samples(source, limit) -> Iterator[Sample]      # extraction time
    materialise(record, out, max_size) -> [rel_path]     # packaging time

Pass one to ``Project(source=…)`` and the framework wires both. Built in, one
module each: ``image_source`` (a flat directory of images, with optional verso
filter and card crop), ``pdf_source`` (PDFs rendered to page images),
``hf_dataset_source`` (an imagefolder dataset on the Hub) and ``video_source``
(videos sampled to frames). Time-based sources share ``manifest.read_manifest``.
"""

from .base import Source
from .hf import HF_CACHE_ENV, hf_dataset_source
from .images import IMAGE_EXTS, image_source
from .manifest import read_manifest
from .pdf import first_pages_plus_last, pdf_source
from .video import VIDEO_EXTS, video_source

__all__ = [
    "HF_CACHE_ENV",
    "IMAGE_EXTS",
    "VIDEO_EXTS",
    "Source",
    "first_pages_plus_last",
    "hf_dataset_source",
    "image_source",
    "pdf_source",
    "read_manifest",
    "video_source",
]
