"""Top-level CLI wiring — the argparse surface a new user meets before any
project exists."""

from importlib.metadata import version

import pytest

import paratext
import paratext.cli as cli


@pytest.mark.parametrize("flag", ["-v", "--version"])
def test_version_flag_prints_version(flag, capsys):
    # argparse's version action exits 0 after printing.
    with pytest.raises(SystemExit) as exc:
        cli.main([flag])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"paratext {paratext.__version__}"


def test_version_matches_package_metadata():
    # __version__ and pyproject's version are separate declarations; keep them
    # honest so `paratext -v` can't report a stale number.
    assert paratext.__version__ == version("paratext")
