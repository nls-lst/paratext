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
from paratext.sources import image_source   # or pdf_source

from .schema import Record

PROJECT = Project(
    name="my-cards",
    schema_version="v1",
    prompt=load_prompt(__file__),
    schema=Record,
    source=image_source(),
)
```

Register it so it's discovered at runtime:

```toml
[project.entry-points."paratext.projects"]
my-cards = "my_cards:PROJECT"
```

That's the whole contract. The review view defaults to showing every schema
field; override it only when you want to curate the display. Optional hooks
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
