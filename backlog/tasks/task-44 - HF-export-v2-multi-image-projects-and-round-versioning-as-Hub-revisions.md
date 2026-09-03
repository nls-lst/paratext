---
id: TASK-44
title: 'HF export v2: multi-image projects and round versioning as Hub revisions'
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - export
milestone: m-7
dependencies: []
priority: low
type: feature
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The v1 export assumes one image per record and one round per dataset. Multi-image projects have no representation, and successive rounds have nowhere natural to live except separate datasets.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Multi-image projects export without losing the relationship between images and a record
- [ ] #2 Successive rounds published as Hub revisions of one dataset
<!-- AC:END -->
