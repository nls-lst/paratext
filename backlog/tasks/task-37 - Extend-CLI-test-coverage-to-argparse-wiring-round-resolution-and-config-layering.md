---
id: TASK-37
title: >-
  Extend CLI test coverage to argparse wiring, round resolution and config
  layering
status: To Do
assignee: []
created_date: '2026-09-02 17:56'
labels:
  - testing
  - cli
milestone: m-6
dependencies: []
priority: high
type: task
ordinal: 37000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
tests/test_cli.py now exists and covers -v/--version plus a guard that paratext.__version__ matches installed metadata, since __init__.py and pyproject.toml declare the version separately. The parts that motivated the task are still uncovered: argparse wiring, _resolve_round, and config layering. These are where a change breaks a user without breaking a test.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 argparse wiring covered, including that an unknown project explains the environment problem
- [ ] #2 _resolve_round covered across explicit, latest and missing-round cases
- [ ] #3 Config layering covered: packaged example, project config, environment
<!-- AC:END -->
