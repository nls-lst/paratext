"""Config resolution for the paratext CLI.

A single project-local ``paratext.toml`` holds the defaults; CLI flags and
``PARATEXT_*`` environment variables override them. Precedence (highest
first):

    1. CLI flags
    2. ``PARATEXT_*`` environment variables (e.g. ``PARATEXT_BASE_URL``)
    3. ``./paratext.toml`` ``[project.<name>]`` section
    4. ``./paratext.toml`` top-level keys
    5. Hardcoded defaults in :mod:`paratext.cli`

Env vars are kept alongside the file because they are the idiomatic way to
configure the CLI inside a container.

**Config keys are kebab-case** (``base-url``), matching the CLI flag that sets
them (``--base-url``). ``_kebab_to_snake`` also accepts snake_case so an older
config keeps working, but that is leniency, not a second convention — document
and generate kebab-case only.

Example ``paratext.toml``::

    base-url = "http://localhost:8000/v1"
    model    = "user.Qwen3.6-35B-A3B-GGUF-Q8_0"

    [project.index-cards]
    source = "/datasets/index-cards/eval-samples"
    output = "output/index-cards.jsonl"
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ENV_PREFIX = "PARATEXT_"


def config_template() -> str:
    """The starter config `paratext config` seeds into a fresh paratext.toml.

    Read from the packaged ``paratext.example.toml`` — the repo-root file,
    symlinked into the package — so the example a reader finds in the repo and
    the file the CLI actually writes cannot drift apart.
    """
    from importlib.resources import files

    return (files("paratext") / "paratext.example.toml").read_text(encoding="utf-8")

# Keys the loader will recognise. Anything else in TOML/env is ignored so a
# stray field doesn't accidentally crash the CLI.
RECOGNISED = (
    "project",
    "source",
    "output",
    "review_out",
    "review_port",
    "model",
    "base_url",
    "api_key",
    "limit",
    "no_structured",
    "skip_preflight",
)


def local_config_path(start: Path | None = None) -> Path:
    return (start or Path.cwd()) / "paratext.toml"


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _kebab_to_snake(d: dict) -> dict:
    """Config is written kebab-case; Python wants snake_case. Snake_case input
    passes through unchanged, so an older config still loads."""
    return {k.replace("-", "_"): v for k, v in d.items()}


def _merge_layer(base: dict, layer: dict, project: str | None) -> None:
    """Apply ``layer`` (a parsed TOML dict) on top of ``base``.

    Top-level keys apply to all projects; ``[project.<name>]`` overlays them
    for that specific project.
    """
    flat = _kebab_to_snake({k: v for k, v in layer.items() if k != "project"})
    for k, v in flat.items():
        if k in RECOGNISED:
            base[k] = v
    if project and isinstance(layer.get("project"), dict):
        section = layer["project"].get(project)
        if isinstance(section, dict):
            for k, v in _kebab_to_snake(section).items():
                if k in RECOGNISED:
                    base[k] = v


def load_defaults(project: str | None) -> dict:
    """Return resolved defaults for the given project (excluding CLI flags).

    Reads ``./paratext.toml`` then overlays environment variables. CLI flags
    are layered on top by argparse itself (``set_defaults`` + parse).
    """
    out: dict = {}
    _merge_layer(out, _load_toml(local_config_path()), project)

    # Environment variables: PARATEXT_BASE_URL, PARATEXT_MODEL, etc.
    for key in RECOGNISED:
        env_key = ENV_PREFIX + key.upper()
        if env_key in os.environ:
            out[key] = os.environ[env_key]

    return out


def env_or(key: str) -> str | None:
    """Return the ``PARATEXT_<KEY>`` environment variable, or None."""
    return os.environ.get(ENV_PREFIX + key.upper())


def load_table(section: str) -> dict:
    """Return a top-level ``[section]`` table (kebab→snake keys), or empty."""
    t = _load_toml(local_config_path()).get(section)
    return _kebab_to_snake(t) if isinstance(t, dict) else {}


def load_project_section(project: str, section: str) -> dict:
    """Return a nested ``[project.<name>.<section>]`` table (kebab→snake keys).

    Used for feature-specific config (e.g. ``export``) that has its own key
    namespace rather than the flat RECOGNISED set. Empty dict if absent.
    """
    toml = _load_toml(local_config_path())
    projects = toml.get("project")
    if not isinstance(projects, dict):
        return {}
    proj = projects.get(project)
    if not isinstance(proj, dict):
        return {}
    sub = proj.get(section)
    return _kebab_to_snake(sub) if isinstance(sub, dict) else {}


def coerce_paths(d: dict) -> dict:
    """Convert string source/output values to Path objects."""
    for key in ("source", "output", "review_out"):
        if key in d and isinstance(d[key], str):
            d[key] = Path(d[key])
    for key in ("limit", "review_port"):
        if key in d and isinstance(d[key], str):
            d[key] = int(d[key])
    for key in ("no_structured", "skip_preflight"):
        if key in d and isinstance(d[key], str):
            d[key] = d[key].lower() in ("1", "true", "yes", "on")
    return d
