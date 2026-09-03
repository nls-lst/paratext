---
id: PTX-38
title: Walk a real run from a fresh scaffold
status: done
horizon: now
flow: clear
priority: high
labels:
  - onboarding
  - cli
  - tests
created: '2026-09-02'
updated: '2026-09-03'
---

`paratext new` has been walked end to end and fixed, but a real `paratext run` from a fresh scaffold has still never been done — it needs a live endpoint. Until it has, the first thing a new user does after scaffolding is untested.

Done 2026-09-03. Walked in an empty directory: `paratext new` → `inspect` →
`paratext run --limit 3` against a live endpoint, packaged to a round and opened
in review. Repeated against a hosted endpoint (HF router) as well as a local
one. Two defects came out of it and are fixed: `paratext new` died with an
EOFError on a non-TTY stdin *after* writing files but before registering the
entry point, and the example config set `review-out`, which silently disabled
round auto-naming.
