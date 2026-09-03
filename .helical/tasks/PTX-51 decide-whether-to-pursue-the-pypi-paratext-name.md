---
id: PTX-51
title: Decide whether to pursue the PyPI paratext name
status: todo
horizon: future
flow: clear
priority: low
labels:
  - packaging
created: '2026-09-02'
updated: '2026-09-02'
---

The PyPI name paratext holds a stranger's 1 KB empty placeholder — no summary, licence, URL, dependencies or console scripts — which made a real user's `uv tool install paratext` fail. We ship as paratext-cli instead and nothing depends on changing that.

Options are a PEP 541 claim (an empty placeholder is a decent 'not functional' case, though it is weeks old rather than dormant), emailing the owner for a transfer, or leaving it. Low priority precisely because the workaround is already published.
