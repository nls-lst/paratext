---
id: PTX-37
title: Extend CLI test coverage to argparse wiring, round resolution and config layering
status: todo
horizon: now
flow: clear
priority: high
labels:
  - cli
  - tests
created: '2026-09-02'
updated: '2026-09-02'
---

tests/test_cli.py now exists and covers -v/--version plus a guard that paratext.__version__ matches installed metadata, since __init__.py and pyproject.toml declare the version separately. The parts that motivated the task are still uncovered: argparse wiring, _resolve_round, and config layering. These are where a change breaks a user without breaking a test.
