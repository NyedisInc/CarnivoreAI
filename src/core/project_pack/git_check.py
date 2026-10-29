
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List

import structlog

from src.core.dev_tools import git_guard
from src.core.project_pack import constants as K

logger = structlog.get_logger()


class GitReadError(Exception):
    pass


@dataclass
class RepoReport:

    path: str
    head: str = ""
    problems: List[str] = field(default_factory=list)
    local_only: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    remotes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {"path": self.path, "head": self.head, "ok": not self.problems, "problems": self.problems,
                "local_only": self.local_only, "warnings": self.warnings, "remotes": self.remotes}


def _git(repo: str, *args: str) -> str:
    if not git_guard.git_available():
        raise GitReadError("git is not installed on this machine")
    try:
        done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                              timeout=K.GIT_TIMEOUT_SECONDS, env={**os.environ, **K.GIT_ENV}, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitReadError(f"git {args[0]} did not run in {repo}: {exc}") from exc
    if done.returncode != 0:
        raise GitReadError(f"git {args[0]} failed in {repo}: {done.stderr.strip()[:200]}")
    return done.stdout


def find_repos(root: str) -> List[str]:
    found: List[str] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in K.GIT_SKIP_DIRS and d != ".git"]
        if ".git" in files or os.path.isdir(os.path.join(current, ".git")):
            found.append(os.path.relpath(current, root))
    return sorted(found)


def inspect_repo(root: str, rel: str) -> RepoReport:
    report = RepoReport(path=rel)
    repo = os.path.join(root, rel) if rel != "." else root
    if os.path.isfile(os.path.join(repo, ".git")):
        report.problems.append("a linked worktree (its .git is a file pointing elsewhere); pack refuses it")
        return report
    try:
        _measure(repo, root, report)
    except GitReadError as exc:
        report.problems.append(f"could not read git state: {exc}")
    return report


def _measure(repo: str, root: str, report: RepoReport) -> None:
    head = _git(repo, "rev-parse", "--verify", "-q", "HEAD") if _has_commits(repo) else ""
    report.head = head.strip()
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=no").strip():
        report.problems.append("modified or staged tracked files")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard").strip()
    if untracked:
        report.warnings.append(f"{len(untracked.splitlines())} untracked files (kept inside the archive)")
    if _git(repo, "stash", "list").strip():
        report.problems.append("a stash entry")
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            other = os.path.realpath(line[len("worktree "):])
            if other != os.path.realpath(repo) and not other.startswith(os.path.realpath(root) + os.sep):
                report.problems.append(f"a worktree outside the folder: {other}")
    report.remotes = _git(repo, "remote").split()
    if not report.head:
        return
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)\t%(upstream:short)", "refs/heads").splitlines()
    if not report.remotes:
        report.local_only.append("no remote: the archive will be the only copy of this repository")
    for line in branches:
        name, _, upstream = line.partition("\t")
        if upstream:
            ahead = int(_git(repo, "rev-list", "--count", f"{upstream}..{name}").strip() or 0)
            if ahead:
                report.problems.append(f"branch {name} is {ahead} commit(s) ahead of {upstream}")
        elif report.remotes and _git(repo, "rev-list", "--count", name, "--not", "--remotes").strip() != "0":
            report.local_only.append(f"branch {name} has no upstream and commits no remote has")


def _has_commits(repo: str) -> bool:
    try:
        _git(repo, "rev-parse", "--verify", "-q", "HEAD")
        return True
    except GitReadError:
        return False


def inspect_all(root: str) -> List[RepoReport]:
    return [inspect_repo(root, rel) for rel in find_repos(root)]
