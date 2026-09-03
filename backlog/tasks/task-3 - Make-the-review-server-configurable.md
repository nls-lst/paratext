---
id: TASK-3
title: Make the review server configurable
status: Done
assignee: []
created_date: '2026-06-28 12:00'
updated_date: '2026-06-28 12:00'
labels:
  - backfill
  - ui
milestone: m-1
dependencies: []
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The review server has to coexist with whatever else is on the host, and be reachable from off-box when it is deployed rather than run locally.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Configurable review-port (defaulting to 5050 to avoid ai-verify on 4000), plus --host and --db flags.
<!-- SECTION:FINAL_SUMMARY:END -->
