from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core import project_worktree
from src.core.worktrees import repo_file
from src.core.worktrees.store import WorktreeStore

logger = structlog.get_logger()


@dataclass
class Prepared:

    path: str
    repo: str
    branch: str
    created: bool
    copied: List[str] = field(default_factory=list)
    setup_log: Optional[str] = None


async def current_branch(repo: str) -> Optional[str]:
    code, out, _err = await project_worktree.run_git(["-C", repo, "symbolic-ref", "--quiet", "--short", "HEAD"])
    return out if code == 0 and out else None


async def probe(folder: str, store: WorktreeStore) -> Dict[str, Any]:
    real = os.path.realpath(os.path.expanduser(folder))
    try:
        code, top, _err = await project_worktree.run_git(["-C", real, "rev-parse", "--show-toplevel"])
    except (project_worktree.GitUnavailable, project_worktree.WorktreeTimeout):
        return {"repo": False}
    if code != 0 or not top or os.path.realpath(top) != real:
        return {"repo": False}
    code, out, _err = await project_worktree.run_git(
        ["-C", real, "for-each-ref", "--format=%(refname:short)", "--sort=-committerdate", "refs/heads"])
    branches = [b for b in out.splitlines() if b][:50] if code == 0 else []
    answer: Dict[str, Any] = {"repo": True, "toplevel": real, "branches": branches,
                              "current": await current_branch(real), "file": None, "file_error": None}
    try:
        parsed = repo_file.read_repo_file(real)
    except repo_file.RepoFileRefused as exc:
        answer["file_error"] = str(exc)
        parsed = None
    if parsed is not None:
        answer["file"] = {
            "sha256": parsed.sha256, "setup": [list(s) for s in parsed.setup], "text": parsed.text,
            "copy": [{"name": n, "secret": repo_file.looks_secret(n)} for n in parsed.copy],
            "approved": store.is_approved(real, parsed.sha256),
        }
    return answer


async def prepare(repo_dir: str, branch: str, base_branch: Optional[str], setup: bool, copy: List[str], *,
                  root: str, store: WorktreeStore, state_dir: Path) -> Prepared:
    repo = os.path.realpath(os.path.expanduser(repo_dir))
    base = base_branch or await current_branch(repo)
    if not base:
        raise project_worktree.WorktreeRefused("base_branch_unknown", "the repository is on no branch; pick a base branch")
    plan = await project_worktree.plan_worktree(repo, base, branch, root=root)
    parsed = repo_file.read_repo_file(repo) if (setup or copy) else None
    if setup:
        if parsed is None or not parsed.setup:
            raise repo_file.RepoFileRefused("setup_missing", f"{repo_file.RELATIVE_PATH} has no setup steps")
        if not store.is_approved(repo, parsed.sha256):
            raise repo_file.RepoFileRefused("setup_unapproved",
                                            f"{repo_file.RELATIVE_PATH} changed or was never approved; approve it first")
    for name in copy:
        repo_file.check_copy(repo, name)
    created = await project_worktree.create_worktree(plan, root=root)
    if created:
        store.record(plan.path, repo, branch, base)
    done = Prepared(path=plan.path, repo=repo, branch=branch, created=created)
    done.copied = repo_file.copy_files(repo, plan.path, copy) if copy else []
    if setup and parsed is not None:
        tail = await repo_file.run_setup(parsed.setup, plan.path)
        log_dir = Path(state_dir) / "worktree-setup"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f"{os.path.basename(repo)}-{project_worktree.branch_slug(branch)}.log"
        log.write_text(tail, encoding="utf-8")
        done.setup_log = str(log)
    logger.info("worktree_launch_prepared", repo=repo, path=plan.path, created=created, copied=len(done.copied),
                setup=bool(setup))
    return done
