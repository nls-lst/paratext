---
id: TASK-39
title: Add the paratext dependency when scaffolding into an existing project
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - cli
  - onboarding
milestone: m-6
dependencies: []
priority: medium
type: bug
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The empty-directory bootstrap writes a pyproject declaring paratext-cli, but scaffolding into a project that already has one adds no dependency. The scaffolded audit test therefore only runs if the user happened to have paratext installed already.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Scaffolding into an existing project offers to add the paratext-cli dependency
- [ ] #2 The scaffolded audit test passes on a project that did not previously depend on paratext
<!-- AC:END -->
