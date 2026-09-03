---
id: PTX-21
title: Render entries as tables, read-only and editable
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-07-24'
updated: '2026-07-24'
---

Entries are tabular data and were being shown as stacked fields, which makes comparing rows across a record impossible.

## Notes

- Read-only and editable entry tables matching each other, with autogrowing cells. table-layout:fixed was tried and reverted — it cramped the editor. Collapsed and auxiliary fields are omitted from the eval editor.
