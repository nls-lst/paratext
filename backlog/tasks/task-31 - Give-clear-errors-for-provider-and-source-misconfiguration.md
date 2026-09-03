---
id: TASK-31
title: Give clear errors for provider and source misconfiguration
status: Done
assignee: []
created_date: '2026-08-12 12:00'
updated_date: '2026-08-12 12:00'
labels:
  - backfill
  - cli
milestone: m-4
dependencies: []
type: enhancement
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A malformed base URL or a missing source directory produced a failure far from its cause.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Base URLs trimmed of endpoint paths and given a missing scheme, preflight 4xx diagnosed, a warning raised when a provider token sits in paratext.toml rather than the environment, and a clean error for a missing or non-directory source.
<!-- SECTION:FINAL_SUMMARY:END -->
