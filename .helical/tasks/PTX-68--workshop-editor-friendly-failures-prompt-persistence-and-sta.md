---
id: PTX-68
title: 'Workshop editor: friendly failures, prompt persistence, and Start over'
status: done
horizon: now
flow: clear
result: 'Shipped 0.6.7 and 0.6.8. Verified live on the Space at 0.6.8: 4-card run, prompt persisted, and the friendly message appearing for a real runaway. Also caught that 0.6.7 and 0.6.8 had silently failed to deploy — a chained sed/commit/push stopped on a failed commit while the HF upload ran anyway, and RUNNING plus a matching repo sha both looked green. Verify a Space by /api/projects entry_point.version instead.'
created: '2026-09-15'
updated: '2026-09-15'
---

Final round of workshop fixes on 2026-09-15, shipped across 0.6.7 and 0.6.8.

**Failed cards now say why in plain words.** A runaway reported a raw pydantic
trace, and the token-cap message pointed at `--max-tokens` and `paratext.toml`,
neither reachable from a hosted Space. `runs.friendly_failure()` translates the
failures that actually happen — runaway/truncated JSON, timeout, rate limit,
auth, connection — and names cards by their workshop number. Anything
unrecognised keeps its own first line rather than getting a diagnosis invented
for it.

**The editor reopens on the prompt last run.** 0.6.6 made the server store it,
but the browser fetched workshop state only once at page load, so returning to
the editor redrew from a cached copy holding the default. The route re-reads on
entry now. Worth noting the first fix was verified against the API and not the
UI, which is why it shipped half-done.

**Start over returns to the index** rather than leaving the attendee in the
editor on a default prompt with no sign the rounds had gone too.

**Reproduced the user's failure exactly**: the default prompt plus "always add a
:) to the end of the shelfmark" makes card 01 run away about one time in three.
That card carries its call number twice — down the left edge and again at the
foot — so an instruction to append to the shelfmark leaves the model unable to
settle. Card 02 is the other fragile one, with the typewriter bracket glyphs
that caused the earlier mojibake. Both are good teaching cases, not defects.
