
from __future__ import annotations

import os

from src.core.claude_project_dirs import (
    candidate_project_dirs,
    path_spellings,
    same_directory,
)
from src.core.claude_transcript_correlate import slugify_project_dir


def test_slugify_maps_spaces_tildes_and_underscores():
    working = (
        "/Users/sam/Library/Mobile Documents/com~apple~CloudDocs"
        "/Sync/Development/Assistants/BHPP"
    )
    assert slugify_project_dir(working) == (
        "-Users-sam-Library-Mobile-Documents-com-apple-CloudDocs"
        "-Sync-Development-Assistants-BHPP"
    )


def test_slugify_maps_underscores_too():
    assert slugify_project_dir("/a/claude_4") == "-a-claude-4"


def test_slugify_keeps_the_documented_dot_behaviour():
    assert slugify_project_dir("/Users/x/.claude") == "-Users-x--claude"


def test_path_spellings_recovers_the_symlinked_spelling(tmp_path):
    home = tmp_path / "home"
    real = home / "Library" / "Sync" / "Development" / "Proj"
    real.mkdir(parents=True)
    link = home / "Development"
    link.symlink_to(home / "Library" / "Sync" / "Development")

    spellings = path_spellings(str(link / "Proj"), home=home)

    assert str(link / "Proj") in spellings
    assert os.path.realpath(str(real)) in [os.path.realpath(s) for s in spellings]
    assert len(spellings) >= 2


def test_candidate_project_dirs_finds_a_transcript_filed_under_either_spelling(
    tmp_path,
):
    home = tmp_path / "home"
    real = home / "Library" / "Sync" / "Development" / "Proj"
    real.mkdir(parents=True)
    link = home / "Development"
    link.symlink_to(home / "Library" / "Sync" / "Development")

    projects = tmp_path / "projects"
    projects.mkdir()
    short_dir = projects / slugify_project_dir(str(link / "Proj"))
    long_dir = projects / slugify_project_dir(str(real))
    short_dir.mkdir()
    long_dir.mkdir()

    found = candidate_project_dirs(
        str(real), projects_dir=projects, home=home
    )
    names = {p.name for p in found}

    assert short_dir.name in names, "the symlinked spelling was not searched"
    assert long_dir.name in names, "the resolved spelling was not searched"


def test_candidate_project_dirs_drops_directories_that_do_not_exist(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    assert candidate_project_dirs("/nowhere/at/all", projects_dir=projects) == []


def test_candidate_project_dirs_can_use_a_listing_from_another_machine(tmp_path):
    projects = tmp_path / "projects"
    found = candidate_project_dirs(
        "/Users/x/Proj",
        projects_dir=projects,
        existing=["-Users-x-Proj"],
    )
    assert [p.name for p in found] == ["-Users-x-Proj"]


def test_same_directory_sees_through_a_symlink(tmp_path):
    home = tmp_path / "home"
    real = home / "Library" / "Dev"
    real.mkdir(parents=True)
    link = home / "Dev"
    link.symlink_to(real)
    assert same_directory(str(link), str(real)) is True


def test_same_directory_refuses_two_genuinely_different_paths(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert same_directory(str(a), str(b)) is False
    assert same_directory(None, str(a)) is False


def test_home_alias_scan_is_cached_and_invalidated(tmp_path, monkeypatch):
    from src.core import claude_project_dirs as cpd

    home = tmp_path / "home"
    home.mkdir()
    (home / "real").mkdir()
    for i in range(300):
        (home / f"f{i}.txt").write_text("x")
    os.symlink(home / "real", home / "link1")

    calls = []
    real_listdir = os.listdir
    monkeypatch.setattr(cpd.os, "listdir", lambda p: (calls.append(p), real_listdir(p))[1])
    clock = [1000.0]
    monkeypatch.setattr(cpd, "_alias_clock", lambda: clock[0])

    first = cpd._home_dir_aliases(home=home)
    assert [l for l, _ in first] == [str(home / "link1")]
    first.append(("mutated", "x"))
    assert len(cpd._home_dir_aliases(home=home)) == 1
    assert len(calls) == 1

    (home / "real2").mkdir()
    os.symlink(home / "real2", home / "link2")
    assert len(cpd._home_dir_aliases(home=home)) == 2
    assert len(calls) == 2

    clock[0] += cpd.HOME_ALIAS_TTL_SECONDS + 1
    cpd._home_dir_aliases(home=home)
    assert len(calls) == 3
