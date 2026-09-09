---
id: PTX-40
title: Fix cross-batch accumulation overwriting metadata.jsonl
status: todo
horizon: next
flow: clear
outcome: R-4
priority: med
labels:
  - export
created: '2026-09-02'
updated: '2026-09-09'
---

Exporting a second round overwrites the first round's metadata.jsonl, so a dataset cannot accumulate across batches.
