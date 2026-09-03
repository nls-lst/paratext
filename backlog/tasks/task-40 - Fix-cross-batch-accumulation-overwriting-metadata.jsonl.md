---
id: TASK-40
title: Fix cross-batch accumulation overwriting metadata.jsonl
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - export
milestone: m-7
dependencies: []
priority: medium
type: bug
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Exporting a second round overwrites the first round's metadata.jsonl, so a dataset cannot accumulate across batches.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A second export into the same dataset appends rather than overwriting
- [ ] #2 Existing single-round exports are unaffected
<!-- AC:END -->
