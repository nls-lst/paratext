---
id: TASK-51
title: Decide whether to pursue the PyPI paratext name
status: To Do
assignee: []
created_date: '2026-09-02 18:13'
labels:
  - packaging
dependencies: []
priority: low
type: spike
ordinal: 51000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The PyPI name paratext holds a stranger's 1 KB empty placeholder — no summary, licence, URL, dependencies or console scripts — which made a real user's `uv tool install paratext` fail. We ship as paratext-cli instead and nothing depends on changing that.

Options are a PEP 541 claim (an empty placeholder is a decent 'not functional' case, though it is weeks old rather than dormant), emailing the owner for a transfer, or leaving it. Low priority precisely because the workaround is already published.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A decision recorded, or the question closed as not worth pursuing
<!-- AC:END -->
