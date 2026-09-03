---
id: PTX-56
title: 'Workshop mode: edit the prompt and schema in a shared review instance'
status: done
horizon: now
flow: clear
labels:
  - workshop
  - schema
  - ui
  - cli
created: '2026-09-03'
updated: '2026-09-03'
---

`paratext review --workshop DIR` makes one server usable by a room. Each browser
gets its own workspace — prompt, fields, rounds and verdicts — keyed on a
`pt_session` cookie and seeded from the rounds being served, so nobody
overwrites anybody. A Prompt editor page edits the prompt and the fields and
runs a handful of items against the configured endpoint, backgrounded and polled
so there is a progress bar.

Fields are data, not Python: `paratext.workshop.build_schema` builds a Pydantic
model per run from a field list, and the type is inferred from the field name
unless set. The inference deliberately ignores a bare "number" — a call number,
accession number, ISBN or edition is text, and guessing integer breaks a run.

Caps: 8 items a run, 40 runs a session, one at a time, counted per session.
Start over throws away the caller's own workspace. None of it is reachable
without the flag, and the server stays single-tenant otherwise.

Deliberately undocumented in the README: it is a demo and teaching mode, and the
README should stay a golden path for a new reader.

Shipped 0.4.0–0.4.3.
