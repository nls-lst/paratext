"""Install paratext's agent guide as a skill the local coding agents can find.

`paratext guide` already prints the guide; this puts the same content where
agents look for it without being asked. The canonical copy lives in a stable
data directory, and each agent's skills directory gets a symlink to it — so
upgrading paratext never leaves a dangling link into a replaced venv.
"""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path

SKILL_NAME = "paratext"

# The description is what a harness matches on, so it names the triggers rather
# than describing the package.
FRONTMATTER = """---
name: paratext
description: >
  Use when working with paratext — extracting metadata from digitised library or
  archive collections with a multimodal model, or reviewing the results.
  Triggers: paratext, paratext.toml, `paratext run`/`extract`/`package`/`review`/
  `export`/`inspect`/`new`, a paratext project (prompt.md + schema.py +
  PROJECT), the paratext.projects entry-point group, extraction rounds, review
  datasets, gold/eval sets, or adding a source adapter or export format.
---

"""

# Where the common agents look. Vendor-neutral ~/.agents/skills first.
AGENT_SKILL_DIRS = (
    Path(".agents/skills"),
    Path(".claude/skills"),
    Path(".codex/skills"),
    Path(".pi/agent/skills"),
    Path(".gemini/config/skills"),
    Path(".hermes/skills"),
)


def skill_text() -> str:
    """The SKILL.md body: frontmatter plus the packaged agent guide."""
    guide = (files("paratext") / "AGENTS.md").read_text(encoding="utf-8")
    return FRONTMATTER + guide


def canonical_dir() -> Path:
    """A stable home for the skill, independent of the venv paratext lives in."""
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "paratext" / "skills" / SKILL_NAME


def write_skill(dest: Path) -> Path:
    """Write SKILL.md into `dest`, returning the file path."""
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "SKILL.md"
    path.write_text(skill_text(), encoding="utf-8")
    return path


def _link(target: Path, link: Path) -> str:
    """Point `link` at `target`. Returns what happened, for reporting."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return "already linked"
        link.unlink()
    elif link.exists():
        return "skipped — a real directory is already there"
    try:
        link.symlink_to(target, target_is_directory=True)
        return "linked"
    except OSError as e:                      # Windows without privileges, odd mounts
        shutil.copytree(target, link, dirs_exist_ok=True)
        return f"copied ({e.__class__.__name__})"


def install(home: Path | None = None) -> tuple[Path, dict[str, str]]:
    """Write the skill and link it into every agent directory. Returns the
    canonical path and what happened for each."""
    home = home or Path.home()
    canonical = canonical_dir()
    write_skill(canonical)
    results = {
        str(rel): _link(canonical, home / rel / SKILL_NAME) for rel in AGENT_SKILL_DIRS
    }
    return canonical, results


def uninstall(home: Path | None = None) -> dict[str, str]:
    """Remove the links, leaving the canonical copy alone."""
    home = home or Path.home()
    out = {}
    for rel in AGENT_SKILL_DIRS:
        link = home / rel / SKILL_NAME
        if link.is_symlink():
            link.unlink()
            out[str(rel)] = "removed"
        elif link.is_dir():
            out[str(rel)] = "left alone — not a link"
        else:
            out[str(rel)] = "not installed"
    return out
