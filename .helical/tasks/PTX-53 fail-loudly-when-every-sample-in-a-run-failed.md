---
id: PTX-53
title: Fail loudly when every sample in a run failed
status: done
horizon: now
flow: clear
labels:
  - cli
created: '2026-09-03'
updated: '2026-09-03'
---

A run where every call failed printed `Packaged 0 record(s)` and `Review them:`
and exited 0 — a bad key, a wrong base-url or a model the endpoint doesn't serve
all produced a cheerful, near-silent failure. Found while pointing a fresh
install at a hosted endpoint with the wrong token.

An all-failed run now exits non-zero, names the last error and the errors file,
and packages nothing. A partial failure still completes and reports the count,
because that is a real result.

Shipped 0.2.4.
