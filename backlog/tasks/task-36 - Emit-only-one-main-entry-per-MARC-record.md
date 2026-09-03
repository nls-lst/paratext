---
id: TASK-36
title: Emit only one main entry per MARC record
status: Done
assignee: []
created_date: '2026-09-02 12:00'
updated_date: '2026-09-02 12:00'
labels:
  - backfill
  - marc
  - export
milestone: m-5
dependencies: []
type: bug
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Records were being emitted with more than one 1xx field, which is invalid MARC and was caught by cataloguers in review.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
A single main entry per record enforced at export.
<!-- SECTION:FINAL_SUMMARY:END -->
