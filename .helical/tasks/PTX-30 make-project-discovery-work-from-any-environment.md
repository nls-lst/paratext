---
id: PTX-30
title: Make project discovery work from any environment
status: done
horizon: now
flow: clear
labels:
  - cli
  - packaging
created: '2026-08-12'
updated: '2026-08-12'
---

Projects are found per environment through entry points, and a bare `paratext` invocation was resolving to the wrong interpreter and reporting a confusing argparse error for an unknown project.

## Notes

- The CLI hands over to a project's .venv so a bare `paratext` finds its projects. Unknown projects point at `uv run paratext` instead of argparse's invalid-choice message. The scaffolder nests into the installed package and bootstraps an empty directory.
