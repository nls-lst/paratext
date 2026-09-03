---
id: PTX-17
title: Add the project inspector and fix sqlite thread safety
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-07-21'
updated: '2026-07-21'
---

Diagnosing a misconfigured project meant reading files by hand, and the review server was touching sqlite across threads.

## Notes

- Project inspector added (later renamed Project configuration and linked from a homepage footer), sqlite thread safety fixed, and inspect/notices/troubleshooting documented.
