---
id: TASK-41
title: Remove the silent hf default from --format
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
ordinal: 41000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`--format` defaults silently to hf, so a user who meant MARC gets a Hugging Face dataset without being told. On a TTY the right behaviour is a menu; otherwise an error.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 No silent default: a menu on a TTY, an error when not interactive
- [ ] #2 Existing scripts passing --format explicitly are unaffected
<!-- AC:END -->
