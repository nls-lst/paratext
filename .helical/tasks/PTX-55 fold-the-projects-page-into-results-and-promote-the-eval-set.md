---
id: PTX-55
title: Fold the Projects page into Results and promote the eval set
status: done
horizon: now
flow: clear
labels:
  - ui
created: '2026-09-03'
updated: '2026-09-03'
---

The Projects page was never used. Everything on it was duplicated by the Fields
panel or available from `paratext inspect`, except one diagnostic: whether the
*installed* prompt still matches the round being looked at.

That diagnostic moved to Results, above the prompt history where rounds are
already being compared, and stays silent when no matching project is installed —
which is the normal case when reviewing a packaged round elsewhere. 118 lines
removed.

The eval gold set became a call-to-action button rather than a statistic in a
list, since building it is the point of reviewing.

Shipped 0.3.0.
