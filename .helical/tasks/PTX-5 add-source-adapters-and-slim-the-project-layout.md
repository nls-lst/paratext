---
id: PTX-5
title: Add source adapters and slim the project layout
status: done
horizon: now
flow: clear
created: '2026-06-28'
updated: '2026-06-28'
---

A project should be the smallest thing that expresses what is different about it. Everything else — how images or PDFs are loaded, how a default view is derived — belongs to the framework.

## Notes

- image_source and pdf_source adapters added, default view derived from the schema, and project.py collapsed into __init__.py. A project is now a folder holding __init__.py, schema.py and prompt.md.
