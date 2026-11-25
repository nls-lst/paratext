"""The `Source` contract shared by every input adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from ..projects import Sample


@dataclass
class Source:
    """An extraction iterator paired with its packaging image-materialiser.

    ``notices`` collects human-readable degradations noticed during iteration
    (e.g. a requested crop that fell back). `extract` drains it into the run
    summary so a silently-degraded run can't look like a clean one.
    """

    iter_samples: Callable[[Path, int | None], Iterator[Sample]]
    materialise: Callable[[dict, Path, int], list[str]]
    notices: list[str] = field(default_factory=list)
    # What this adapter was constructed with, for `paratext inspect` — the
    # preprocessing a project applies is otherwise invisible without reading its
    # source. Descriptive only; nothing reads it back to make decisions.
    config: dict = field(default_factory=dict)
