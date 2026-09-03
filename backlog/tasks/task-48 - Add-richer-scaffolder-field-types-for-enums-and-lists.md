---
id: TASK-48
title: Add richer scaffolder field types for enums and lists
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - cli
  - onboarding
dependencies: []
priority: low
type: enhancement
ordinal: 48000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`entries[]` in the field prompt silently slugifies to a plain string field named entries — direct evidence that the scaffolder needs a way to express list and enum fields rather than only scalars.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 List and enum fields expressible when scaffolding
- [ ] #2 A field spec that cannot be parsed is rejected rather than silently slugified
<!-- AC:END -->
