# Export

Once a round is reviewed, `paratext export -p <project>` turns the human-approved
items into a Hugging Face dataset, MARCXML, or Dublin Core.

```bash
paratext export -p monographs --format hf     # Hugging Face dataset (ML)
paratext export -p monographs --format marc   # MARCXML catalogue records
paratext export -p monographs --format dc     # Dublin Core (OAI-DC) records
paratext export -p monographs                 # no --format: prompts on a terminal
```

`--round N` picks a round; the default is the latest.

## The gold set

Every format ships the **same** set, of two kinds:

- **verified** — a reviewer marked the model output *good enough*. The label is
  that output.
- **corrected** — a reviewer edited the fields in **Build eval set**. The label is
  the edited output.

Each row records which it was (`_label_status`), and corrected rows also carry
`_corrected_fields`. `_verdict` keeps the original model verdict, so **accuracy
still measures the model**, not the human who fixed it.

With no corrections made, the gold set is just the *good enough* rows.

## Hugging Face (`--format hf`)

Writes an imagefolder plus `metadata.jsonl` and an auto-generated dataset card
recording schema, model, prompt and review accuracy.

```bash
paratext export -p index-cards --dry-run     # build ./export/<round>/ and inspect
paratext export -p index-cards               # push (private)
paratext export -p index-cards --public      # public
```

- **Private by default.** `--public` is opt-in.
- **Licence is steered, not gated.** With no `license` set, export prompts for
  one — CC0-1.0 recommended for open sharing. Leaving it blank still publishes;
  the card records `license: other`. Image rights remain your call.
- **Single-image projects only.** Multi-image projects (like monographs) are
  rejected — use `marc`/`dc` for those.

```toml
[project.index-cards.export]
repo    = "your-org/your-dataset"
license = "cc0-1.0"     # shorthands like `cc0` are normalised
# min-verdict = "good_enough"
# include-negatives = false
# annotators = "omit"     # omit | pseudonym | name
```

Auth uses your Hugging Face token (`huggingface-cli login` or `HF_TOKEN`). The
review UI can also push via **Sign in with Hugging Face**, in which case each
reviewer pushes as themselves and the server stores no token.

Implementation detail lives in [hf-export-spec.md](hf-export-spec.md).

## MARC & Dublin Core (`--format marc` / `--format dc`)

Writes catalogue records for loading into an ILS or discovery layer — a MARCXML
`<collection>` (`export/<round>.marcxml`) or an OAI Dublin Core file
(`export/<round>.dc.xml`). Plain stdlib XML, no extra dependency.

Unlike HF these are metadata-only, so **multi-image projects work**.

### Field mapping

Each schema field maps to a MARC tag or DC element. Fields with **standard
names** (title, subtitle, author/creator, publisher, place, date, isbn, subject,
…) are inferred automatically — a project using conventional names needs no
configuration at all.

For any field with a non-standard name, a **wizard** asks you for a target once
and saves the answer. Unmapped fields are dropped with a warning, never a hard
error.

```toml
# Auto-inferred for standard names; edit only to override or map unknowns.
# "" means "skip this field" (so the wizard stops asking).
[project.monographs.export.marc]
title             = "245$a"
personal_authors  = "100$a|700$a"   # first → 100 (main entry), rest → 700 (added)
publisher         = "264$b"
publication_date  = "264$c"
isbn              = "020$a"

[project.monographs.export.dc]
title            = "title"
personal_authors = "creator"
publication_date = "date"
```

### AI-assistance note

Records can carry a provenance note saying the metadata was machine-assisted. It is
**opt-in** — nothing is added unless you ask for it, because a record with no machine
involvement should not carry the claim.

```bash
paratext export -p monographs --format marc --ai-note
paratext export -p monographs --format marc --ai-note "Machine-generated, reviewed {date}"
```

The bare flag uses the default wording, `Some metadata created with AI assistance on {date}`.
Pass your own text to replace it. `{date}` is filled with today's date as `dd/mm/yy`; text
without `{date}` is used verbatim.

To make it the default for a project, set it in `paratext.toml`:

```toml
[project.monographs.export]
ai-note = true                                   # default wording
ai-note = "Some metadata created with AI assistance on {date}"   # or your own
```

`--ai-note` on the command line beats the config value; `ai-note = false` (or leaving it out)
suppresses the note entirely.

The review UI's export modal has the same control: a checkbox and an editable text box below
the mapping table, seeded from the config value and date-substituted so the box shows exactly
what will be written. Unticking it suppresses the note even when config sets one.

The note is written as:

| format | where |
|---|---|
| MARC | `588` with first indicator `0` ("source of description note"), text in `$a` |
| Dublin Core | an additional `dc:description` |

```xml
<datafield tag="588" ind1="0" ind2=" ">
  <subfield code="a">Some metadata created with AI assistance on 24/08/26</subfield>
</datafield>
```

## Exporting from the review UI

The Stats page has an **Export…** button offering the same three formats, plus
raw JSONL. It shows live record counts per scope (good enough / needs tweaks /
everything) and lets you edit the field mapping before downloading.
