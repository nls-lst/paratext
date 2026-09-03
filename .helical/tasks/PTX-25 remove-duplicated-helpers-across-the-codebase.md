---
id: PTX-25
title: Remove duplicated helpers across the codebase
status: done
horizon: now
flow: clear
created: '2026-07-27'
updated: '2026-07-27'
---

The split from paratext-nls left copies of the same helper in projects and in the review server, which drift apart silently.

## Notes

- Single humanise() shared between projects and the review server, image_source reusing packaging.default_materialise, one config template read from the packaged example.toml, and Counter for the excluded/skipped tallies.
