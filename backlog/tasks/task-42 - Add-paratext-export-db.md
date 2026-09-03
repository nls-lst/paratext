---
id: TASK-42
title: Add paratext export --db
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - export
  - cli
milestone: m-7
dependencies: []
priority: medium
type: enhancement
ordinal: 42000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Publishing live gold currently needs a staging dance because export cannot be pointed at a database directly.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `paratext export --db <path>` reads verdicts and gold from the named database
<!-- AC:END -->
