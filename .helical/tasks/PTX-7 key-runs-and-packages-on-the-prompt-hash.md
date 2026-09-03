---
id: PTX-7
title: Key runs and packages on the prompt hash
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-07-01'
updated: '2026-07-01'
---

Comparing extraction quality across prompt revisions requires knowing which prompt produced which output. Hashing the prompt makes a round self-identifying instead of relying on the operator to remember.

## Notes

- Round-aware run and package: one dataset per prompt version, keyed on the prompt hash. Later extended to key on the model as well.
