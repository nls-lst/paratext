"""Installing the agent guide as a skill."""

from pathlib import Path

from paratext import skill


def test_skill_text_is_frontmatter_plus_the_guide():
    t = skill.skill_text()
    assert t.startswith("---\n")
    assert "name: paratext" in t
    # Frontmatter closes before the guide begins.
    body = t.split("---\n", 2)[2]
    assert "# paratext — agent guide" in body


def test_write_skill_creates_the_file(tmp_path):
    path = skill.write_skill(tmp_path / "paratext")
    assert path.name == "SKILL.md" and path.read_text().startswith("---")


def test_install_links_every_agent_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    home = tmp_path / "home"
    canonical, results = skill.install(home=home)

    assert (canonical / "SKILL.md").is_file()
    assert set(results.values()) == {"linked"}
    for rel in skill.AGENT_SKILL_DIRS:
        link = home / rel / "paratext"
        assert link.is_symlink() and (link / "SKILL.md").is_file()


def test_install_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    home = tmp_path / "home"
    skill.install(home=home)
    _, again = skill.install(home=home)
    assert set(again.values()) == {"already linked"}


def test_install_refuses_to_clobber_a_real_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    home = tmp_path / "home"
    squatter = home / skill.AGENT_SKILL_DIRS[0] / "paratext"
    squatter.mkdir(parents=True)
    (squatter / "SKILL.md").write_text("someone else's")

    _, results = skill.install(home=home)
    assert "skipped" in results[str(skill.AGENT_SKILL_DIRS[0])]
    assert (squatter / "SKILL.md").read_text() == "someone else's"


def test_install_replaces_a_link_pointing_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    home = tmp_path / "home"
    stale_target = tmp_path / "old-venv" / "paratext"
    stale_target.mkdir(parents=True)
    link = home / skill.AGENT_SKILL_DIRS[0] / "paratext"
    link.parent.mkdir(parents=True)
    link.symlink_to(stale_target, target_is_directory=True)

    canonical, results = skill.install(home=home)
    assert results[str(skill.AGENT_SKILL_DIRS[0])] == "linked"
    assert link.resolve() == canonical.resolve()


def test_uninstall_removes_links_but_keeps_the_canonical_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    home = tmp_path / "home"
    canonical, _ = skill.install(home=home)

    out = skill.uninstall(home=home)
    assert set(out.values()) == {"removed"}
    assert (canonical / "SKILL.md").is_file()
    for rel in skill.AGENT_SKILL_DIRS:
        assert not (home / rel / "paratext").exists()


def test_uninstall_leaves_a_real_directory_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    home = tmp_path / "home"
    theirs = home / skill.AGENT_SKILL_DIRS[1] / "paratext"
    theirs.mkdir(parents=True)
    out = skill.uninstall(home=home)
    assert out[str(skill.AGENT_SKILL_DIRS[1])] == "left alone — not a link"
    assert theirs.is_dir()


def test_canonical_dir_respects_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert skill.canonical_dir() == Path(tmp_path) / "paratext" / "skills" / "paratext"
