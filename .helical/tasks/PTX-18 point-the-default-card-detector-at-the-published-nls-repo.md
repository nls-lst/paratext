---
id: PTX-18
title: Point the default card detector at the published NLS repo
status: done
horizon: now
flow: clear
result: Default detector points at the published NationalLibraryOfScotland repo; a local path remains supported. Card tooling made opt-in and the crop fallback fixed.
created: '2026-07-21'
updated: '2026-07-21'
---

The default detector weights were a local path, so the cards extra only worked on the machine that trained them.
