---
id: TASK-30
title: Make project discovery work from any environment
status: Done
assignee: []
created_date: '2026-08-12 12:00'
updated_date: '2026-08-12 12:00'
labels:
  - backfill
  - cli
milestone: m-4
dependencies: []
type: bug
ordinal: 30000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Projects are found per environment through entry points, and a bare `paratext` invocation was resolving to the wrong interpreter and reporting a confusing argparse error for an unknown project.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The CLI hands over to a project's .venv so a bare `paratext` finds its projects. Unknown projects point at `uv run paratext` instead of argparse's invalid-choice message. The scaffolder nests into the installed package and bootstraps an empty directory.
<!-- SECTION:FINAL_SUMMARY:END -->
