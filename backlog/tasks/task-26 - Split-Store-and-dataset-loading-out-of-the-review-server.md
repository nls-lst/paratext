---
id: TASK-26
title: Split Store and dataset loading out of the review server
status: Done
assignee: []
created_date: '2026-07-27 12:00'
updated_date: '2026-07-27 12:00'
labels:
  - backfill
  - architecture
milestone: m-1
dependencies: []
type: chore
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The review server had grown to hold its own persistence and dataset loading, which makes both untestable in isolation.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
store.py and datasets.py extracted and noted in AGENTS.md.
<!-- SECTION:FINAL_SUMMARY:END -->
