---
id: PTX-48
title: Add richer scaffolder field types for enums and lists
status: todo
horizon: future
flow: clear
priority: low
labels:
  - cli
created: '2026-09-02'
updated: '2026-09-02'
---

`entries[]` in the field prompt silently slugifies to a plain string field named entries — direct evidence that the scaffolder needs a way to express list and enum fields rather than only scalars.
