---
id: PTX-3
title: Make the review server configurable
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-06-28'
updated: '2026-06-28'
---

The review server has to coexist with whatever else is on the host, and be reachable from off-box when it is deployed rather than run locally.

## Notes

- Configurable review-port (defaulting to 5050 to avoid ai-verify on 4000), plus --host and --db flags.
