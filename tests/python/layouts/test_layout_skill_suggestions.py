from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.layouts import skill_suggestions as sug
from src.core import slash_command_discovery as scd


def _skill(root, name, desc):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\nSECRET BODY\n")


@pytest.fixture()
def homes(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    monkeypatch.setattr(scd, "CLAUDE_HOME", home)
    _skill(home / "skills", "gskill", "a global one")
    _skill(tmp_path / "codex" / "skills", "cskill", "a codex one")
    return home, tmp_path / "codex" / "skills"


def test_global_plus_intersection_of_project_skills(tmp_path, homes):
    home, codex = homes
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        _skill(d / ".claude" / "skills", "shared", "in both")
        _skill(d / ".agents" / "skills", "cshared", "in both")
    _skill(a / ".claude" / "skills", "only-a", "just a")
    _skill(b / ".claude" / "skills", "gskill", "dup of a global")
    out = sug.suggest("/", working_dirs=[str(a), str(b)], claude_home=home, codex_skills_root=codex)
    by = {e["name"]: e for e in out}
    assert set(by) == {"gskill", "shared"}
    assert by["gskill"]["scope"] == "global" and by["shared"]["scope"] == "project"
    assert set(by["shared"]) == {"name", "description", "scope"}
    assert by["shared"]["description"] == "in both"
    dollar = sug.suggest("$", working_dirs=[str(a), str(b)], claude_home=home, codex_skills_root=codex)
    assert {e["name"] for e in dollar} == {"cskill", "cshared"}
    with pytest.raises(ValueError):
        sug.suggest("!", working_dirs=[])


def test_targets_are_the_toggled_on_live_members(tmp_path):
    def m(rid, pos, on):
        return SimpleNamespace(session_row_id=rid, position=pos, broadcast=on)

    def i(rid, status, wd):
        return SimpleNamespace(session_row_id=rid, activity_status=status, session=SimpleNamespace(working_dir=wd))

    layout = SimpleNamespace(members=[m(1, 0, True), m(2, 1, False), m(3, 2, True), m(4, 3, True)])
    infos = [i(1, "idle", "/w1"), i(2, "idle", "/w2"), i(3, "dead", "/w3")]
    assert sug.target_working_dirs(layout, infos) == ["/w1"]


def test_global_skills_are_per_receiving_profile(tmp_path, homes):
    home, codex = homes
    p1, p2 = tmp_path / "acct1", tmp_path / "acct2"
    for p in (p1, p2):
        _skill(p / "skills", "both", "in both profiles")
    _skill(p1 / "skills", "only-p1", "one profile")
    _skill(p2 / "plugins" / "cache" / "mk" / "pl" / "1.0" / "skills", "plug2", "plugin in p2")
    wd = [str(tmp_path / "a"), str(tmp_path / "b")]
    names = lambda **kw: {e["name"] for e in sug.suggest("/", working_dirs=wd, claude_home=home,
                                                        codex_skills_root=codex, **kw)}
    assert names(profile_dirs=[str(p1), str(p2)]) == {"both"}
    assert names(profile_dirs=[str(p1)]) == {"both", "only-p1"}
    assert names(profile_dirs=[str(p1), None]) == set()
    assert names(profile_dirs=[None, None]) == {"gskill"}
    assert names(profile_dirs=[str(p2)]) == {"both", "plug2"}
    _skill(tmp_path / "ch1" / "skills", "cx", "x")
    dollar = sug.suggest("$", working_dirs=wd, codex_skills_root=codex,
                         profile_dirs=[str(tmp_path / "ch1"), None])
    assert dollar == []
