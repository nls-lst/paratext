---
id: PTX-9
title: Add carbon-aware scheduling
status: done
horizon: now
flow: clear
labels:
  - carbon
created: '2026-07-01'
updated: '2026-07-01'
---

Batch extraction has no deadline, so it can wait for cleaner grid electricity. That only works if the tool can find out what the grid is doing without the user signing up for anything.

## Notes

- `paratext carbon` and `run --green` added, with an energy-charts provider (EU, no token) and IP-geolocated region suggestion during config.
