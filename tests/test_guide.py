"""`paratext guide` prints the packaged agent guide + installed projects, so an
agent that finds the CLI on PATH can self-orient without the source checkout."""

from importlib.resources import files

import paratext.cli as cli


def test_guide_is_packaged_as_a_resource():
    # Bundled inside the package (repo-root AGENTS.md symlinked in) so it resolves
    # via importlib.resources in both editable and wheel installs.
    text = (files("paratext") / "AGENTS.md").read_text(encoding="utf-8")
    assert text.lstrip().startswith("# paratext — agent guide")


def test_guide_prints_guide_and_projects(capsys):
    rc = cli.main(["guide"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "# paratext — agent guide" in out
    assert "## Installed projects" in out
    # The bundled `card-template` example registers via the paratext.projects
    # group. Match the run line, not the bare name — the guide prose mentions
    # "cards" independently, so a loose check passes even when discovery breaks.
    assert "paratext run -p card-template" in out


def test_help_points_agents_at_guide(capsys):
    # A cold agent's first move is `--help`; it must advertise the guide.
    parser, *_ = cli._build_parser()
    assert "paratext guide" in (parser.epilog or "")
