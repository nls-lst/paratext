---
id: PTX-70
title: Give FAST subject headings the right MARC indicators
status: todo
horizon: next
flow: clear
priority: med
created: '2026-09-17'
updated: '2026-09-17'
---

A FAST heading in 650 takes second indicator 7 with $2 fast, and the URI belongs in $0. _marc_indicators in src/paratext/catalogue.py currently returns (' ', ' ') for 650 — 'no information provided' — and there is no $2 handling. Required before accepted Annif subject suggestions can reach a MARC export; see the Annif paratext-integration brief and ANF-28.
