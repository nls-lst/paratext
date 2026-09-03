---
id: TASK-34
title: Replace the blind margin crop with a content-aware fallback
status: Done
assignee: []
created_date: '2026-08-20 12:00'
updated_date: '2026-08-20 12:00'
labels:
  - backfill
  - cards
milestone: m-0
dependencies: []
type: enhancement
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When the detector finds nothing, cropping a fixed margin discards real content on some cards and keeps background on others.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Content-aware crop fallback; stale 'uniform crop' references cleared from the detector messages.
<!-- SECTION:FINAL_SUMMARY:END -->
