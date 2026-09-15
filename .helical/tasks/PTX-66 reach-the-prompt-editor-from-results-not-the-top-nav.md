---
id: PTX-66
title: Reach the prompt editor from Results, not the top nav
status: done
horizon: now
flow: clear
result: Moved the link onto Results directly under the two history accordions, and flipped Prompt history above Fields so the page mirrors the editor (prompt first, fields second). Results now reads as what the last round did, then go change it. Removed the runtime nav injection entirely, along with its Oat display-layer workaround. Shipped as 0.6.4 to PyPI and the Space.
created: '2026-09-15'
updated: '2026-09-15'
---

The Prompt editor sat in the top nav, which is the review path (Rounds / Review / Results). It belongs after you have read what the last round did, not alongside the reviewing.
