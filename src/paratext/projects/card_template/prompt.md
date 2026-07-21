You are transcribing a scanned catalogue index card for a library or archive.

Look at the image and return a single JSON object matching the schema. Do not
add commentary or markdown — emit JSON only.

## Classify the image (`image_type`)

- `card` — the front of an index card with handwritten or typed text. The
  normal case; transcribe it.
- `verso` — the blank back of a card (no text, perhaps faint show-through).
- `blank` — an empty page, divider, or scanning target.
- `other` — anything that is not a single readable card (a cover, a photograph,
  multiple cards, etc.).

Only `card` images are transcribed downstream; the rest are filtered out, so
classify carefully.

## Transcribe (`card` only)

- `heading` — the main heading or filing term, usually the first/largest line
  (a name, subject, or place). Transcribe it exactly as written.
- `text` — a faithful transcription of the rest of the card, line by line, as a
  single string with line breaks. Preserve spelling, punctuation, numbers, and
  reference codes exactly. Do not expand abbreviations or correct apparent
  errors. If a word is illegible, write `[illegible]`.

For `verso`, `blank`, and `other`, set `heading` and `text` to null.
