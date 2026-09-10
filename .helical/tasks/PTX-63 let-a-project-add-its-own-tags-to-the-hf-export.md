---
id: PTX-63
title: Let a project add its own tags to the HF export
status: done
horizon: next
flow: clear
result: 'Added a glam-eval kind tag alongside the paratext provenance tag, plus --tag / tags config. merge_tags() de-duplicates built-ins + project + publisher tags in order; wired through the CLI and the review UI''s push path. Docs in export.md and hf-export-spec.md; 3 new tests, 310 pass. Existing published datasets keep their old tags until re-exported.'
created: '2026-09-10'
updated: '2026-09-10'
---

The dataset card front matter in `hf_export.py:_dataset_card` hardcodes
`tags: paratext, library-metadata, <project>`. There is no `--tag` flag and no
`tags` key in `[project.<name>.export]` — `ExportConfig` has no field for it.

Discovery already works as far as it goes: `paratext` is on every export, and
`https://huggingface.co/api/datasets?filter=paratext` returns
`NationalLibraryOfScotland/index-cards-eval` (verified 2026-09-10).
`?other=paratext` is the website's parameter; the API wants `filter=`.

**The reason to add tags is that `paratext` is a provenance tag, not a kind
tag.** It means "exported by this tool", not "is an eval set" — and the
workshop's closing argument is that other institutions should publish their own
checked examples. The day that argument works, filtering on `paratext` stops
identifying our eval sets, and a run of the bench picks up whatever anyone
exported. Wanted: a second, agreed *kind* tag (e.g. `glam-eval`) alongside the
provenance one, settled with Daniel since he is the consumer.

Shape: `tags: list[str]` on `ExportConfig`, a repeatable `--tag`, a `tags` key
under `[project.<name>.export]`, merged with the built-ins and de-duplicated.
An HF Collection is the complement for a curated, ordered list.
