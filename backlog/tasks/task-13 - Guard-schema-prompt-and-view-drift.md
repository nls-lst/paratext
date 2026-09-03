---
id: TASK-13
title: 'Guard schema, prompt and view drift'
status: Done
assignee: []
created_date: '2026-07-09 12:00'
updated_date: '2026-07-09 12:00'
labels:
  - backfill
  - architecture
milestone: m-0
dependencies: []
type: feature
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A field can be added to the schema, missed in the prompt, and silently absent from the view — three files that must agree and nothing checking that they do.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
audit_project added to catch the drift, the scaffolder now seeds a drift-guard test, and the discipline is documented in the README.
<!-- SECTION:FINAL_SUMMARY:END -->
