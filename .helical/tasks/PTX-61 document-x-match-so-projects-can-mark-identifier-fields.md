---
id: PTX-61
title: Document x-match so projects can mark identifier fields
status: todo
horizon: future
flow: clear
created: '2026-09-09'
updated: '2026-09-09'
---

The annotation already works via json_schema_extra but nothing says so

A benchmark scoring our exports has to know which fields are transcribed
identifiers (compare verbatim) rather than free text (compare loosely). Daniel's
harness overlays `x-match: "exact"` onto `ms_no` and `folios` from outside,
which makes a third party maintain a guess about our data.

It does not need a new feature. Verified that Pydantic passes this straight
through into the exported schema:

    ms_no: Optional[str] = Field(None, json_schema_extra={"x-match": "exact"})

So this is a convention and documentation gap, worth three things in order of
size: say so in `docs/writing-a-project.md`; consider a small helper for
discoverability; and consider using it ourselves, since a field paratext knows
is an identifier could be compared strictly in the review UI and a
whitespace-only difference flagged rather than passed.

The matching downstream change is declaring it on the index-cards schema in
`paratext-nls`, after which the external overlay is redundant.

Deferred until after the workshop.
