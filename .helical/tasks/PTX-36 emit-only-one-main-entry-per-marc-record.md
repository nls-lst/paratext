---
id: PTX-36
title: Emit only one main entry per MARC record
status: done
horizon: now
flow: clear
labels:
  - export
  - marc
created: '2026-09-02'
updated: '2026-09-02'
---

Records were being emitted with more than one 1xx field, which is invalid MARC and was caught by cataloguers in review.

## Notes

- A single main entry per record enforced at export.
