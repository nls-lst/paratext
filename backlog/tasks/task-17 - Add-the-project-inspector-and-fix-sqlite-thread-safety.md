---
id: TASK-17
title: Add the project inspector and fix sqlite thread safety
status: Done
assignee: []
created_date: '2026-07-21 12:00'
updated_date: '2026-07-21 12:00'
labels:
  - backfill
  - ui
milestone: m-1
dependencies: []
type: bug
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Diagnosing a misconfigured project meant reading files by hand, and the review server was touching sqlite across threads.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Project inspector added (later renamed Project configuration and linked from a homepage footer), sqlite thread safety fixed, and inspect/notices/troubleshooting documented.
<!-- SECTION:FINAL_SUMMARY:END -->
