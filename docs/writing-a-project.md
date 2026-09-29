# Writing a project

A project is the prompt, schema and input handling for one kind of material.
`paratext new` writes a working one; this page covers what to change in it, in
the order you'll usually change it.

## 1. The files

```
my_cards/
    prompt.md     # the prompt (prose, for the model)
    schema.py     # the Pydantic output schema (your metadata fields)
    __init__.py   # wires them together
```

`__init__.py` stays small:

```python
from paratext.projects import Project, load_prompt
from paratext.sources import image_source

from .schema import Record

PROJECT = Project(
    name="my-cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=Record,
    source=image_source(),
)
```

## 2. The source

The **source adapter** reads your material and turns each item into images for
the model:

| Adapter | Reads |
|---|---|
| `image_source()` | a directory of images, one item per file |
| `pdf_source()` | PDFs, rendered to page images |
| `hf_dataset_source(repo="owner/name")` | an imagefolder dataset on the Hugging Face Hub |
| `video_source()` | videos, or a manifest of clips, sampled to frames (needs ffmpeg) |

Their options are under [Source details](#source-details). If you already have
the metadata and only want to review it, you don't need a source: see
[Reviewing metadata you already have](review-views.md#reviewing-metadata-you-already-have).

## 3. The schema and the prompt

The schema says *what* comes back: one field per piece of metadata, with its
type. The prompt says *how* to fill each field: what counts, what to leave
empty, and what to do with the awkward cases. Behaviour belongs in `prompt.md`.
Keep the schema's `Field(description=...)` short and structural: those
descriptions are sent to the model too, and shouldn't restate the prompt in a
second voice.

Every field ends up named in three places (schema, prompt and view) with no
automatic link between them. The test `paratext new` generates calls
`audit_project(PROJECT)`, which fails when they drift apart.

## 4. The model

The model normally comes from `paratext.toml`. When a project has been tuned
against one model, say so on the project:

```python
PROJECT = Project(..., model="Qwen3.6-35B-A3B")
```

It takes precedence over the top-level `model` in `paratext.toml`, so one config
can serve projects that prefer different models. `[project.<name>] model = …`,
`PARATEXT_MODEL` and `--model` still override it. Model ids are whatever your
endpoint calls the model, so a project shared with others is tied to that
naming.

## 5. The review view

By default, reviewers see every schema field beside the item. To choose the
fields, compare against an existing record, or review video, see
[Choosing a review view](review-views.md).

Optional hooks handle the rest: `curate` drops or sets aside items before
review, `ground_truth` supplies the existing record, and `build_record` shapes
what reviewers see.

## 6. Registering it

`paratext new` does this for you. By hand, add an entry point so paratext can
find the project:

```toml
[project.entry-points."paratext.projects"]
my-cards = "my_cards:PROJECT"
```

Then run `paratext inspect -p my-cards` to see what is actually installed: the
fields, the prompt, the source, the model and whether they agree.

## Where projects are found

Run paratext from your project directory and it finds your project. That is the
whole rule in practice — the CLI hands over to the nearest `.venv` that has
paratext installed, so a bare `paratext run -p my-cards` works.

### Why, and what to do if it doesn't

Projects are discovered through Python entry points, which are **per
environment**: paratext finds a project when the two are installed into the
*same* environment. Nothing about it is tied to your working directory, and
`uv tool install` deliberately isolates the tool, so an isolated `paratext`
would otherwise see only the bundled example.

The hand-over happens only when the nearest `.venv` really has paratext in it,
and never over an environment you activated yourself. `PARATEXT_NO_DELEGATE=1`
turns it off. Failing that, any of these put the two in one environment:

```bash
uv run paratext …                          # use the project's own .venv
source .venv/bin/activate                  # then a bare `paratext` works too
uv tool install paratext-cli --with .      # inject the project into the tool
pip install paratext-cli && pip install -e .   # or just share one environment
```

## Source details

**`image_source`** reads a flat directory. For scanned index cards it can also
drop blank versos, crop to the card and suppress show-through; see
[Scanned cards](scanned-cards.md).

**`pdf_source`** reads PDFs recursively. `pages(num_pages) -> [indices]` picks
the pages to render; the default is the first three and the last.

**`hf_dataset_source`** is the round trip on `paratext export`: a published eval
set can be pulled back and re-run. Leave `repo` unset to take the id from the
run's source instead, so `--source owner/name` works without rebuilding the
project, and pass `token=` for a private dataset; nothing reads an ambient
credential. It reads imagefolder layouts only; a parquet-backed dataset needs
the `datasets` library and a column map, and would be a separate adapter.

**`video_source`** takes a directory of video files, one item each, or a
manifest (`.jsonl` or `.csv`) with one clip per row: `id`, `src` (a path or a
URL, HLS included) and optionally `start` and `end` in seconds, `poster` and
`label`. Each clip is sampled to eight evenly spaced frames by default; pass
`frames=evenly_spaced(n)` (from `paratext.video`) or your own
`frames(start, end) -> [seconds]` to change that. Each frame carries its time on
a band below the picture, counted from the start of the clip, so ask for
timecodes in the prompt on that basis. The review UI plays the clip, and
clicking a timecode seeks to it.
