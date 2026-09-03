---
id: TASK-6
title: Rename init to new and document every CLI flag
status: Done
assignee: []
created_date: '2026-06-28 12:00'
updated_date: '2026-06-28 12:00'
labels:
  - backfill
  - cli
milestone: m-0
dependencies: []
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`init` reads as initialising the tool rather than creating a project, and undocumented flags make the CLI unusable without reading the source.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
`paratext new` (with `init` kept as an alias), seeded schema fields, help text on every flag, a help command, bare-command usage, and a README flag reference.
<!-- SECTION:FINAL_SUMMARY:END -->
