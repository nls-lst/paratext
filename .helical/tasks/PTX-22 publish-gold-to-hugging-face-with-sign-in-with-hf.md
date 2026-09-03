---
id: PTX-22
title: Publish gold to Hugging Face with Sign in with HF
status: done
horizon: now
flow: clear
labels:
  - export
created: '2026-07-24'
updated: '2026-07-24'
---

Publishing from the review UI should not require the reviewer to hold or paste an API token.

## Notes

- OAuth PKCE flow added. The authorisation code is delivered over BroadcastChannel because Hugging Face's COOP header severs window.opener.
