---
id: TASK-32
title: Add a configurable output budget and provider extra-body passthrough
status: Done
assignee: []
created_date: '2026-08-19 12:00'
updated_date: '2026-08-19 12:00'
labels:
  - backfill
  - engine
milestone: m-4
dependencies: []
type: enhancement
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Different providers expose different knobs, and a fixed output budget truncates long extractions on some models while wasting tokens on others.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Output budget configurable; provider-specific parameters passed through via extra_body.
<!-- SECTION:FINAL_SUMMARY:END -->
