---
id: PTX-57
title: Install the agent guide as a skill agents can find
status: done
horizon: now
flow: clear
labels:
  - cli
  - docs
created: '2026-09-03'
updated: '2026-09-03'
---

`paratext guide` printed the agent guide, but only if you knew to ask. `paratext
skill` writes it as a SKILL.md — the guide plus trigger-heavy frontmatter — and
symlinks it into `~/.agents/skills` along with Claude Code, Codex, Pi, Gemini
and Hermes, following the pattern Omarchy uses.

Two differences from that pattern, both forced by paratext being a package
rather than a distro: it is an explicit command, because a pip install has no
business writing into `~/.claude`; and the canonical copy lives under
XDG_DATA_HOME with the agent directories linking to it, because `uv tool
upgrade` replaces the venv and a link into site-packages would dangle.

Refuses to overwrite a real directory somebody else put there, replaces a stale
link of its own, and `--remove` unlinks without deleting the copy.

Shipped 0.5.0.
