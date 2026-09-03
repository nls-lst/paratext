---
id: PTX-26
title: Split Store and dataset loading out of the review server
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-07-27'
updated: '2026-07-27'
---

The review server had grown to hold its own persistence and dataset loading, which makes both untestable in isolation.

## Notes

- store.py and datasets.py extracted and noted in AGENTS.md.
