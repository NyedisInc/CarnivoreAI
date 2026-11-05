
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
import time
import uuid as uuid_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.checkpoints import shadow as shadow_mod
from src.core.checkpoints.store import KIND_TURN, Checkpoint, CheckpointStore
from src.core.session_git.secret_names import is_secret_path
from src.core.swarm.gitrun import _filter_flags, run_git

logger = structlog.get_logger()

MAX_FILE_BYTES = 20 * 1024 * 1024
SLOW_MS = 5000
SCRATCH_DIRNAME = "scratch"
_IDENTITY = ("-c", "user.name=Carnivore", "-c", "user.email=checkpoint@carnivore.invalid", "-c", "gc.auto=0")
REF_PREFIX = "refs/checkpoints/"

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass
class CaptureResult:

    checkpoint: Optional[Checkpoint] = None
    skipped: Optional[str] = None
    ms: int = 0
    left_out: List[str] = field(default_factory=list)


def repo_lock(shadow: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(shadow), threading.Lock())


def ref_name(session_uuid: str, prompt_uuid: str, kind: str = KIND_TURN) -> str:
    safe = lambda v: "".join(c if c.isalnum() or c in "-_" else "_" for c in v)  # noqa: E731
    return f"{REF_PREFIX}{safe(session_uuid)}/{kind}/{safe(prompt_uuid)}"


def _is_denied(rel: str) -> bool:
    return is_secret_path(rel) or any("credentials" in part.lower() for part in rel.split("/"))


def _too_big(top: Path, rel: str) -> bool:
    try:
        return os.lstat(top / rel).st_size > MAX_FILE_BYTES
    except OSError:
        return False


def _git(paths: shadow_mod.RepoPaths, index: Optional[Path], blank: List[str], *args: str,
         timeout: float) -> "subprocess.CompletedProcess[str]":
    env = {"GIT_INDEX_FILE": str(index)} if index is not None else None
    return run_git(paths.work_tree, *_IDENTITY, *blank, f"--git-dir={paths.shadow}", f"--work-tree={paths.work_tree}", *args,
                   timeout=timeout, untrusted_repo=True, extra_env=env, low_priority=True)


def _split(out: str) -> List[str]:
    return [p for p in out.split("\0") if p]


def _uses_filters(paths: shadow_mod.RepoPaths) -> bool:
    listed = run_git(paths.work_tree, "ls-files", "-z", timeout=shadow_mod.GIT_TIMEOUT_S, optional_locks=False,
                     untrusted_repo=True)
    files = [paths.work_tree / p for p in _split(listed.stdout) if p == ".gitattributes" or p.endswith("/.gitattributes")]
    files.append(paths.common_dir / "info" / "attributes")
    for f in files:
        try:
            if "filter=" in f.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def _left_out(paths: shadow_mod.RepoPaths, index: Path, blank: List[str], deadline: float) -> Tuple[List[str], List[str]]:
    shadow_mod.write_excludes(paths, [])
    others = _git(paths, index, blank, "ls-files", "--others", "--exclude-standard", "-z", timeout=max(1.0, deadline - time.monotonic()))
    if others.returncode != 0:
        raise OSError("ls-files failed")
    untracked = [p for p in _split(others.stdout) if _is_denied(p) or _too_big(paths.work_tree, p)]
    changed = _git(paths, index, blank, "diff-files", "--name-only", "-z", timeout=max(1.0, deadline - time.monotonic()))
    if changed.returncode not in (0, 1):
        raise OSError("diff-files failed")
    big_tracked = [p for p in _split(changed.stdout) if _too_big(paths.work_tree, p)]
    return untracked, big_tracked


def _left(deadline: float) -> float:
    return max(1.0, deadline - time.monotonic())


def _build_tree(paths: shadow_mod.RepoPaths, blank: List[str], deadline: float) -> Tuple[str, List[str], List[str]]:
    scratch = paths.shadow.parent / SCRATCH_DIRNAME
    index = scratch / f"idx-{os.getpid()}-{uuid_module.uuid4().hex}"
    try:
        scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        if paths.index.is_file():
            shutil.copyfile(paths.index, index)
        untracked_out, big_tracked = _left_out(paths, index, blank, deadline)
        shadow_mod.write_excludes(paths, untracked_out)
        if big_tracked:
            skip = run_git(paths.work_tree, f"--git-dir={paths.shadow}", f"--work-tree={paths.work_tree}",
                           "update-index", "--skip-worktree", "--", *big_tracked, timeout=shadow_mod.GIT_TIMEOUT_S,
                           untrusted_repo=True, extra_env={"GIT_INDEX_FILE": str(index)})
            if skip.returncode != 0:
                raise OSError("update-index failed")
        if _git(paths, index, blank, "add", "-A", timeout=_left(deadline)).returncode != 0:
            raise OSError("add failed")
        tree = _git(paths, index, blank, "write-tree", timeout=_left(deadline))
        if tree.returncode != 0 or not tree.stdout.strip():
            raise OSError("write-tree failed")
        return tree.stdout.strip(), untracked_out, big_tracked
    finally:
        for leftover in (index, Path(str(index) + ".lock")):
            try:
                leftover.unlink()
            except FileNotFoundError:
                pass


def tree_now(paths: shadow_mod.RepoPaths) -> Tuple[str, List[str]]:
    shadow_mod.ensure(paths)
    tree_sha, untracked_out, big_tracked = _build_tree(paths, _filter_flags(paths.work_tree),
                                                       time.monotonic() + shadow_mod.GIT_TIMEOUT_S)
    return tree_sha, sorted(untracked_out + big_tracked)


def capture(directory: Path, *, session_uuid: str, conversation: str, prompt_uuid: str, store: CheckpointStore,
            state_root: Path, kind: str = KIND_TURN, locked: bool = False) -> CaptureResult:
    started = time.monotonic()
    turn = kind == KIND_TURN
    paths = shadow_mod.resolve(directory, state_root)
    if paths is None:
        return CaptureResult(skipped="not_git")
    state = store.repo_state(str(paths.shadow))
    if turn and state is not None and state["disabled_reason"]:
        return CaptureResult(skipped="disabled")
    if _uses_filters(paths):
        return CaptureResult(skipped="filters")
    with contextlib.nullcontext() if locked else repo_lock(paths.shadow):
        deadline = time.monotonic() + shadow_mod.GIT_TIMEOUT_S
        try:
            shadow_mod.ensure(paths)
            blank = _filter_flags(paths.work_tree)
            tree_sha, untracked_out, big_tracked = _build_tree(paths, blank, deadline)
            head = run_git(paths.work_tree, "rev-parse", "--verify", "-q", "HEAD^{commit}", timeout=shadow_mod.GIT_TIMEOUT_S,
                           optional_locks=False, untrusted_repo=True)
            head_sha = head.stdout.strip() if head.returncode == 0 else None
            message = f"checkpoint {kind} session={session_uuid} prompt={prompt_uuid} head={head_sha or '-'}"
            commit = _git(paths, None, blank, "commit-tree", tree_sha, "-m", message, timeout=_left(deadline))
            if commit.returncode != 0 or not commit.stdout.strip():
                raise OSError("commit-tree failed")
            commit_sha = commit.stdout.strip()
            ref = ref_name(session_uuid, prompt_uuid, kind)
            if _git(paths, None, blank, "update-ref", ref, commit_sha, timeout=_left(deadline)).returncode != 0:
                raise OSError("update-ref failed")
        except subprocess.TimeoutExpired:
            if turn:
                store.set_repo_state(str(paths.shadow), str(paths.work_tree), last_ms=None, disabled_reason="timeout")
            logger.warning("checkpoint_capture_timeout", work_tree=str(paths.work_tree), kind=kind)
            return CaptureResult(skipped="timeout")
        except OSError as exc:
            logger.warning("checkpoint_capture_failed", work_tree=str(paths.work_tree), kind=kind, error=str(exc))
            return CaptureResult(skipped="failed")
    ms = int((time.monotonic() - started) * 1000)
    left_out = sorted(untracked_out + big_tracked)
    saved = store.put(session_uuid=session_uuid, conversation=conversation, prompt_uuid=prompt_uuid, kind=kind,
                      work_tree=str(paths.work_tree), shadow=str(paths.shadow), ref=ref, commit_sha=commit_sha,
                      tree_sha=tree_sha, head_sha=head_sha, left_out=left_out, capture_ms=ms)
    if not turn:
        return CaptureResult(checkpoint=saved, ms=ms, left_out=left_out)
    slow = ms > SLOW_MS
    store.set_repo_state(str(paths.shadow), str(paths.work_tree), last_ms=ms,
                         disabled_reason="slow" if slow else None)
    if slow:
        logger.warning("checkpoint_capture_slow_disabled", work_tree=str(paths.work_tree), ms=ms)
    return CaptureResult(checkpoint=saved, ms=ms, left_out=left_out)
