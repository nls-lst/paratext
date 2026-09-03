---
id: TASK-45
title: Add paratext bench
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - evaluation
  - cli
dependencies: []
priority: low
type: feature
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Once a gold round is exported, the obvious next question is how a smaller or cheaper model scores against it. That is a loop worth having in the tool rather than in a script beside it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `paratext bench` runs a model over an exported dataset and scores it against gold
- [ ] #2 Output is comparable across models and rounds
<!-- AC:END -->
