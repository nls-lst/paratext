---
id: PTX-52
title: Refuse to resume extractions made with a different prompt or model
status: done
horizon: now
flow: clear
labels:
  - cli
  - extraction
  - tests
created: '2026-09-03'
updated: '2026-09-04'
---

Resume keys on sample id, so editing `prompt.md` and re-running skipped every
sample, called the model zero times, and reported success — the run → review →
edit → re-run loop the README and docs describe silently did nothing. The round
also kept the old prompt hash, so no new round opened.

Extraction now compares the incoming prompt hash and model against the existing
file's provenance header and stops if either moved, naming both values and the
two ways forward. `--re-extract` discards the old records and redoes them;
`re-extract = true` under `[project.<name>]` makes that the default for a
collection small enough that re-running is cheap. Stopping was chosen over
re-extracting automatically so a re-run can never silently re-bill a large sweep.

Shipped 0.2.0 and 0.2.1.
