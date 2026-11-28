from __future__ import annotations

import subprocess

from scripts.gate import field_installs as fi

FLOOR_COMMITS = {"1.16.2": "f47b29b57d08725ecfb8b8267cbe8c220eb37d82"}


def _ensure_floor_tag() -> None:
    sha, tag = FLOOR_COMMITS.get(fi.FIELD_FLOOR), f"v{fi.FIELD_FLOOR}"
    if not sha:
        return
    git = lambda *a: subprocess.run(["git", *a], cwd=fi.REPO, capture_output=True, check=False)  # noqa: E731
    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode != 0 and git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        git("tag", tag, sha)


_ensure_floor_tag()
