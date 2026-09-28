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

A sample with `media` shows a player in place of its images, in either layout.
A source puts it in the sample's metadata and packaging carries it through,
checking its shape:

```python
metadata={"media": {
    "src": "https://example.org/reel-12.m3u8",  # HLS or a plain video file
    "start": 120, "end": 279,                    # the clip, in seconds; optional
    "poster": "https://example.org/reel-12.jpg",
    "label": "Programme",                        # names the clip on the timeline
    "tracks": [
        {"name": "Model", "items": [{"start": 120, "end": 150, "text": "Opening titles"}]},
        {"name": "Catalogue", "note": "shotlist times are approximate", "items": [...]},
    ],
}}
```

Only `src` is required. Times count from the start of the file, so one long
tape can yield several clips. Each track draws as a strip under the player:
hovering a segment shows its text, and clicking one plays from there. A track
with a `note` is marked ≈, and the note is shown beneath. In the fields,
timecodes such as `01:23` in a table cell seek the player, relative to the clip
start.

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
