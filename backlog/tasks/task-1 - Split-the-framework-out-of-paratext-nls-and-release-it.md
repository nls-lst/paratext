---
id: TASK-1
title: Split the framework out of paratext-nls and release it
status: Done
assignee: []
created_date: '2026-06-28 12:00'
updated_date: '2026-06-28 12:00'
labels:
  - backfill
  - architecture
milestone: m-0
dependencies: []
type: feature
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The engine, CLI, config and plug-in contract were entangled with NLS-specific projects and data. Separating them is what makes the framework publishable at all, and forces the plug-in boundary to be real rather than notional.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Initial release of the framework: engine, CLI, config, plug-in contract, paratext.cards and paratext.sources, with a generic cards starter.
<!-- SECTION:FINAL_SUMMARY:END -->
