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


def test_delegate_is_a_noop_without_a_venv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli._delegate_to_project_venv()  # must simply return, not exec


def _fake_venv(root, *, with_paratext=True, script=True):
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    if script:
        (venv / "bin" / "paratext").write_text("")
    if with_paratext:
        (venv / "lib" / "python3.13" / "site-packages" / "paratext").mkdir(parents=True)
    return venv


def test_delegate_skips_a_venv_without_paratext(tmp_path, monkeypatch):
    # Execing into an interpreter that can't run this command would be worse
    # than not finding the project.
    monkeypatch.chdir(tmp_path)
    _fake_venv(tmp_path, with_paratext=False)
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(a))
    cli._delegate_to_project_venv()
    assert called == []


def test_delegate_respects_the_opt_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PARATEXT_NO_DELEGATE", "1")
    _fake_venv(tmp_path)
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(a))
    cli._delegate_to_project_venv()
    assert called == []


def test_delegate_execs_into_a_project_venv(tmp_path, monkeypatch):
    import sys

    monkeypatch.chdir(tmp_path)
    for var in ("PARATEXT_NO_DELEGATE", "_PARATEXT_DELEGATED", "VIRTUAL_ENV"):
        monkeypatch.delenv(var, raising=False)
    venv = _fake_venv(tmp_path)
    called = []
    monkeypatch.setattr(cli.os, "execv", lambda *a: called.append(a))
    monkeypatch.setattr(sys, "argv", ["paratext", "inspect"])
    cli._delegate_to_project_venv()
    assert called, "expected an exec into the project venv"
    assert called[0][0] == str(venv / "bin" / "paratext")
    assert called[0][1][1:] == ["inspect"]
