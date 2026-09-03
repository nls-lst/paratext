---
id: PTX-2
title: Add the inbuilt review web UI
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-06-28'
updated: '2026-06-28'
---

Extraction output is unreadable as JSONL. Reviewing it needs the image and the extracted fields side by side, which means a server ships with the framework rather than beside it.

## Notes

- `paratext review` added, defaulting to a ./review root that lists all projects and detecting an already-running server.
