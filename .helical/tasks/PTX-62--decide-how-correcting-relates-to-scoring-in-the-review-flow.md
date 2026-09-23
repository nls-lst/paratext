---
id: PTX-62
title: Decide how correcting relates to scoring in the review flow
status: done
horizon: now
flow: clear
result: 'Decided 2026-09-10: leave the flow alone — no collapse, and not even the jump-to-editor affordance. Scoring and correcting are separate tasks in day-to-day work, done at different times by different people, and the UI should keep saying so. The free-text note stays the prompt-rewriting signal and the gold label stays the durable target. The friction is real for the workshop and accepted deliberately: the session shows how we actually work, not a slick end-to-end demo.'
created: '2026-09-09'
updated: '2026-09-10'
---

Concern raised 2026-09-09 while prepping the workshop: the route to an eval set
feels convoluted. Score a card → write a note → go to a separate Build eval set
screen → re-enter values. The pull is to fold correction into the "needs tweaks"
verdict itself, one screen, one pass.

**The reason not to collapse them:** the free-text note is the single biggest
signal for rewriting the prompt. Note and correction are different artefacts
with different lifetimes — the note diagnoses *this round* and is thrown away
when the prompt changes; the gold label is the durable target and survives every
future round. A person given editable fields at the moment of judgement stops
writing prose, because the fields feel like they say it. Same ordering effect as
[[notes-field-is-not-reasoning]]: whichever input comes first shapes the second,
so note-then-correct keeps the diagnosis uncontaminated.

**Middle option** (the likely answer): keep the two artefacts and the two passes,
but add a "fix this now" affordance from a needs_tweaks card that jumps into the
editor for that card and returns to Review. The note is still captured first;
what goes away is the sense of a separate screen you must remember to visit.

Note the editor already prefills from the model output (`prefill = s.gold?.output
?? base` in app.js), so correcting is editing, not retyping — worth checking that
attendees actually notice, since "manual re-entry" was how it felt.

For the workshop the cost is not all bad: making gold by hand is what makes
"we produce evals" concrete and shows people that gold is expensive.
