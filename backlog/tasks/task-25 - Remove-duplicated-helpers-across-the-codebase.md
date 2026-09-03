---
id: TASK-25
title: Remove duplicated helpers across the codebase
status: Done
assignee: []
created_date: '2026-07-27 12:00'
updated_date: '2026-07-27 12:00'
labels:
  - backfill
  - chore
milestone: m-0
dependencies: []
type: chore
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The split from paratext-nls left copies of the same helper in projects and in the review server, which drift apart silently.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Single humanise() shared between projects and the review server, image_source reusing packaging.default_materialise, one config template read from the packaged example.toml, and Counter for the excluded/skipped tallies.
<!-- SECTION:FINAL_SUMMARY:END -->
