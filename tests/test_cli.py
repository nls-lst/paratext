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
    # honest so `paratext -v` can't report a stale number. NB the distribution is
    # `paratext-cli` while the import package is `paratext` — the plain name on
    # PyPI is an unrelated project.
    assert paratext.__version__ == version("paratext-cli")


def test_broken_project_reports_clearly_not_a_traceback(monkeypatch):
    # A registered-but-unimportable project used to raise ImportError straight
    # through argparse — the first thing a new user sees after `paratext new`
    # writes a module outside the installed package.
    from paratext import projects

    class _Ghost:
        name = "ghost"
        value = "ghost_mod:PROJECT"

        def load(self):
            raise ImportError("No module named 'ghost_mod'")

    monkeypatch.setattr(projects, "_entry_points", lambda: {"ghost": _Ghost()})
    with pytest.raises(ValueError, match="registered but its module 'ghost_mod'"):
        projects.get_project("ghost")


def test_unknown_project_hints_at_uv_run(tmp_path, monkeypatch):
    # The failure a new user hits: `paratext` installed globally (uv tool) can't
    # see a project installed in the working directory's .venv. argparse's
    # "invalid choice" gave no way to work that out.
    import argparse

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".venv").mkdir()
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        cli._project_arg("my-cards")
    msg = str(exc.value)
    assert "unknown project 'my-cards'" in msg
    assert "uv run paratext" in msg


def test_unknown_project_without_a_venv_omits_the_hint(tmp_path, monkeypatch):
    import argparse

    monkeypatch.chdir(tmp_path)  # no .venv here
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        cli._project_arg("my-cards")
    assert "uv run paratext" not in str(exc.value)


def test_known_project_passes_through():
    assert cli._project_arg("card-template") == "card-template"
