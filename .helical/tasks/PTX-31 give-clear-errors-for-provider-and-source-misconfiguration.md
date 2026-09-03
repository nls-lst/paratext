---
id: PTX-31
title: Give clear errors for provider and source misconfiguration
status: done
horizon: now
flow: clear
labels:
  - cli
  - packaging
created: '2026-08-12'
updated: '2026-08-12'
---

A malformed base URL or a missing source directory produced a failure far from its cause.

## Notes

- Base URLs trimmed of endpoint paths and given a missing scheme, preflight 4xx diagnosed, a warning raised when a provider token sits in paratext.toml rather than the environment, and a clean error for a missing or non-directory source.
