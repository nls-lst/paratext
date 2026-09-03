---
id: TASK-18
title: Point the default card detector at the published NLS repo
status: Done
assignee: []
created_date: '2026-07-21 12:00'
updated_date: '2026-07-21 12:00'
labels:
  - backfill
  - cards
milestone: m-0
dependencies: []
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The default detector weights were a local path, so the cards extra only worked on the machine that trained them.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Default detector points at the published NationalLibraryOfScotland repo; a local path remains supported. Card tooling made opt-in and the crop fallback fixed.
<!-- SECTION:FINAL_SUMMARY:END -->
