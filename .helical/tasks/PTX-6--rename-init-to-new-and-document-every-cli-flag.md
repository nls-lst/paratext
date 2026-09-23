---
id: PTX-6
title: Rename init to new and document every CLI flag
status: done
horizon: now
flow: clear
outcome: R-4
result: '`paratext new` (with `init` kept as an alias), seeded schema fields, help text on every flag, a help command, bare-command usage, and a README flag reference.'
created: '2026-06-28'
updated: '2026-09-09'
---

`init` reads as initialising the tool rather than creating a project, and undocumented flags make the CLI unusable without reading the source.
