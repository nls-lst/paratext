"""`paratext` CLI — one command for the whole pipeline.

Subcommands:
    run         Extract then package in one go (the common path).
    extract     Run the VLM over a directory of inputs, write JSONL.
    package     Convert JSONL into a review dataset (samples.json + images/).
    review      Launch the local web UI to review a packaged dataset.
    sample      Build a random N-image subset of a source directory (helper).
    config      Open the config file (``--show`` prints the resolved defaults).
    init        Scaffold a new project package (interactive).

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
    coerce_paths,
    load_defaults,
    local_config_path,
)
from .extract import run as run_extract
from .packaging import package
from .projects import get_project, project_names

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
    "no_structured": False,
    "skip_preflight": False,
}


def _do_extract(args: argparse.Namespace) -> None:
    missing = [
        flag
        for flag, val in (
            ("--project", args.project),
            ("--source", args.source),
            ("--output", args.output),
            ("--model", args.model),
        )
        if val is None
    ]
    if missing:
        raise SystemExit(
            f"missing required value(s): {', '.join(missing)}\n"
            f"  pass on the CLI, set PARATEXT_<NAME>, or add to paratext.toml"
        )
    run_extract(
        get_project(args.project),
        source=Path(args.source),
        output=Path(args.output),
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        limit=args.limit,
        use_structured=not args.no_structured,
        skip_preflight=args.skip_preflight,
    )


# ── Extract ───────────────────────────────────────────────────────────────
def _cmd_extract(args: argparse.Namespace) -> int:
    _do_extract(args)
    print(f"Wrote extractions to {args.output}")
    return 0


# ── Run (extract + package) ────────────────────────────────────────────────
def _cmd_run(args: argparse.Namespace) -> int:
    _do_extract(args)
    review_out = args.review_out or Path(args.output).with_name(f"{args.project}-review")
    kept, skipped = package(Path(args.output), Path(review_out), args.project, fresh=True)
    print(f"Wrote extractions to {args.output}")
    print(f"Packaged {kept} record(s) to {review_out / 'samples.json'}")
    if skipped:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(skipped.items()))
        print(f"Skipped {sum(skipped.values())} item(s): {breakdown}")
    return 0


# ── Package ───────────────────────────────────────────────────────────────
def _cmd_package(args: argparse.Namespace) -> int:
    kept, skipped = package(args.jsonl, args.out, args.project, fresh=args.fresh)
    print(f"Wrote {kept} records to {args.out / 'samples.json'}")
    if skipped:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(skipped.items()))
        print(f"Skipped {sum(skipped.values())} item(s): {breakdown}")
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
    """Open paratext.toml in $EDITOR, or print the resolved defaults with --show."""
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
    if not path.exists():
        path.write_text("# paratext config — see `paratext config --show` for resolved values\n")
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    subprocess.call([*editor.split(), str(path)])
    return 0


# ── Init ───────────────────────────────────────────────────────────────────
def _cmd_init(args: argparse.Namespace) -> int:
    from .scaffold import init

    return init(args.name)


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
    p.add_argument("-p", "--project", choices=choices, default=None)
    p.add_argument("--source", type=Path, default=None, help="Input directory")
    p.add_argument("--output", type=Path, default=None, help="Output JSONL path")
    p.add_argument("--model", default=None, help="Model id served by the VLM endpoint")
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--limit", type=int, default=None, help="Process at most N inputs")
    p.add_argument(
        "--no-structured",
        action="store_true",
        default=None,
        help="Disable Pydantic response_format (for models that don't support it)",
    )
    p.add_argument("--skip-preflight", action="store_true", default=None)


def _build_parser() -> tuple[argparse.ArgumentParser, list[argparse.ArgumentParser]]:
    p = argparse.ArgumentParser(prog="paratext")
    sub = p.add_subparsers(dest="cmd", required=True)
    choices = project_names() or None

    r = sub.add_parser("run", help="Extract then package in one go")
    _add_extract_args(r)
    r.add_argument("--review-out", type=Path, default=None, help="Review dataset dir")
    r.set_defaults(func=_cmd_run)

    e = sub.add_parser("extract", help="Run VLM extraction over a directory")
    _add_extract_args(e)
    e.set_defaults(func=_cmd_extract)

    pk = sub.add_parser("package", help="Convert extraction JSONL to a review dataset")
    pk.add_argument("jsonl", type=Path)
    pk.add_argument("-p", "--project", choices=choices, default=None)
    pk.add_argument("--out", type=Path, required=True)
    pk.add_argument("--fresh", action="store_true")
    pk.set_defaults(func=_cmd_package)

    rv = sub.add_parser("review", help="Launch the local web UI to review a dataset")
    rv.add_argument("data_dir", type=Path, nargs="?", default=Path.cwd(),
                    help="A packaged dataset dir (or a parent holding several)")
    rv.add_argument("--port", type=int, default=5050)
    rv.add_argument("--no-open", action="store_true", help="Don't open a browser")
    rv.set_defaults(func=_cmd_review)

    s = sub.add_parser("sample", help="Symlink a random subset of a nested image tree")
    s.add_argument("--source", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("-n", type=int, default=500)
    s.add_argument("--seed", type=int, default=20260506)
    s.set_defaults(func=_cmd_sample)

    cfg = sub.add_parser("config", help="Open the config file (--show prints resolved defaults)")
    cfg.add_argument("-p", "--project", choices=choices, default=None)
    cfg.add_argument("--show", action="store_true", help="Print resolved defaults instead")
    cfg.set_defaults(func=_cmd_config)

    ini = sub.add_parser("init", help="Scaffold a new project package")
    ini.add_argument("name", nargs="?", default=None, help="Project name")
    ini.set_defaults(func=_cmd_init)

    return p, [r, e]  # the subparsers that take layered config defaults


def main(argv: list[str] | None = None) -> int:
    parser, config_subparsers = _build_parser()

    project = _peek_project(argv)
    layered = coerce_paths(load_defaults(project))
    merged = {**HARDCODED_DEFAULTS, **layered}
    if project is not None:
        merged.setdefault("project", project)
    for sp in config_subparsers:
        sp.set_defaults(**merged)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
