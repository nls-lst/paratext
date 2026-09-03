---
id: PTX-1
title: Split the framework out of paratext-nls and release it
status: done
horizon: now
flow: clear
created: '2026-06-28'
updated: '2026-06-28'
---

The engine, CLI, config and plug-in contract were entangled with NLS-specific projects and data. Separating them is what makes the framework publishable at all, and forces the plug-in boundary to be real rather than notional.

## Notes

- Initial release of the framework: engine, CLI, config, plug-in contract, paratext.cards and paratext.sources, with a generic cards starter.
