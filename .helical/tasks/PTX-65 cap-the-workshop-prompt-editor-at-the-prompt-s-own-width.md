---
id: PTX-65
title: 'Cap the workshop prompt editor at the prompt''s own width'
status: done
horizon: now
flow: clear
result: 'max-width:82ch on the textarea, matching the page''s existing caps (44rem description, 24rem progress bar). Rejected reflowing the prompt to soft-wrap instead: the prompt is diffed between rounds, and reflowed paragraphs would make a one-word change light up a whole line. Shipped as 0.6.3 to PyPI and the Space. Version bump needs BOTH pyproject and paratext.__version__ — test_version_matches_package_metadata catches it, and did.'
created: '2026-09-15'
updated: '2026-09-15'
---

The Prompt editor's textarea was width:100%, but the seeded prompt is hard-wrapped at 79 characters or less (most lines 72-76). On a wide screen the box ran far past where the text stopped, so the hard returns read as ragged breaks rather than deliberate wrapping.
