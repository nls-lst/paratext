# Writing a project

`paratext new` scaffolds three files:

```
my_cards/
    prompt.md     # the prompt (prose, for the model)
    schema.py     # the Pydantic output schema (your metadata fields)
    __init__.py   # wires them together
```

`__init__.py` stays small because input handling comes from a **source adapter**:

```python
from paratext.projects import Project, load_prompt
from paratext.sources import image_source   # or pdf_source, hf_dataset_source

from .schema import Record

PROJECT = Project(
    name="my-cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=Record,
    source=image_source(),
)
```

Four adapters ship with paratext:

| | |
|---|---|
| `image_source()` | a local directory of images, one sample per file |
| `pdf_source()` | PDFs rendered to page images |
| `hf_dataset_source(repo="owner/name")` | an imagefolder-style dataset on the Hugging Face Hub |
| `video_source()` | videos, or a manifest of clips, sampled to frames (needs ffmpeg) |

`hf_dataset_source` is the round trip on `paratext export`: a published eval set
can be pulled back and re-run. Leave `repo` unset to take the id from the run's
source instead, so `--source owner/name` works without rebuilding the project,
and pass `token=` for a private dataset — nothing reads an ambient credential.
It reads imagefolder layouts only; a parquet-backed dataset needs the `datasets`
library and a column map, and would be a separate adapter.

`video_source` takes a directory of video files, one sample each, or a manifest
(`.jsonl` or `.csv`) with one clip per row: `id`, `src` (a path or a URL, HLS
included) and optionally `start` and `end` in seconds, `poster` and `label`.
Each clip is sampled to eight evenly spaced frames by default; pass
`frames=evenly_spaced(n)` (from `paratext.video`) or your own
`frames(start, end) -> [seconds]` to change that. Each frame carries its time
on a band below the picture, counted from the start of the clip, so ask for
timecodes in the prompt on that basis; in review, clicking one seeks to it. The review UI plays the clip; see
[Choosing a review view](review-views.md#video).

Register it so it's discovered at runtime:

```toml
[project.entry-points."paratext.projects"]
my-cards = "my_cards:PROJECT"
```

That's the whole contract. The review view defaults to showing every schema
field; see [Choosing a review view](review-views.md) to curate it. Optional hooks
(`curate`, `build_record`, `ground_truth`) handle drop rules and ground truth.

Your fields end up named in three places — schema, prompt, and view — with no
automatic link between them. Keep them in step by calling `audit_project(PROJECT)`
from a test; `paratext new` generates one. Put behaviour in `prompt.md`, and keep
the schema's `Field(description=...)` short and structural — those descriptions
are sent to the model too, and shouldn't restate the prompt in a second voice.


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
