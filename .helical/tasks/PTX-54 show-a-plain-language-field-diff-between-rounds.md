---
id: PTX-54
title: Show a plain-language field diff between rounds
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-09-03'
updated: '2026-09-03'
---

The Results page showed what the model scored but not what it was asked for, so
a reader new to schemas had no way to see that the fields had changed between
rounds.

A Fields panel now lists the model-output fields for the latest round and marks
what moved since the one before — added, dropped, or a changed type — as a table
rather than a +/- diff, with types worded (`string` → text, `integer` → whole
number). Silent when only one round exists. `schema_history()` and
`diff_fields()` do the work in Python so they are testable; `/api/schema` serves
them.

Shipped 0.2.2, collapsed by default in 0.2.3.
