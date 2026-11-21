
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.core.pack.transport import ladder

logger = structlog.get_logger()

FIRST_COMMIT_MESSAGE = "first commit"
PRIVATE_INDEX_SUFFIX = ".carnivore-publish"
LOCK_SUFFIX = ".lock"
GIT_TIMEOUT_S = 300.0
PUSH_TIMEOUT_S = 600.0
PUSH_CONFIG = (("push.followTags", "false"), ("push.recurseSubmodules", "no"))
PUSH_ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "SSH_AUTH_SOCK", "GIT_SSH", "GIT_SSH_COMMAND",
                 "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "XDG_CONFIG_HOME", "GH_CONFIG_DIR")
_GITHUB_URL = re.compile(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.IGNORECASE)


class GitStepFailed(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _git(root: str, *args: str, env: Optional[Dict[str, str]] = None, timeout: float = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    try:
        return ladder.run(["git", "-C", root, *args], air_gap=False, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GitStepFailed("git_failed", "a git step ran too long") from None


def identity_flags(root: str) -> List[str]:
    return [] if _git(root, "config", "user.email").stdout.strip() else ["-c", "user.name=Carnivore", "-c", "user.email=carnivore@localhost"]


class PrivateIndex:

    def __init__(self, root: str) -> None:
        done = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "index")
        index = done.stdout.decode("utf-8", "replace").strip()
        if done.returncode != 0 or not index:
            raise GitStepFailed("git_failed", "the git index could not be found")
        self.root, self.index = root, Path(index)
        self.copy = Path(index + PRIVATE_INDEX_SUFFIX)
        self.lock_path = Path(index + LOCK_SUFFIX)
        self.digest: Optional[str] = None
        self._lock_fd: Optional[int] = None

    def stage(self) -> str:
        env = {"GIT_INDEX_FILE": str(self.copy)}
        try:
            self.digest = _digest(self.index)
            if self.digest is None:
                self.copy.unlink(missing_ok=True)
            else:
                shutil.copy2(self.index, self.copy)
            added = _git(self.root, "add", "-A", env=env)
            written = _git(self.root, "write-tree", env=env) if added.returncode == 0 else added
        except OSError:
            self.discard()
            raise GitStepFailed("git_failed", "the git index could not be copied") from None
        tree = written.stdout.decode("ascii", "replace").strip()
        if written.returncode != 0 or not tree:
            self.discard()
            raise GitStepFailed("git_failed", "the first commit could not be staged")
        return tree

    def lock(self) -> None:
        try:
            self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise GitStepFailed("git_failed", "another git command holds the index lock") from None
        except OSError:
            raise GitStepFailed("git_failed", "the git index could not be locked") from None
        if _digest(self.index) != self.digest:
            self._release()
            raise GitStepFailed("git_failed", "the git index changed while the publish ran")

    def adopt(self) -> None:
        if self._lock_fd is None:
            raise GitStepFailed("git_failed", "the git index was not locked")
        try:
            with open(self.copy, "rb") as source, os.fdopen(self._lock_fd, "wb", closefd=False) as out:
                shutil.copyfileobj(source, out)
            os.fsync(self._lock_fd)
            os.close(self._lock_fd)
            self._lock_fd = None
            os.replace(self.lock_path, self.index)
        except OSError:
            self._release()
            raise GitStepFailed("git_failed", "the git index could not be updated") from None

    def _release(self) -> None:
        if self._lock_fd is None:
            return
        try:
            os.close(self._lock_fd)
            self.lock_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("pack_publish_index_lock_left", error_type=type(exc).__name__)
        self._lock_fd = None

    def discard(self) -> None:
        self._release()
        try:
            self.copy.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("pack_publish_private_index_left", error_type=type(exc).__name__)


def _digest(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def commit_scanned_tree(root: str, tree: str) -> str:
    made = ladder.run(["git", "-C", root, *identity_flags(root), "commit-tree", "--no-gpg-sign", "-m", FIRST_COMMIT_MESSAGE, tree],
                      air_gap=False, timeout=GIT_TIMEOUT_S)
    commit = made.stdout.decode("ascii", "replace").strip()
    if made.returncode != 0 or not commit:
        raise GitStepFailed("git_failed", "the first commit failed")
    if _git(root, "update-ref", "-m", f"publish: {FIRST_COMMIT_MESSAGE}", "HEAD", commit, "").returncode != 0:
        raise GitStepFailed("git_failed", "the branch changed while the first commit was made")
    return commit


def current_branch(root: str) -> str:
    done = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    name = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not name:
        raise GitStepFailed("detached_head", "the project is not on a branch")
    return name


def remote_matches(url: str, owner: str, name: str) -> bool:
    match = _GITHUB_URL.match(url.strip())
    return bool(match) and match.group(1).lower() == owner.lower() and match.group(2).lower() == name.lower()


def push_url(root: str) -> str:
    done = _git(root, "remote", "get-url", "--push", "origin")
    return done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else ""


def push_env(token: Dict[str, str]) -> Dict[str, str]:
    return {**{key: os.environ[key] for key in PUSH_ENV_KEEP if key in os.environ}, **token}


def push_argv(root: str, gh: str, commit: str, branch: str) -> List[str]:
    config = [part for key, value in PUSH_CONFIG for part in ("-c", f"{key}={value}")]
    helper = ["-c", "credential.helper=", "-c", f"credential.helper=!{shlex.quote(gh)} auth git-credential"]
    return ["git", "-C", root, *helper, *config, "push", "origin", f"{commit}:refs/heads/{branch}"]


def push_scanned(root: str, gh: str, commit: str, branch: str, token: Dict[str, str], *, owner: str, name: str) -> None:
    url = push_url(root)
    if not url:
        raise GitStepFailed("gh_failed", "gh created the repo but set up no remote")
    if not remote_matches(url, owner, name):
        logger.warning("pack_publish_remote_mismatch", owner=owner, name=name)
        raise GitStepFailed("remote_mismatch", "the push would go somewhere other than the new repo")
    try:
        done = ladder.run(push_argv(root, gh, commit, branch), air_gap=False, env=push_env(token), inherit_env=False,
                          timeout=PUSH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise GitStepFailed("gh_failed", "the push to the new repo ran too long") from None
    if done.returncode != 0:
        logger.warning("pack_publish_push_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        raise GitStepFailed("gh_failed", "the push to the new repo failed")
    tracked = _git(root, "branch", f"--set-upstream-to=origin/{branch}", branch)
    if tracked.returncode != 0:
        logger.warning("pack_publish_upstream_not_set", branch=branch, status=tracked.returncode)
