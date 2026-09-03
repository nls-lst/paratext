---
id: PTX-41
title: Remove the silent hf default from --format
status: todo
horizon: next
flow: blocked
blocker: 'Needs a decision: does a non-interactive export keep defaulting to hf, or error? Erroring breaks existing scripts.'
priority: med
labels:
  - cli
  - export
created: '2026-09-02'
updated: '2026-09-03'
---

`--format` defaults silently to hf, so a user who meant MARC gets a Hugging Face dataset without being told. On a TTY the right behaviour is a menu; otherwise an error.

Half of this is already built (checked 2026-09-03): `_pick_format` shows a
numbered menu on a TTY, so an interactive user is asked rather than defaulted.
What remains is only the non-TTY path, which returns `hf` — and its docstring
says that is deliberate back-compat for scripts and CI. So the task is now a
decision, not an implementation: keep the silent default for non-interactive
use, or error and require an explicit `--format`, which would break any existing
script that relies on it.
