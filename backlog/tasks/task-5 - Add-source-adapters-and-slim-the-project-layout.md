---
id: TASK-5
title: Add source adapters and slim the project layout
status: Done
assignee: []
created_date: '2026-06-28 12:00'
updated_date: '2026-06-28 12:00'
labels:
  - backfill
  - architecture
milestone: m-0
dependencies: []
type: enhancement
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A project should be the smallest thing that expresses what is different about it. Everything else — how images or PDFs are loaded, how a default view is derived — belongs to the framework.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
image_source and pdf_source adapters added, default view derived from the schema, and project.py collapsed into __init__.py. A project is now a folder holding __init__.py, schema.py and prompt.md.
<!-- SECTION:FINAL_SUMMARY:END -->
