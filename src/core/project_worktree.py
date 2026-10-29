
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import structlog

from src.core import config_writer
from src.core.dev_tools import git_guard

logger = structlog.get_logger()

CONFIG_KEY = "blueprints"
ROOT_FIELD = "worktree_root"

DEFAULT_ROOT = "~/dev-worktrees"

GIT_TIMEOUT_SECONDS = 180

SYSTEM_DIRS: Tuple[str, ...] = ("/", "/etc", "/usr", "/bin", "/sbin", "/var",
                                "/System", "/Library", "/private", "/tmp")


class WorktreeRefused(ValueError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class WorktreeTimeout(RuntimeError):
    pass


class GitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class WorktreePlan:

    repo: str
    base_branch: str
    branch: str
    path: str
    reuse: bool
    branch_exists: bool


def branch_slug(branch: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.")
    return slug or "branch"


def resolve_root(raw: str) -> Path:
    expanded = os.path.expanduser(str(raw).strip())
    if "\x00" in expanded or not os.path.isabs(expanded):
        raise WorktreeRefused("worktree_root_invalid",
                              "the worktree root must be an absolute path or start with ~")
    real = os.path.realpath(expanded)
    if real in {os.path.realpath(d) for d in SYSTEM_DIRS}:
        raise WorktreeRefused("worktree_root_invalid", f"{real!r} is a system directory")
    if real == os.path.realpath(os.path.expanduser("~")):
        raise WorktreeRefused("worktree_root_invalid",
                              "the home directory itself is not a worktree root")
    return Path(real)


def read_root(config_path: Path) -> str:
    try:
        document = config_writer.read_config(Path(config_path))
    except (FileNotFoundError, ValueError):
        return DEFAULT_ROOT
    block = document.get(CONFIG_KEY) if isinstance(document, dict) else None
    value = block.get(ROOT_FIELD) if isinstance(block, dict) else None
    return value if isinstance(value, str) and value.strip() else DEFAULT_ROOT


def set_root(config_path: Path, raw: str) -> str:
    value = str(raw).strip()
    resolve_root(value)

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block = config.get(CONFIG_KEY)
        block = dict(block) if isinstance(block, dict) else {}
        if block.get(ROOT_FIELD) == value:
            return None
        block[ROOT_FIELD] = value
        return {**config, CONFIG_KEY: block}

    config_writer.commit(Path(config_path).expanduser(), mutate)
    logger.info("blueprint_worktree_root_set")
    return value


async def run_git(args: Sequence[str], *,
                  timeout: float = GIT_TIMEOUT_SECONDS) -> Tuple[int, str, str]:
    if not git_guard.git_available():
        raise GitUnavailable("git is not installed on this machine")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL, env=env)
    except FileNotFoundError:
        raise GitUnavailable("git is not installed on this machine") from None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        logger.warning("blueprint_git_timeout", command=args[2] if len(args) > 2 else "")
        raise WorktreeTimeout(f"git timed out after {int(timeout)} seconds") from None
    return (proc.returncode or 0,
            (out or b"").decode("utf-8", "replace").strip(),
            (err or b"").decode("utf-8", "replace").strip())


async def check_branch_name(name: str) -> str:
    if not name or name.startswith("-"):
        raise WorktreeRefused("branch_invalid", f"{name!r} is not a branch name")
    code, _out, _err = await run_git(["check-ref-format", "--branch", name])
    if code != 0:
        raise WorktreeRefused("branch_invalid", f"git refuses {name!r} as a branch name")
    return name


async def _toplevel(directory: str) -> Optional[str]:
    code, out, _err = await run_git(["-C", directory, "rev-parse", "--show-toplevel"])
    return os.path.realpath(out) if code == 0 and out else None


async def _common_dir(directory: str) -> Optional[str]:
    code, out, _err = await run_git(
        ["-C", directory, "rev-parse", "--path-format=absolute", "--git-common-dir"])
    return os.path.realpath(out) if code == 0 and out else None


def _inside(child: str, parent: str) -> bool:
    return Path(child) == Path(parent) or Path(child).is_relative_to(Path(parent))


async def _is_this_worktree(target: str, repo: str, branch: str) -> bool:
    if await _toplevel(target) != target:
        return False
    if await _common_dir(target) != await _common_dir(repo):
        return False
    code, out, _err = await run_git(["-C", target, "symbolic-ref", "--quiet", "--short", "HEAD"])
    return code == 0 and out == branch


async def plan_worktree(repo_path: str, base_branch: str, branch: str, *,
                        root: str) -> WorktreePlan:
    repo = os.path.realpath(os.path.expanduser(repo_path))
    if not os.path.isdir(repo) or await _toplevel(repo) != repo:
        raise WorktreeRefused("not_a_repository",
                              f"{repo!r} is not the top level of a git repository")
    await check_branch_name(branch)
    await check_branch_name(base_branch)
    code, _out, _err = await run_git(
        ["-C", repo, "rev-parse", "--verify", "--quiet", "--end-of-options",
         f"{base_branch}^{{commit}}"])
    if code != 0:
        raise WorktreeRefused("base_branch_unknown",
                              f"{base_branch!r} names no commit in {repo!r}")
    code, _out, _err = await run_git(
        ["-C", repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    branch_exists = code == 0

    root_real = resolve_root(root)
    repo_name = os.path.basename(repo)
    target = os.path.realpath(root_real / repo_name / branch_slug(branch))
    if not _inside(target, str(root_real)) or target == str(root_real):
        raise WorktreeRefused("worktree_path_escapes",
                              f"the worktree path resolves outside {str(root_real)!r}")
    if _inside(target, repo):
        raise WorktreeRefused("worktree_path_escapes",
                              "the worktree would sit inside the repository itself")
    reuse = False
    if os.path.lexists(target):
        if not os.path.isdir(target) or not await _is_this_worktree(target, repo, branch):
            raise WorktreeRefused("worktree_path_taken",
                                  f"{target!r} already exists and is not this worktree")
        reuse = True
    return WorktreePlan(repo=repo, base_branch=base_branch, branch=branch, path=target,
                        reuse=reuse, branch_exists=branch_exists)


async def create_worktree(plan: WorktreePlan, *, root: str) -> bool:
    if plan.reuse:
        return False
    root_real = str(resolve_root(root))
    parent = os.path.dirname(plan.path)
    os.makedirs(parent, exist_ok=True)
    if os.path.realpath(parent) != parent or not _inside(parent, root_real):
        raise WorktreeRefused("worktree_path_escapes",
                              f"{parent!r} resolves outside {root_real!r}")
    if os.path.lexists(plan.path):
        raise WorktreeRefused("worktree_path_taken", f"{plan.path!r} appeared before the add")
    if plan.branch_exists:
        args = ["-C", plan.repo, "worktree", "add", "--", plan.path, plan.branch]
    else:
        args = ["-C", plan.repo, "worktree", "add", "-b", plan.branch, "--",
                plan.path, plan.base_branch]
    code, _out, err = await run_git(args)
    if code != 0:
        logger.warning("blueprint_worktree_failed", repo=plan.repo, code=code)
        raise WorktreeRefused("worktree_failed", f"git worktree add failed: {err[:500]}")
    logger.info("blueprint_worktree_created", repo=plan.repo, path=plan.path)
    return True
