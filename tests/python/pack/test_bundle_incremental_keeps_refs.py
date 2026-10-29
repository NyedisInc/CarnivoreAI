
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.core.pack.transport import bundles

SENDER = "iid-a"


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


def refs(repo: Path) -> list[str]:
    return git(repo, "for-each-ref", "--format=%(refname)", f"refs/carnivore/{SENDER}").splitlines()


def test_incremental_apply_keeps_refs_the_bundle_omits(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    git(src, "init", "-q", "-b", "main")
    commit(src, "a")
    git(src, "branch", "side")
    git(src, "tag", "v1")
    first = str(tmp_path / "first.bundle")
    tips = bundles.make_bundle(str(src), first, known_tips=[], air_gap=True)
    assert tips
    bundles.apply_bundle(str(dst), first, SENDER, air_gap=True)
    before = refs(dst)
    assert len(before) == 3

    commit(src, "b")
    second = str(tmp_path / "second.bundle")
    assert bundles.make_bundle(str(src), second, known_tips=tips, air_gap=True)
    assert bundles._has_prerequisites(second)
    assert not bundles._has_prerequisites(first)
    bundles.apply_bundle(str(dst), second, SENDER, air_gap=True)

    assert refs(dst) == before
