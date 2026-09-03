---
id: TASK-21
title: 'Render entries as tables, read-only and editable'
status: Done
assignee: []
created_date: '2026-07-24 12:00'
updated_date: '2026-07-24 12:00'
labels:
  - backfill
  - ui
milestone: m-3
dependencies: []
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Entries are tabular data and were being shown as stacked fields, which makes comparing rows across a record impossible.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Read-only and editable entry tables matching each other, with autogrowing cells. table-layout:fixed was tried and reverted — it cramped the editor. Collapsed and auxiliary fields are omitted from the eval editor.
<!-- SECTION:FINAL_SUMMARY:END -->
