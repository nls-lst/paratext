---
id: PTX-40
title: Fix cross-batch accumulation overwriting metadata.jsonl
status: todo
horizon: next
flow: clear
priority: med
labels:
  - export
created: '2026-09-02'
updated: '2026-09-02'
---

Exporting a second round overwrites the first round's metadata.jsonl, so a dataset cannot accumulate across batches.
