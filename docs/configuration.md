# Configuration

A `paratext.toml` in the working directory holds your defaults. `paratext config`
creates it from a template and opens it; `paratext config --show -p <project>`
prints what actually resolved.

## Resolution order

Highest priority first:

1. **CLI flags** — `--source`, `--model`, …
2. **`PARATEXT_*` environment variables** — `PARATEXT_MODEL`, `PARATEXT_BASE_URL`, … (idiomatic in containers)
3. **`[project.<name>]`** in `paratext.toml` — per-project
4. **top-level keys** in `paratext.toml` — shared by all projects

Keys are **kebab-case**, matching the CLI flag that sets them: `--base-url`
becomes `base-url`.

```toml
base-url = "http://localhost:8000/v1"
model    = "Qwen3-VL-30B"

[project.my-cards]
source = "/data/my-cards/images"
output = "output/my-cards.jsonl"
```

Once a project has a section, `paratext run -p my-cards` needs nothing else.

## Top-level keys

| Key | Default | What |
| --- | --- | --- |
| `base-url` | `http://localhost:8000/v1` | OpenAI-compatible endpoint |
| `api-key` | `EMPTY` | Token; prefer `PARATEXT_API_KEY` (see below). Local servers ignore it |
| `model` | *(required)* | Model id your endpoint serves |
| `limit` | none | Process at most N inputs |
| `review-port` | `5050` | Port for `paratext review` |
| `no-structured` | `false` | Fall back to plain completion + JSON parsing |
| `skip-preflight` | `false` | Skip the endpoint reachability check |

Any of these may also be set per-project. `source`, `output` and `review-out`
are normally per-project.

## Remote and hosted endpoints

The endpoint is just an OpenAI-compatible URL, so a hosted API works exactly like
a local server — only `base-url`, `api-key` and `model` change.

```toml
base-url = "https://router.huggingface.co/v1"
model    = "Qwen/Qwen2.5-VL-7B-Instruct"   # must accept images
```
```bash
export PARATEXT_API_KEY=hf_…               # keep the token out of the file
```

Three things to know:

- **`base-url` is the API *base*, not an endpoint.** The client appends
  `/chat/completions` itself, so `https://openrouter.ai/api/v1` is right and
  `https://openrouter.ai/api/v1/chat/completions` would request a doubled path.
  paratext trims a full endpoint URL and tells you it did — but the corrected
  value is worth putting in your config, not relying on.
- **Auth — keep the token in the environment.** `paratext.toml` holds source
  paths and model ids, so it is normally committed; a provider token in it is one
  `git add` from being published. Use `PARATEXT_API_KEY` or `--api-key`. The
  `api-key` config key exists and works, but paratext warns when it finds a token
  there for a remote endpoint. Local servers ignore the key entirely.
- **Structured output** — extraction uses OpenAI json-schema structured outputs.
  If a provider or model doesn't support them, set `no-structured = true` to fall
  back to a plain completion plus JSON parsing.

paratext is a *client*, not a model runner. To use a model nobody hosts,
self-host it behind vLLM/TGI/llama.cpp and point `base-url` there.

## Feature tables

Some features have their own config table:

- `[project.<name>.export]` and `[project.<name>.export.marc|dc]` — see [Export](export.md)
- `[detector]` — see [Scanned cards](scanned-cards.md)
- `[carbon]` — see [Green scheduling](green-scheduling.md)

## Environment variables

Every recognised key has a `PARATEXT_<KEY>` form, upper-cased with underscores:
`PARATEXT_BASE_URL`, `PARATEXT_MODEL`, `PARATEXT_API_KEY`, `PARATEXT_PROJECT`, …

Two extra variables exist outside the config file:

- `PARATEXT_CARD_DETECTOR` — path to local detector weights ([Scanned cards](scanned-cards.md))
- `PARATEXT_HF_CLIENT_ID` — Hugging Face OAuth app id, for pushing from the review UI

## Checking what resolved

```bash
paratext config --show -p my-cards
```

Prints the config file path and every resolved value, so you can see which layer
won. Unrecognised keys are ignored rather than erroring, so a typo shows up here
as a missing value rather than a crash.
