---
id: PTX-34
title: Replace the blind margin crop with a content-aware fallback
status: done
horizon: now
flow: clear
labels:
  - index-cards
created: '2026-08-20'
updated: '2026-08-20'
---

When the detector finds nothing, cropping a fixed margin discards real content on some cards and keeps background on others.

## Notes

- Content-aware crop fallback; stale 'uniform crop' references cleared from the detector messages.
