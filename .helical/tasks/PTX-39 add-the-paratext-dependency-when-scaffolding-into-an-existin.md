---
id: PTX-39
title: Add the paratext dependency when scaffolding into an existing project
status: todo
horizon: next
flow: clear
priority: med
labels:
  - cli
  - tests
created: '2026-09-02'
updated: '2026-09-02'
---

The empty-directory bootstrap writes a pyproject declaring paratext-cli, but scaffolding into a project that already has one adds no dependency. The scaffolded audit test therefore only runs if the user happened to have paratext installed already.
