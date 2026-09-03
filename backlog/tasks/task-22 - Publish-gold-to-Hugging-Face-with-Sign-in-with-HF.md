---
id: TASK-22
title: Publish gold to Hugging Face with Sign in with HF
status: Done
assignee: []
created_date: '2026-07-24 12:00'
updated_date: '2026-07-24 12:00'
labels:
  - backfill
  - export
milestone: m-2
dependencies: []
type: feature
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Publishing from the review UI should not require the reviewer to hold or paste an API token.
<!-- SECTION:DESCRIPTION:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
OAuth PKCE flow added. The authorisation code is delivered over BroadcastChannel because Hugging Face's COOP header severs window.opener.
<!-- SECTION:FINAL_SUMMARY:END -->
