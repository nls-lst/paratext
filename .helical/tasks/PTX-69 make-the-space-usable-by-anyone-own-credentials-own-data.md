---
id: PTX-69
title: 'Make the Space usable by anyone: own credentials, own data'
status: todo
horizon: now
flow: clear
created: '2026-09-16'
updated: '2026-09-16'
---

After the 2026-09-15 workshop went well — attendees published their own eval
sets to the Hub — the Space should stop being an NLS demo and become something
anyone can use. Three parts, plus a decision already taken.

**Decided: no fork.** The split already exists in the right place —
`nls-lst/paratext` is the framework, `mikegsaunders/paratext-space` the
deployment (Dockerfile, curated cards, config). A third repo forking the
framework would mean two copies to maintain and would cost the PyPI channel that
delivered eight fixes to the Space during workshop prep. All three features land
on extension points core already has, so the divergence is additive.

**1. Bring your own credentials.** Remove `PARATEXT_API_KEY` (Mike's account)
from the Space. `review/hf_oauth.py` already runs Authorization-Code-with-PKCE
for *export*, and its docstring states the goal: the token is never stored
server-side, the browser holds it in sessionStorage and sends it per request.
Extend the same flow to cover inference — an HF token works directly as the HF
router key. A pasted token or custom endpoint is the fallback; it must live in
sessionStorage and travel per-request, never written to session state (sessions
persist to /tmp) and never logged.

**2. Point it at your own data.** An `hf_dataset_source` alongside `image_source`
and `pdf_source` in `paratext/sources.py`. This is the piece with value well
beyond the Space — pointing paratext at a Hub dataset is what lets another
institution use it at all, and it is what Daniel's shared-evaluations slide
assumes. Starting here.

**3. A settings modal** for endpoint, model, and sign-in-or-token.

**Notice on sign-in:** signing in means the prompt editor spends *their*
inference, and the login must say so plainly before they authorise.

**Model: keep `Qwen/Qwen3-VL-30B-A3B-Instruct` for the Space — on latency, not
quality.** Qwen3.6-35B-A3B is the framework's model and reads cards correctly:
with the Space's real prompt it returned `Howe, Mark Antony De Wolfe, 1864-`,
transcribed as printed. An earlier result suggesting it normalised names was an
artefact of testing with a bare one-line prompt carrying no transcription rule.

What rules it out for the Space is cost of time, not accuracy: **30.8s a card
against ~3s**, so an eight-card run would take about four minutes with somebody
watching. It also needs a 4096-token cap, because `enable_thinking: false` is
**not honoured** for it on the router — at the workshop's 1024 cap it spent the
entire budget on reasoning and returned nothing. Both models are A3B.

**Blocker found while testing: the thinking-off hint is not portable.**
`Qwen3.6-27B` returns 400 for `extra arguments: {"chat_template_kwargs":
{"enable_thinking":false}}`. We hardcoded that in `runs.py` yesterday, so the
moment someone points the Space at their own endpoint it can fail every card.
Must be sent defensively — retry without it on a 400, or make it a setting —
before BYO-endpoint ships.

**Consequence accepted:** a first-time visitor with no token cannot run
anything. They can still review the packaged BPL rounds, which is a reasonable
front door, but it is a deliberate change and needs designing rather than
discovering.

Also: with attendees spending their own credit, `MAX_RUNS_PER_SESSION = 40`
stops being a credit guard and can relax.
