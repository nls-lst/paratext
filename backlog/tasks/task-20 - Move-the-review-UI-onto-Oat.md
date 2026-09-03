---
id: TASK-20
title: Move the review UI onto Oat
status: Done
assignee: []
created_date: '2026-07-23 12:00'
updated_date: '2026-07-23 12:00'
labels:
  - backfill
  - ui
milestone: m-3
dependencies: []
type: chore
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The review UI had accumulated custom CSS duplicating what Oat already provides, and in places fighting it. Auditing every rule against Oat's own components is cheaper than maintaining a parallel design system.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Custom pill, entry-row, muted and box styling replaced by Oat's .badge, .card, .text-light, .vstack, semantic dialog, and pre/code. Two Oat bugs worked around: the bundled switch omits appearance:none, and table input styling painted over the skip switch.
<!-- SECTION:FINAL_SUMMARY:END -->
