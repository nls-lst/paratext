---
id: TASK-46
title: 'Review UI polish: flagged stat key, score badge, and verdict toggles'
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - ui
milestone: m-8
dependencies: []
priority: low
type: chore
ordinal: 46000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Three small items that have been carried for a while: the flagged_marc stat key is schema-specific in a framework that is not, the deterministic-score badge is unstyled, and the verdict toggles do not report their state to assistive technology.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 flagged_marc renamed to a schema-agnostic flagged
- [ ] #2 Deterministic-score badge styled with Oat
- [ ] #3 aria-pressed set on the verdict toggles
<!-- AC:END -->
