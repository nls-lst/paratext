---
id: PTX-29
title: Rename the distribution to paratext-cli and publish to PyPI
status: done
horizon: now
flow: clear
labels:
  - packaging
created: '2026-08-12'
updated: '2026-08-12'
---

The PyPI name `paratext` belongs to an unrelated package, so the distribution needs a different name while the import package and console script stay as they are.

## Notes

- Distribution renamed to paratext-cli; `import paratext` and the `paratext` command are unchanged. Published the same day via PyPI trusted publishing, with release docs and a publish workflow.
