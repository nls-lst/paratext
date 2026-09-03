---
id: TASK-11
title: Make paratext new self-installing
status: Done
assignee: []
created_date: '2026-07-01 12:00'
updated_date: '2026-07-01 12:00'
labels:
  - backfill
  - cli
milestone: m-0
dependencies: []
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A scaffolded project that does not appear in the entry-point registry until the user runs two more commands is a scaffold that half-works by default.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
`paratext new` registers the entry point and runs uv sync automatically, with --no-install to opt out. Offers to write the project config block.
<!-- SECTION:FINAL_SUMMARY:END -->
