---
id: TASK-29
title: Rename the distribution to paratext-cli and publish to PyPI
status: Done
assignee: []
created_date: '2026-08-12 12:00'
updated_date: '2026-08-12 12:00'
labels:
  - backfill
  - packaging
milestone: m-4
dependencies: []
type: chore
ordinal: 29000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The PyPI name `paratext` belongs to an unrelated package, so the distribution needs a different name while the import package and console script stay as they are.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Distribution renamed to paratext-cli; `import paratext` and the `paratext` command are unchanged. Published the same day via PyPI trusted publishing, with release docs and a publish workflow.
<!-- SECTION:FINAL_SUMMARY:END -->
