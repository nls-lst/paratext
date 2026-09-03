---
id: PTX-59
title: Clearer install and first-run path in the README
status: done
horizon: now
flow: clear
labels:
  - docs
created: '2026-09-03'
updated: '2026-09-03'
---

Read as a newcomer, the README had three obstacles. The one prerequisite that
cannot be guessed — a model endpoint — was described only as "an OpenAI-compatible
endpoint", with no copy-pasteable example, while `paratext run` was the third
command in the quickstart and would fail without one. The first run was
`--limit 50`, a large spend before you have read a single output. And "Where
projects are found" was twenty lines of environment troubleshooting in the middle
of the happy path, opening with the problem and conceding only at the end that it
usually just works — which, since the .venv hand-over landed, it does.

Now: a working two-line hosted config, `--limit 5` for the first run, a note that
`paratext new` writes the config, and the discovery section inverted to three
lines with the mechanism folded into a details block.
