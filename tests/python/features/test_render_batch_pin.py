
from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


@pytest.fixture(scope="module")
def features():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("features_under_test", SCRIPTS / "features.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(repo: Path, *args: str, when: int = 0) -> None:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_AUTHOR_DATE": f"{1600000000 + when} +0000", "GIT_COMMITTER_DATE": f"{1600000000 + when} +0000", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(repo)}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _commit(repo: Path, msg: str, when: int) -> None:
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", msg, when=when)


def body(name: str) -> str:
    return "\n".join(f"{name} line {i}: {name[::-1]} {i * 7919} text" for i in range(12)) + "\n"


@pytest.fixture()
def world(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "features" / "changes").mkdir(parents=True)
    (repo / "other").mkdir()
    _run(repo, "init", "-q", "-b", "main")
    ch = repo / "features" / "changes"
    (repo / "README").write_text("x\n")
    (repo / "other" / "outside.json").write_text(body("outside"))
    _commit(repo, "seed", 1000)
    (ch / "plain.json").write_text(body("plain"))
    _commit(repo, "add plain", 2000)
    (ch / "edited.json").write_text(body("edited"))
    _commit(repo, "add edited", 3000)
    (ch / "edited.json").write_text(body("edited") + "more\n")
    (ch / "before.json").write_text(body("before"))
    _commit(repo, "edit edited, add before", 4000)
    _run(repo, "tag", "v1.0.0")
    _run(repo, "mv", "features/changes/before.json", "features/changes/after.json")
    _commit(repo, "rename inside", 5000)
    _run(repo, "mv", "other/outside.json", "features/changes/moved_in.json")
    _commit(repo, "rename in from outside", 6000)
    _run(repo, "tag", "v1.1.0")
    (ch / "untagged.json").write_text(body("untagged"))
    _commit(repo, "after every tag", 7000)
    (ch / "dirty.json").write_text(body("dirty"))
    return repo


def _reference(features, repo: Path, paths: list[Path]) -> dict[Path, tuple[str | None, str]]:
    tags = sorted((t for t in features._git(repo, "tag", "--list", "v*").stdout.splitlines() if t.strip()), key=features._version_key)
    out = {}
    for p in paths:
        commit = features._added_commit(repo, p)
        out[p] = (features._landed_at(repo, commit) if commit else None, features._release_for(repo, commit, tags) if commit else "Unreleased")
    return out


def _entries(repo: Path) -> list[tuple[Path, dict]]:
    return [(p, {}) for p in sorted((repo / "features" / "changes").glob("*.json"))]


def test_batched_results_equal_the_per_entry_reference(features, world):
    changes = _entries(world)
    want = _reference(features, world, [p for p, _ in changes])
    releases = features.group_by_release(world, changes)
    got = {}
    for name, entries in releases.items():
        for e in entries:
            got[id(e)] = (e.get("landed_at"), name)
    for p, e in changes:
        assert got[id(e)] == want[p], p.name
    assert len(want) == 6
    assert {p.name: w[1] for p, w in want.items()}["moved_in.json"] == "v1.0.0"


def test_without_the_outside_rename_fallback_the_pin_goes_red(features, world, monkeypatch):
    real = features._added_commits
    monkeypatch.setattr(features, "_added_commits", lambda repo, paths: (real(repo, paths)[0], set()))
    changes = _entries(world)
    want = _reference(features, world, [p for p, _ in changes])
    features.group_by_release(world, changes)
    differs = [p.name for (p, e) in changes if (e.get("landed_at"), None)[0] != want[p][0]]
    assert differs == ["moved_in.json"]


def test_a_failing_git_raises_instead_of_reading_unreleased(features, world, monkeypatch):
    real = features._git

    def failing(repo, *args, **kw):
        if args[:1] in (("log",), ("rev-list",), ("diff-tree",)):
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: stubbed failure")
        return real(repo, *args, **kw)

    monkeypatch.setattr(features, "_git", failing)
    with pytest.raises(RuntimeError, match="stubbed failure"):
        features.group_by_release(world, _entries(world))
