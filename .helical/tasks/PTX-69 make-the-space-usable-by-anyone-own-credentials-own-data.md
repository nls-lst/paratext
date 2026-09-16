---
id: PTX-69
title: 'Make the Space usable by anyone: own credentials, own data'
status: done
horizon: now
flow: clear
result: 'First slice shipped as 0.7.0. hf_dataset_source lands in core (imagefolder datasets from the Hub, no new dependency, token never recorded in inspect config). Workshop runs now spend the signed-in user: bearer token per request as publishing already did, inference-api added to the OAuth scopes, PARATEXT_API_KEY secret deleted from the Space, and a notice before consent saying runs are billed to their account. Endpoint field dropped by decision — the model is pinned to Qwen3-VL-30B-A3B, so only a token is needed and the chat_template_kwargs portability problem stays out of scope. Trap found: HARDCODED_DEFAULTS uses ''EMPTY'' as a local-server key placeholder, and being truthy it made a keyless deployment look authenticated; workshop mode now reads it as unset.'
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

**Model: pinned to `Qwen/Qwen3-VL-30B-A3B-Instruct`, thinking off.** Decided
2026-09-16: this is a demo Space, so the model is not a setting. It is the A3B
(3B active) vision model at $0.000224/card and ~3s a card, and — measured — it
genuinely honours the thinking-off hint (`reasoning_tokens=0` with the flag,
identical without, meaning no reasoning either way).

**Why that hint is not portable, for whenever a model setting is wanted.**
`chat_template_kwargs` is applied by the *inference server* rendering the chat
template, not by the model. Locally llama.cpp renders it and honours the flag;
the HF router serves nothing itself and fans out to third-party providers
(featherless-ai, scaleway, deepinfra, ovhcloud, novita), each with its own API
surface. Measured three calls each on 2026-09-16:

- `Qwen3.6-27B` — **400 every time** with the flag, fine without. Its provider
  rejects unknown extra arguments outright.
- `Qwen3.6-35B-A3B` — accepts it and **silently ignores it**:
  `reasoning_tokens=64` with the flag and without, identical.

The silent case is the dangerous one — nothing errors, you just pay for
reasoning. The `Project.disable_thinking` docstring already warns of exactly
this for OpenAI/Anthropic/OpenRouter. So if the endpoint ever becomes a setting,
`runs.py` must retry without the hint on a 400, and a `reasoning_tokens` check
is worth surfacing because "accepted and ignored" is invisible today.

**Open, now that the model is pinned:** the modal may only need a token, not an
endpoint. Worth confirming before building — the original ask said "own HF token
or an endpoint", and pinning the model makes the endpoint field optional rather
than wrong.

**Consequence accepted:** a first-time visitor with no token cannot run
anything. They can still review the packaged BPL rounds, which is a reasonable
front door, but it is a deliberate change and needs designing rather than
discovering.

Also: with attendees spending their own credit, `MAX_RUNS_PER_SESSION = 40`
stops being a credit guard and can relax.
