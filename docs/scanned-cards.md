# Scanned cards (`paratext.cards`)

Two reusable tools for index-card collections. Both are **off by default** and
both are calibrated against one collection's scans, so neither should be trusted
on new material without checking it first.

Enable them per-project on the source adapter:

```python
source = image_source(verso_filter=True, crop=True, suppress_show_through=True)
```

## `is_verso(image)` — blank-back filter

A pure-NumPy check (no ML dependency) that drops the blank backs of cards before
any model call, saving the run time and cost.

Thresholds are arguments; recalibrate them for your scanner. **A false positive
silently discards a real card**, so verify against a labelled sample before
enabling it on a full run.

## `load_card_detector()` — card-region crop

A permissive (BSD) torchvision RetinaNet that crops a scan down to the card,
removing desk background. Needs the `[detector]` extra:

```bash
uv tool install "paratext[detector]"
```

If the runtime or the weights are unavailable it falls back to a **uniform
margin crop** and says so in the run summary — a `!` notice at the end of the
run. Preprocessing that silently does nothing is the worst failure mode here, so
the fallback is always reported.

### Pointing at your own weights

The reference weights are trained on National Library of Scotland catalogue
cards. They are a starting point, not a general-purpose card detector — expect
to train your own.

```toml
[detector]
repo = "your-org/your-card-detector"   # a Hugging Face repo
file = "weights.pt"
# ...or a local file instead, e.g. weights you've just trained:
weights = "models/my-card-detector.pt"
```

Resolution order, highest first: the `weights=` argument → the
`PARATEXT_CARD_DETECTOR` environment variable → `weights` in `[detector]` →
downloading `file` from `repo`.

The reference weights live at
[`NationalLibraryOfScotland/card-detector-retinanet`](https://huggingface.co/NationalLibraryOfScotland/card-detector-retinanet).

## `suppress_show_through(image)` — flatten bleed-through

Cards stacked for scanning can show faint ink from the card behind, which a
model will happily transcribe as a real entry. This flattens that bleed to
paper-white before the model sees it, using a per-image threshold so the card's
own ink is untouched.

It is **partial** — darker ghosts survive. Pair it with a structural check in
your prompt (for example, a punctuation grammar the real entries must obey) so
surviving artefacts are still caught.

## Worked example

The bundled `card-template` project is a neutral starting point — a minimal
prompt and schema to copy and edit:

```bash
paratext run -p card-template
```

It leaves all three tools off. Enable them once you've calibrated for your own
collection.
