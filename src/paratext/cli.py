"""`paratext` CLI — one command for the whole pipeline.

Subcommands:
    run         Extract then package in one go (the common path).
    extract     Run the VLM over a directory of inputs, write JSONL.
    package     Convert JSONL into a review dataset (samples.json + images/).
    review      Launch the local web UI to review a packaged dataset.
    export      Publish a reviewed round as a Hugging Face dataset.
    carbon      Show current grid carbon/renewables (for --green scheduling).
    sample      Build a random N-image subset of a source directory (helper).
    config      Open the config file (``--show`` prints the resolved defaults).
    new         Scaffold a new project package (interactive).

Most values resolve from ``paratext.toml`` or the environment, so once a project
is configured ``paratext run -p <project>`` is all you need. See paratext.config.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import subprocess
from pathlib import Path

from .config import (
    CONFIG_TEMPLATE,
    coerce_paths,
    load_defaults,
    local_config_path,
)
from .extract import run as run_extract
from .io import read_provenance
from .packaging import package
from .projects import get_project, project_names
from .review.server import DEFAULT_PORT

# Default root holding each project's review datasets (review/<project>-r<N>/),
# so `paratext review` with no args groups a project's rounds on its homepage.
REVIEW_ROOT = Path("review")


# ── Review rounds ────────────────────────────────────────────────────────────
# A "round" is a prompt version: datasets are named `<project>-r<N>` and the
# review UI diffs consecutive rounds. Re-running the *same* prompt updates the
# current round in place (keeping its annotations); a *changed* prompt rolls to
# the next round. The round is keyed on the prompt hash, not schema_version —
# the prompt is what's iterated round to round.
def _round_dirs(project: str) -> list[tuple[int, Path]]:
    """Existing `<project>-r<N>` review dirs under REVIEW_ROOT, sorted by round."""
    if not REVIEW_ROOT.is_dir():
        return []
    found: list[tuple[int, Path]] = []
    for p in REVIEW_ROOT.iterdir():
        m = re.match(rf"^{re.escape(project)}-r(\d+)$", p.name)
        if m and (p / "samples.json").is_file():
            found.append((int(m.group(1)), p))
    return sorted(found)


def _prompt_hash_of(dataset_dir: Path) -> str | None:
    """The prompt hash a packaged round was built with (from its first record)."""
    try:
        records = json.loads((dataset_dir / "samples.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return records[0].get("prompt_hash") if records else None


def _resolve_round(
    project: str, prompt_hash: str, forced: int | None
) -> tuple[Path, int, bool]:
    """Pick the review-output dir for this run. Returns (dir, round, reuse).

    `reuse` is True when we're re-writing an existing round (same prompt), which
    the caller uses to preserve that round's annotations. `forced` is --round N.
    """
    rounds = _round_dirs(project)
    if forced is not None:
        reuse = any(r == forced for r, _ in rounds)
        return REVIEW_ROOT / f"{project}-r{forced}", forced, reuse
    if not rounds:
        return REVIEW_ROOT / f"{project}-r1", 1, False
    last_round, last_dir = rounds[-1]
    if prompt_hash and _prompt_hash_of(last_dir) == prompt_hash:
        return last_dir, last_round, True  # same prompt → same round
    return REVIEW_ROOT / f"{project}-r{last_round + 1}", last_round + 1, False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

# Hardcoded fallbacks when neither TOML, env, nor CLI provides a value.
HARDCODED_DEFAULTS: dict = {
    "base_url": "http://localhost:8000/v1",
    "api_key": "EMPTY",  # most local OpenAI-compatible servers ignore the key
    "limit": None,
    "review_port": DEFAULT_PORT,
    "no_structured": False,
    "skip_preflight": False,
}


def _do_extract(args: argparse.Namespace) -> None:
    missing = [
        flag
        for flag, val in (
            ("--project", args.project),
            ("--source", args.source),
            ("--model", args.model),
        )
        if val is None
    ]
    if missing:
        raise SystemExit(
            f"missing required value(s): {', '.join(missing)}\n"
            f"  pass on the CLI, set PARATEXT_<NAME>, or add to paratext.toml"
        )
    # --output defaults to output/<project>.jsonl when unset.
    output = args.output or Path("output") / f"{args.project}.jsonl"
    args.output = output  # so callers (e.g. `run`) see the resolved path

    # Carbon-aware gating: block until the grid is clean, and stamp the reading
    # into provenance so `export` can report it.
    energy = None
    if getattr(args, "green", False):
        from . import carbon

        cfg = carbon.load_config(
            min_renewable=getattr(args, "renewables_above", None),
            max_carbon=getattr(args, "max_carbon", None),
        )
        reading = carbon.wait_for_clean(cfg)
        energy = reading.to_provenance(scheduled_window=cfg.mode == "window")

    run_extract(
        get_project(args.project),
        source=Path(args.source),
        output=Path(output),
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        limit=args.limit,
        use_structured=not args.no_structured,
        skip_preflight=args.skip_preflight,
        energy=energy,
    )


# ── Extract ───────────────────────────────────────────────────────────────
def _cmd_extract(args: argparse.Namespace) -> int:
    _do_extract(args)
    print(f"Wrote extractions to {args.output}")
    return 0


# ── Run (extract + package) ────────────────────────────────────────────────
def _cmd_run(args: argparse.Namespace) -> int:
    _do_extract(args)
    # Resolve which review round to write. An explicit --review-out wins; else
    # each run lands in review/<project>-r<N>, rolling to a new round when the
    # prompt changed and updating the current round in place when it didn't.
    if args.review_out:
        review_out, round_no, reuse = Path(args.review_out), None, args.review_out.exists()
    else:
        prompt_hash = read_provenance(Path(args.output)).get("prompt_hash", "")
        review_out, round_no, reuse = _resolve_round(args.project, prompt_hash, args.round)
    # Preserve a reused round's annotations; only clobber on a new round or --fresh.
    kept, skipped = package(
        Path(args.output), review_out, args.project, fresh=args.fresh or not reuse
    )
    print(f"Wrote extractions to {args.output}")
    where = f"round {round_no} ({review_out.name})" if round_no else str(review_out)
    verb = "Updated" if reuse else "Packaged"
    print(f"{verb} {kept} record(s) → {where}")
    if skipped:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(skipped.items()))
        print(f"Skipped {sum(skipped.values())} item(s): {breakdown}")

    from .review.server import is_running

    port = args.review_port
    root = review_out.parent  # the review/ root holding every project's rounds
    if is_running(port):
        print(f"\nReview server already running — reload "
              f"http://127.0.0.1:{port} to see '{args.project}'.")
    elif args.review:
        from .review import serve

        print()
        serve(root, port=port, open_browser=True)  # blocks until Ctrl-C
    else:
        print("\nReview them:  paratext review")
    return 0


# ── Package ───────────────────────────────────────────────────────────────
def _cmd_package(args: argparse.Namespace) -> int:
    # Like `run`: infer the project from the JSONL's provenance and, unless --out
    # is given, resolve the review/<project>-r<N> round from the prompt hash.
    provenance = read_provenance(args.jsonl)
    project = args.project or provenance.get("project")
    if not project:
        raise SystemExit(
            "could not infer the project from the JSONL provenance; pass -p/--project"
        )
    if args.out:
        out, reuse = args.out, args.out.exists()
    else:
        out, _round, reuse = _resolve_round(project, provenance.get("prompt_hash", ""), args.round)
    kept, skipped = package(args.jsonl, out, project, fresh=args.fresh or not reuse)
    print(f"{'Updated' if reuse else 'Wrote'} {kept} records → {out}")
    if skipped:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(skipped.items()))
        print(f"Skipped {sum(skipped.values())} item(s): {breakdown}")
    return 0


# ── Export ────────────────────────────────────────────────────────────────
def _cmd_export(args: argparse.Namespace) -> int:
    from . import hf_export

    project = args.project
    if not project:
        raise SystemExit("export needs a project: pass -p <project>")
    if args.round is not None:
        dataset_dir = REVIEW_ROOT / f"{project}-r{args.round}"
    else:
        rounds = _round_dirs(project)
        if not rounds:
            raise SystemExit(
                f"no reviewed rounds found for '{project}' under {REVIEW_ROOT}/ — "
                f"run `paratext run -p {project}` and review it first"
            )
        dataset_dir = rounds[-1][1]
    if not (dataset_dir / "samples.json").is_file():
        raise SystemExit(f"not a packaged dataset: {dataset_dir}")

    cfg = hf_export.load_config(project, repo=args.to, public=args.public)
    summary = hf_export.run(dataset_dir, project, cfg, dry_run=args.dry_run)

    excluded = ", ".join(f"{k}={v}" for k, v in sorted(summary.excluded.items())) or "none"
    print(f"Dataset {summary.dataset}: {summary.gold} gold, {summary.negatives} negative(s)")
    print(f"Excluded: {excluded}")
    if args.dry_run:
        print(f"\nDry run — built {summary.build_dir} (not pushed). "
              f"Inspect it, then re-run without --dry-run to publish.")
    else:
        vis = "public" if cfg.public else "private"
        print(f"\nPushed {vis} dataset → {summary.url}")
    return 0


# ── Carbon ────────────────────────────────────────────────────────────────
def _cmd_carbon(args: argparse.Namespace) -> int:
    from . import carbon

    cfg = carbon.load_config(
        min_renewable=args.renewables_above, max_carbon=args.max_carbon
    )
    if args.window:
        forecast = carbon.forecast_for(cfg, cfg.window_hours)
        if not forecast:
            raise SystemExit(
                f"provider {cfg.provider!r} has no free forecast (try uk / energy-charts)"
            )
        block = max(1, round(cfg.window_run_hours * 60 / carbon._period_minutes(cfg)))
        i, _ = carbon.cleanest_window(forecast, block)
        print(f"Now:  {carbon.current_reading(cfg).summary()}")
        print(f"Greenest {cfg.window_run_hours:g}h window in next {cfg.window_hours}h: "
              f"{forecast[i].summary()} starting {forecast[i].ts}")
        return 0
    r = carbon.current_reading(cfg)
    print(r.summary())
    print(f"Target: {cfg.target_str()} — {'MET ✓' if cfg.is_clean(r) else 'not met'}")
    return 0


# ── Review ────────────────────────────────────────────────────────────────
def _cmd_review(args: argparse.Namespace) -> int:
    from .review import serve

    serve(args.data_dir, port=args.port, open_browser=not args.no_open)
    return 0


# ── Sample ────────────────────────────────────────────────────────────────
def _slug(name: str) -> str:
    s = re.sub(r"[()]", "", name)
    return re.sub(r"\s+", "-", s.strip())


def _cmd_sample(args: argparse.Namespace) -> int:
    """Symlink a flat directory of N random images out of a nested source tree."""
    src = args.source
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    images: list[Path] = []
    for sub in sorted(src.iterdir()):
        if not sub.is_dir():
            continue
        images.extend(sorted(sub.glob("*.jpg")))
        images.extend(sorted(sub.glob("*.jpeg")))

    rng = random.Random(args.seed)
    pick = rng.sample(images, min(args.n, len(images)))
    for path in pick:
        sid = f"{_slug(path.parent.name)}__{path.stem}"
        dst = out / f"{sid}.jpg"
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(path)
    print(f"Symlinked {len(pick)} of {len(images)} candidate image(s) into {out}")
    return 0


# ── Config ─────────────────────────────────────────────────────────────────
def _cmd_config(args: argparse.Namespace) -> int:
    """Open paratext.toml in $EDITOR, print resolved defaults (--show), or
    suggest a carbon region from IP geolocation (--suggest-region)."""
    if args.suggest_region:
        _suggest_carbon_region()
        return 0

    if args.show:
        resolved = coerce_paths(load_defaults(args.project))
        out = {
            "config": str(local_config_path()),
            "project": args.project,
            "resolved": {k: (str(v) if isinstance(v, Path) else v) for k, v in resolved.items()},
        }
        print(json.dumps(out, indent=2))
        return 0

    path = local_config_path()
    fresh = not path.exists()
    if fresh:
        path.write_text(CONFIG_TEMPLATE)
        print(f"Created {path} from the default template.")
        # Onboarding: offer (never force) carbon-aware scheduling on a new config.
        import sys

        if sys.stdin.isatty():
            ans = input("Detect your electricity grid region for greener scheduling? [y/N] ")
            if ans.strip().lower() in ("y", "yes"):
                try:
                    _suggest_carbon_region()
                except SystemExit as e:
                    print(e)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    subprocess.call([*editor.split(), str(path)])
    return 0


def _suggest_carbon_region() -> None:
    """IP-geolocate and append a suggested `[carbon]` block (confirm, don't detect)."""
    from . import carbon

    info = carbon.suggest_region()
    block = carbon.suggestion_toml(info)
    loc = ", ".join(x for x in (info.get("city"), info.get("country")) if x)
    print(f"Detected {loc} via IP (may reflect your ISP/host, not your site — confirm it).")
    if info.get("region_name"):
        print(f"UK grid region: {info['region_name']}")
    if info.get("note"):
        print(info["note"])
    print(f"\nSuggested config:\n\n{block}")

    path = local_config_path()
    if path.exists() and re.search(r"^\[carbon\]", path.read_text(), re.M):
        print(f"{path} already has a [carbon] section — not modifying it; "
              "paste the above to replace.")
    else:
        prefix = "" if path.exists() else "# paratext config\n"
        with path.open("a") as f:
            f.write(prefix + "\n" + block)
        print(f"Appended the [carbon] block to {path}.")


# ── New (scaffold a project) ────────────────────────────────────────────────
def _cmd_new(args: argparse.Namespace) -> int:
    from .scaffold import init

    return init(args.name, install=not args.no_install)


# ── Argparse wiring ───────────────────────────────────────────────────────
def _peek_project(argv: list[str] | None) -> str | None:
    """Find ``-p/--project <name>`` in argv before full parsing, so we can load
    the right TOML section before setting argparse defaults. Falls back to
    ``PARATEXT_PROJECT``."""
    import sys

    src = sys.argv[1:] if argv is None else argv
    for i, tok in enumerate(src):
        if tok in ("--project", "-p") and i + 1 < len(src):
            return src[i + 1]
        if tok.startswith("--project="):
            return tok.split("=", 1)[1]
    return os.environ.get("PARATEXT_PROJECT")


def _add_extract_args(p: argparse.ArgumentParser) -> None:
    """Shared --source/--model/… overrides for `extract` and `run`. Defaults
    flow in from the config/env layer; missing values are reported at runtime."""
    choices = project_names() or None
    p.add_argument("-p", "--project", choices=choices, default=None, help="Project plug-in to run")
    p.add_argument("--source", type=Path, default=None, help="Input directory (images or PDFs)")
    p.add_argument("--output", type=Path, default=None,
                   help="Output JSONL path (default: output/<project>.jsonl)")
    p.add_argument("--model", default=None, help="Model id served by the VLM endpoint")
    p.add_argument("--base-url", default=None, help="VLM endpoint base URL (OpenAI-compatible)")
    p.add_argument("--api-key", default=None, help="API key for the endpoint (often unused)")
    p.add_argument("--limit", type=int, default=None, help="Process at most N inputs")
    p.add_argument(
        "--no-structured",
        action="store_true",
        default=None,
        help="Disable Pydantic response_format (for models that don't support it)",
    )
    p.add_argument("--skip-preflight", action="store_true", default=None,
                   help="Skip the endpoint reachability/model check")
    p.add_argument("--green", action="store_true", default=None,
                   help="Wait for a clean grid before extracting (see [carbon] config)")
    p.add_argument("--renewables-above", type=float, default=None, metavar="PCT",
                   help="With --green: wait until renewables ≥ PCT%% (overrides config)")
    p.add_argument("--max-carbon", type=float, default=None, metavar="GCO2",
                   help="With --green: wait until intensity ≤ GCO2 gCO2/kWh (overrides config)")


def _build_parser() -> tuple[argparse.ArgumentParser, list[argparse.ArgumentParser]]:
    p = argparse.ArgumentParser(
        prog="paratext",
        description="VLM metadata-extraction pipeline for digitised collections.",
    )
    sub = p.add_subparsers(dest="cmd", metavar="<command>")
    choices = project_names() or None

    r = sub.add_parser("run", help="Extract then package in one go")
    _add_extract_args(r)
    r.add_argument("--review-out", type=Path, default=None,
                   help="Review dataset dir (overrides round auto-naming)")
    r.add_argument("--round", type=int, default=None,
                   help="Force review round N (default: auto — new round when the prompt changes)")
    r.add_argument("--fresh", action="store_true",
                   help="Rebuild the round dir from scratch, discarding its annotations")
    r.add_argument("--review", action="store_true",
                   help="Launch the review UI when the run finishes (blocks)")
    r.set_defaults(func=_cmd_run)

    e = sub.add_parser("extract", help="Run VLM extraction over a directory")
    _add_extract_args(e)
    e.set_defaults(func=_cmd_extract)

    pk = sub.add_parser("package", help="Convert extraction JSONL to a review dataset")
    pk.add_argument("jsonl", type=Path, help="Extraction JSONL produced by `extract`")
    pk.add_argument("-p", "--project", choices=choices, default=None,
                    help="Project plug-in (inferred from the JSONL if omitted)")
    pk.add_argument("--out", type=Path, default=None,
                    help="Output dir (default: the review/<project>-r<N> round for this prompt)")
    pk.add_argument("--round", type=int, default=None,
                    help="Force review round N (default: auto from the prompt hash)")
    pk.add_argument("--fresh", action="store_true",
                    help="Rebuild the output dir from scratch, discarding its annotations")
    pk.set_defaults(func=_cmd_package)

    ex = sub.add_parser("export", help="Publish a reviewed round as a Hugging Face dataset")
    ex.add_argument("-p", "--project", choices=choices, default=None, help="Project to export")
    ex.add_argument("--to", default=None,
                    help="HF repo id (org/name); default: export.repo in config")
    ex.add_argument("--round", type=int, default=None,
                    help="Review round to export (default: the latest)")
    ex.add_argument("--public", action="store_true",
                    help="Publish publicly (default: private; requires a license in config)")
    ex.add_argument("--dry-run", action="store_true",
                    help="Build the dataset folder locally without pushing")
    ex.set_defaults(func=_cmd_export)

    rv = sub.add_parser("review", help="Launch the local web UI to review datasets")
    rv.add_argument("data_dir", type=Path, nargs="?", default=REVIEW_ROOT,
                    help="A review root (default: ./review) or a single dataset dir")
    rv.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"Port to serve on (config review-port, else {DEFAULT_PORT})")
    rv.add_argument("--no-open", action="store_true", help="Don't open a browser")
    rv.set_defaults(func=_cmd_review)

    cb = sub.add_parser("carbon", help="Show current grid carbon/renewables (see [carbon] config)")
    cb.add_argument("--window", action="store_true",
                    help="Show the greenest forecast window instead of the current reading")
    cb.add_argument("--renewables-above", type=float, default=None, metavar="PCT",
                    help="Renewables threshold to test against (overrides config)")
    cb.add_argument("--max-carbon", type=float, default=None, metavar="GCO2",
                    help="Carbon-intensity threshold to test against (overrides config)")
    cb.set_defaults(func=_cmd_carbon)

    s = sub.add_parser("sample", help="Symlink a random subset of a nested image tree")
    s.add_argument("--source", type=Path, required=True, help="Root of the nested image tree")
    s.add_argument("--out", type=Path, required=True, help="Output dir for the symlinked subset")
    s.add_argument("-n", type=int, default=500, help="Number of images to pick (default: 500)")
    s.add_argument("--seed", type=int, default=20260506, help="Random seed (reproducible pick)")
    s.set_defaults(func=_cmd_sample)

    cfg = sub.add_parser("config", help="Open the config file (--show prints resolved defaults)")
    cfg.add_argument("-p", "--project", choices=choices, default=None,
                     help="Project to resolve defaults for (with --show)")
    cfg.add_argument("--show", action="store_true", help="Print resolved defaults instead")
    cfg.add_argument("--suggest-region", action="store_true",
                     help="Suggest a [carbon] grid region from IP geolocation")
    cfg.set_defaults(func=_cmd_config)

    nw = sub.add_parser("new", aliases=["init"], help="Scaffold a new project package")
    nw.add_argument("name", nargs="?", default=None, help="Project name")
    nw.add_argument("--no-install", action="store_true",
                    help="Scaffold only — don't edit pyproject.toml or run uv sync")
    nw.set_defaults(func=_cmd_new)

    sub.add_parser("help", help="Show this help message")

    # run/extract take the full layered config; review only needs the port.
    return p, [r, e], rv


def main(argv: list[str] | None = None) -> int:
    parser, config_subparsers, review_subparser = _build_parser()

    project = _peek_project(argv)
    layered = coerce_paths(load_defaults(project))
    merged = {**HARDCODED_DEFAULTS, **layered}
    if project is not None:
        merged.setdefault("project", project)
    for sp in config_subparsers:
        sp.set_defaults(**merged)
    # `paratext review --port` still overrides; otherwise use the configured port.
    review_subparser.set_defaults(port=merged["review_port"])

    args = parser.parse_args(argv)
    # Bare `paratext` or `paratext help` → show usage instead of erroring.
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
