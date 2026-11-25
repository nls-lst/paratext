"""Imagefolder-style datasets on the Hugging Face Hub."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from PIL import Image

from ..packaging import default_materialise
from ..projects import Sample
from .base import Source
from .images import IMAGE_EXTS

HF_CACHE_ENV = "PARATEXT_HF_CACHE"


def hf_dataset_source(
    *,
    repo: str | None = None,
    path_prefix: str = "",
    exts: tuple[str, ...] = IMAGE_EXTS,
    token: str | None = None,
    revision: str | None = None,
    cache_dir: Path | None = None,
) -> Source:
    """An imagefolder-style dataset on the Hugging Face Hub, one Sample per image.

    ``repo`` is the dataset id (``owner/name``). Leave it unset to take the id
    from the run's source argument instead, so ``--source owner/name`` works
    without rebuilding the project.

    Files are listed with ``huggingface_hub`` and pulled one at a time, which
    costs no new dependency and is the exact shape ``paratext export`` writes —
    a round trip, so a published eval set can be re-run. It does **not** read
    parquet-backed datasets; those need the ``datasets`` library and a column
    map, and are a separate adapter rather than a flag on this one.

    ``token`` reaches private datasets, and is the caller's to supply — nothing
    here reads an ambient credential or writes one down.
    """
    notices: list[str] = []
    env_cache = os.environ.get(HF_CACHE_ENV)
    root = cache_dir or (Path(env_cache) if env_cache else None)

    def _iter(source: Path, limit: int | None) -> Iterator[Sample]:
        from huggingface_hub import HfApi, hf_hub_download
        from huggingface_hub.errors import HfHubHTTPError

        repo_id = repo or str(source)
        if repo_id.count("/") != 1 or not all(repo_id.split("/")):
            raise ValueError(
                f"not a dataset id: {repo_id!r} — expected owner/name, "
                f"e.g. NationalLibraryOfScotland/index-cards-eval"
            )
        api = HfApi(token=token)
        try:
            names = api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
        except HfHubHTTPError as e:
            raise FileNotFoundError(
                f"can't read dataset {repo_id!r}: {e}. If it is private, supply a token."
            ) from e

        wanted = sorted(
            n for n in names
            if n.lower().endswith(exts) and n.startswith(path_prefix)
        )
        if not wanted:
            where = f" under {path_prefix!r}" if path_prefix else ""
            raise FileNotFoundError(
                f"no images{where} in {repo_id!r} (looked for {', '.join(exts)}). "
                f"This adapter reads imagefolder-style datasets; a parquet-backed "
                f"dataset needs a different one."
            )
        # An imagefolder dataset keeps everything under one directory, and
        # carrying that into every id just makes them longer. Drop it only when
        # it is shared by all of them, so a nested layout keeps its structure.
        dirs = {n.rsplit("/", 1)[0] if "/" in n else "" for n in wanted}
        shared = f"{dirs.pop()}/" if len(dirs) == 1 and dirs != {""} else ""

        if limit is not None:
            wanted = wanted[:limit]

        for name in wanted:
            local = hf_hub_download(
                repo_id, name, repo_type="dataset", revision=revision,
                token=token, cache_dir=str(root) if root else None,
            )
            img = Image.open(local).convert("RGB")
            # The id has to survive a nested layout without colliding, so keep
            # what's left of the path and drop only the extension.
            stem = name[len(shared):]
            sample_id = stem[: -len(Path(stem).suffix)].replace("/", "__")
            yield Sample(
                id=sample_id,
                images=[img],
                metadata={"image_path": str(Path(local).resolve()),
                          "hf_repo": repo_id, "hf_file": name},
            )

    return Source(
        iter_samples=_iter,
        materialise=default_materialise,
        notices=notices,
        config={
            "kind": "hf-dataset",
            "repo": repo,
            "path_prefix": path_prefix,
            "revision": revision,
            "exts": list(exts),
            "token": bool(token),   # never the value
        },
    )
