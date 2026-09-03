---
id: TASK-7
title: Key runs and packages on the prompt hash
status: Done
assignee: []
created_date: '2026-07-01 12:00'
updated_date: '2026-07-01 12:00'
labels:
  - backfill
  - architecture
milestone: m-1
dependencies: []
type: enhancement
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Comparing extraction quality across prompt revisions requires knowing which prompt produced which output. Hashing the prompt makes a round self-identifying instead of relying on the operator to remember.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Round-aware run and package: one dataset per prompt version, keyed on the prompt hash. Later extended to key on the model as well.
<!-- SECTION:FINAL_SUMMARY:END -->
