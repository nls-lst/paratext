# Review and rounds

Extraction quality lives almost entirely in the prompt, so the workflow is a
loop: **run → review → edit the prompt → run again**. A **round** captures one
prompt version, keyed on the prompt's hash:

- **Edit `prompt.md` and re-run with `--re-extract`** → a new round (`-r2`,
  `-r3`, …). The UI shows the two most recent rounds side by side and highlights
  what changed. The flag is needed because a run resumes on sample id: without
  it the existing extractions are already there, so the model is never called.
  paratext stops and says so rather than resuming into a stale file. On a small
  collection, `re-extract = true` in `paratext.toml` makes it the default and
  the loop needs no flag.
- **Re-run the same prompt** (a resume, or a bigger `--limit`) → the current round
  is updated in place, keeping the annotations you've already made.

Reviewers give a verdict and a free-text note. The **Build eval set** tab goes
further: it surfaces the rows the model got wrong and lets you edit the fields
into the correct answer, stored separately as **gold labels**. Accuracy still
reflects the model — correcting a row never changes its verdict — but those
corrected rows ship as gold alongside the approved ones when you export.

Everything is saved to a SQLite `annotations.db` you can query directly.

