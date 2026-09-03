---
id: PTX-20
title: Move the review UI onto Oat
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-07-23'
updated: '2026-07-23'
---

The review UI had accumulated custom CSS duplicating what Oat already provides, and in places fighting it. Auditing every rule against Oat's own components is cheaper than maintaining a parallel design system.

## Notes

- Custom pill, entry-row, muted and box styling replaced by Oat's .badge, .card, .text-light, .vstack, semantic dialog, and pre/code. Two Oat bugs worked around: the bundled switch omits appearance:none, and table input styling painted over the skip switch.
