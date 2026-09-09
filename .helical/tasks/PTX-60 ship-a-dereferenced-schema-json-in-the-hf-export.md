---
id: PTX-60
title: Ship a dereferenced schema.json in the HF export
status: todo
horizon: future
flow: clear
created: '2026-09-09'
updated: '2026-09-09'
---

Consumers must resolve Pydantic's $defs/$ref themselves; do it once here

Found by Daniel van Strien's glam-extraction-benchmark, which consumes our HF
export as its gold set. Its `nls.py` spends ~25 lines dereferencing what we ship:
`schema.json` is Pydantic's raw `model_json_schema()`, so every nested model
becomes `$defs` + `$ref` and every consumer has to resolve them.

Dereferencing once, at export, removes that from all of them. Needs a recursion
guard: our schemas are not self-referential but a user's could be.

**Do not also collapse `anyOf: [X, null]` into `X`.** The benchmark does, for a
clean type at scoring time, but the same collapsed schema is what it feeds vLLM
as `guided_json` — so a guided model is structurally forbidden from emitting
null and must invent a value for every field. Nullability is the field's licence
to say "absent" and it must survive the export.

Deferred until after the workshop.
