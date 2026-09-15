---
id: PTX-64
title: Model emitted a literal mojibake escape in a notes field
status: done
horizon: future
flow: clear
result: 'Diagnosed, no code change. Model output, not a storage fault — em-dash, degree and half all round-trip in the same files, and this is the only occurrence in 16 records. Card reads M[ellen] / C[hamber-lain]; the model garbled the square brackets into a double-encoded escape. Left as-is deliberately: the review UI is the mechanism for catching transcription errors, and a defensive un-escape would risk real backslashes. Reopen if a second instance appears.'
created: '2026-09-15'
updated: '2026-09-15'
---

Spotted 2026-09-15 on the HF Space, bpl-cards round 2, card
`02_003-actors-english-adh_00406`. The `notes` field contains
`[MÃ¬llen]. CÃ§hamberlain]` — as *literal* escape text, twelve
characters, not resolved characters.

**Not a paratext encoding bug.** In the same two rounds `—`, `°` and `½` all
store and round-trip correctly; this is the only occurrence in 16 records. The
model emitted it.

Two faults stacked. Resolve the escape and you get `Ã` + `¬`; read those as
Latin-1 bytes `C3 AC` and decode UTF-8 and you get `ì` — so it is mojibake, and
the escape was additionally never resolved. Underneath it is just a misreading:
the card reads `"From the author, 1887.--M[ellen]. C[hamber-lain]."--ms. note on
fly-leaf.` and the model choked on this typewriter's square brackets.

**Decided: leave it.** A defensive un-escape pass would risk corrupting genuine
backslashes to paper over a transcription error, and the review UI exists to
catch exactly this. It is also a good live example for the workshop — a real
"would I accept this?" case found in the demo data.

Worth revisiting only if a second instance turns up, which would suggest the
bracket glyph is a systematic trigger rather than a one-off.
