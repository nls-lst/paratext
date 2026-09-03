---
id: PTX-32
title: Add a configurable output budget and provider extra-body passthrough
status: done
horizon: now
flow: clear
labels:
  - packaging
created: '2026-08-19'
updated: '2026-08-19'
---

Different providers expose different knobs, and a fixed output budget truncates long extractions on some models while wasting tokens on others.

## Notes

- Output budget configurable; provider-specific parameters passed through via extra_body.
