---
id: PTX-41
title: Remove the silent hf default from --format
status: todo
horizon: next
flow: clear
priority: med
labels:
  - cli
  - export
created: '2026-09-02'
updated: '2026-09-02'
---

`--format` defaults silently to hf, so a user who meant MARC gets a Hugging Face dataset without being told. On a TTY the right behaviour is a menu; otherwise an error.
