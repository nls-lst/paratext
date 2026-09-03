---
id: TASK-9
title: Add carbon-aware scheduling
status: Done
assignee: []
created_date: '2026-07-01 12:00'
updated_date: '2026-07-01 12:00'
labels:
  - backfill
  - carbon
milestone: m-0
dependencies: []
type: feature
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Batch extraction has no deadline, so it can wait for cleaner grid electricity. That only works if the tool can find out what the grid is doing without the user signing up for anything.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
`paratext carbon` and `run --green` added, with an energy-charts provider (EU, no token) and IP-geolocated region suggestion during config.
<!-- SECTION:FINAL_SUMMARY:END -->
