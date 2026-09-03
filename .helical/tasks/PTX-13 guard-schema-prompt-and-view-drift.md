---
id: PTX-13
title: Guard schema, prompt and view drift
status: done
horizon: now
flow: clear
created: '2026-07-09'
updated: '2026-07-09'
---

A field can be added to the schema, missed in the prompt, and silently absent from the view — three files that must agree and nothing checking that they do.

## Notes

- audit_project added to catch the drift, the scaffolder now seeds a drift-guard test, and the discipline is documented in the README.
