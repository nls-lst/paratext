---
id: PTX-11
title: Make paratext new self-installing
status: done
horizon: now
flow: clear
labels:
  - cli
created: '2026-07-01'
updated: '2026-07-01'
---

A scaffolded project that does not appear in the entry-point registry until the user runs two more commands is a scaffold that half-works by default.

## Notes

- `paratext new` registers the entry point and runs uv sync automatically, with --no-install to opt out. Offers to write the project config block.
