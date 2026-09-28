# Choosing a review view

A project's `view` decides what reviewers see. It is optional: without one,
every schema field is shown in a single panel beside the image, which is right
for most new projects. Add a `View` when you want to choose the fields, compare
against an existing record, or rename things for reviewers.

A view is a list of **panels**. Each one shows some schema fields from one side
of the record:

| `source` | What it holds |
|---|---|
| `model_output` | what the model extracted |
| `ground_truth` | the existing record, from the project's `ground_truth` hook |

The layout follows from the panels. One panel sits beside the images, so the
reviewer can check each field without scrolling. Two sit side by side below
them, so the fields line up for comparison.

## Recipes

### One image, nothing to compare against

Index cards, photographs, single-page ephemera.

```python
view=View(
    title="Index card",
    id_label="Image ID",
    panels=[Panel(source="model_output", title="Model output", fields=["heading", "text"])],
)
```

### Compared with an existing record

Books, pamphlets, anything with a catalogue record.

```python
view=View(
    title="Document",
    id_label="MMSID",
    panels=[
        Panel(source="ground_truth", title="Catalogue record", fields=FIELDS),
        Panel(source="model_output", title="Model output", fields=FIELDS),
    ],
)
```

Put the reference first, because reviewers read it as the baseline. The panels
don't need the same fields: when the reference has a different shape, as with
another institution's metadata, give each panel its own list.

### Video

Video samples are in development on the `video-review` branch.

## Smaller options

| Option | Use it to |
|---|---|
| `labels={"isbn": "ISBN"}` | rename a field for reviewers. The default is the key, humanised. |
| `collapsed=["notes"]` | fold a field away, and hide it when empty. Collapsed fields are left out of gold labels. |
| `table_label=("model_output", "heading")` | choose the field that names each row in the stats table |
| `verdicts=[...]` | replace the three default verdicts |
| `notes_label`, `notes_placeholder` | reword the notes box |
| `Panel(flag=..., flag_label=...)` | add a button for flagging the reference record for follow-up |
| `exports=[...]` | add project-specific downloads to the stats page |
| `layout="split"` or `"stacked"` | override the layout the panels imply |

Leave out triage fields such as `image_type`, which only drive `curate`.
Field names in a view must exist in the schema. The `audit_project` test that
`paratext new` generates checks this.
