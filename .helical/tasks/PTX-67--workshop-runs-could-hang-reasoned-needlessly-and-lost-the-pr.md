---
id: PTX-67
title: Workshop runs could hang, reasoned needlessly, and lost the prompt
status: done
horizon: now
flow: clear
result: 'Shipped 0.6.5 and 0.6.6 to PyPI and the Space. Verified live: 8 of 8 cards, no failures, 32s, prompt and fields persisted across a run. The runs-remaining counter was also removed from the editor; the per-session cap still applies.'
created: '2026-09-15'
updated: '2026-09-15'
---

Three faults found during final testing on 2026-09-15, hours before the session.
All workshop-mode only; fixed across 0.6.5 and 0.6.6.

**A run could appear to hang forever.** The model ran away on some cards — the
Space log showed truncated JSON repeating a call number, and
`model hit the 8192-token output cap before finishing`. Two things turned that
into an apparent hang: no output cap for workshop runs (a runaway burned all
8192 tokens, ~85s a card against 2.9s normal), and no request timeout at all —
the OpenAI SDK defaults to a 600s read timeout with two retries, so one bad card
could hold a run for **30 minutes** behind a progress bar that never moved. Now
1024 max tokens, 90s timeout, one retry.

**Failed cards were silent.** A run that lost cards landed on a short round with
no explanation. It now stops on a warning listing the reason for each card, with
a button through to the round; a clean run still goes straight through.

**Thinking was never off.** `extract.run` builds the vLLM-dialect
`chat_template_kwargs.enable_thinking=false` hint from the project, but the
workshop path calls `call_structured` directly and skipped it — so every
workshop card had been reasoning. Verified the HF router accepts the hint rather
than rejecting it.

**The prompt did not survive a run.** Edit, run, look at Results, come back to
refine — and the editor showed the default again. `_api_workshop_save` existed
and nothing ever called it. Running is now the save.

**Card `01_…00110` is not the bug it looks like.** It carries its call number
twice — `F73 / .5 / .H85` down the edge and `F73.5.H85` at the foot — and the
model latches onto the repetition. But with a plain four-field schema it
succeeds every time in ~3s (tested four ways). The loop is triggered by a
particular prompt/schema, not the card, which makes it a teaching example rather
than a defect — the same lesson as the tracings example.

Verified live: 8 of 8 cards, no failures, 32s, prompt and fields persisted.
