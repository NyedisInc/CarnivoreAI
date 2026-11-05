from __future__ import annotations

import subprocess
from pathlib import Path


class ChangedPathsError(RuntimeError):
    pass


def _git_paths(repo: Path, *args: str) -> set[str]:
    done = subprocess.run(["git", *args, "-z"], cwd=repo, capture_output=True)
    if done.returncode != 0:
        detail = done.stderr.decode(errors="replace").strip()
        raise ChangedPathsError(f"git {' '.join(args)} failed: {detail}")
    return {p for p in done.stdout.decode("utf-8", errors="surrogateescape").split("\0") if p}


def changed_paths(repo: Path, base: str) -> list[str]:
    paths = _git_paths(repo, "diff", "--name-only", f"{base}...HEAD")
    paths |= _git_paths(repo, "diff", "--name-only", "HEAD")
    paths |= _git_paths(repo, "ls-files", "--others", "--exclude-standard")
    return sorted(paths)
