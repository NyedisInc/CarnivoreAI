
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
import uuid as uuid_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.core.checkpoints import capture as capture_mod
from src.core.checkpoints import cleanup
from src.core.checkpoints import shadow as shadow_mod
from src.core.checkpoints.store import KIND_SAFETY, Checkpoint, CheckpointStore
from src.core.swarm.gitrun import _UNTRUSTED_FLAGS, _filter_flags, run_git

logger = structlog.get_logger()

GITLINK = "160000"
WRITE_TIMEOUT_S = 120.0

KEPT_LEFT_OUT = "left_out"
KEPT_IGNORED = "ignored"
KEPT_IN_THE_WAY = "in_the_way"
KEPT_SUBMODULE = "submodule"
KEPT_UNSAFE = "unsafe_path"


class RevertRefused(Exception):

    def __init__(self, status: int, code: str, message: str, safety_id: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.safety_id = safety_id


@dataclass
class RevertPlan:

    change: List[str] = field(default_factory=list)
    create: List[str] = field(default_factory=list)
    delete: List[str] = field(default_factory=list)
    kept: List[Dict[str, str]] = field(default_factory=list)
    current_tree: str = ""
    fingerprint: str = ""


@dataclass
class RevertResult:

    plan: RevertPlan
    safety: Checkpoint
    kept: List[Dict[str, str]]


def _git(paths: shadow_mod.RepoPaths, *args: str, index: Optional[Path] = None, input_bytes: Optional[bytes] = None,
         timeout: float = shadow_mod.GIT_TIMEOUT_S) -> "subprocess.CompletedProcess[str]":
    blank: List[str] = []
    flags = _filter_flags(paths.work_tree)
    names = {flags[i].split("=", 1)[0][len("filter."):].rsplit(".", 1)[0] for i in range(1, len(flags), 2)}
    for name in sorted(names):
        blank += ["-c", f"filter.{name}.smudge=", "-c", f"filter.{name}.required=false"]
    return run_git(paths.work_tree, *_UNTRUSTED_FLAGS, *flags, *blank, f"--git-dir={paths.shadow}",
                   f"--work-tree={paths.work_tree}", *args, timeout=timeout,
                   extra_env={"GIT_INDEX_FILE": str(index)} if index is not None else None, input_bytes=input_bytes,
                   low_priority=True)


def resolve_paths(cp: Checkpoint, state_root: Path) -> shadow_mod.RepoPaths:
    if not os.path.isdir(cp.work_tree):
        raise RevertRefused(409, "work_tree_gone", "the folder this snapshot was taken in is gone")
    paths = shadow_mod.resolve(Path(cp.work_tree), state_root)
    if paths is None or str(paths.work_tree) != cp.work_tree or str(paths.shadow) != cp.shadow:
        raise RevertRefused(409, "work_tree_changed", "this folder is no longer the git checkout the snapshot came from")
    return paths


def _unsafe(rel: str) -> bool:
    parts = rel.split("/")
    return rel.startswith("/") or any(p in ("", ".", "..") or p.lower() == ".git" for p in parts)


def _diff(paths: shadow_mod.RepoPaths, old_tree: str, new_tree: str) -> List[Tuple[str, str, str, str]]:
    done = _git(paths, "diff-tree", "-r", "-z", "--no-renames", old_tree, new_tree)
    if done.returncode != 0:
        raise RevertRefused(503, "checkpoint_unreadable", "git could not compare the snapshot with the files now")
    fields = done.stdout.split("\0")
    out: List[Tuple[str, str, str, str]] = []
    for i in range(0, len(fields) - 1, 2):
        meta = fields[i].lstrip(":").split(" ")
        if len(meta) == 5:
            out.append((meta[0], meta[1], meta[4][:1], fields[i + 1]))
    return out


def _real_index_skip_worktree(paths: shadow_mod.RepoPaths) -> Set[str]:
    done = run_git(paths.work_tree, *_UNTRUSTED_FLAGS, "ls-files", "-t", "-z", timeout=shadow_mod.GIT_TIMEOUT_S,
                   optional_locks=False)
    if done.returncode != 0:
        raise RevertRefused(503, "index_unreadable", "git could not read this checkout's index")
    return {e[2:] for e in done.stdout.split("\0") if e.startswith("S ")}


def _ignored(paths: shadow_mod.RepoPaths, rels: Iterable[str]) -> Set[str]:
    wanted = set(rels)
    if not wanted:
        return set()
    done = run_git(paths.work_tree, *_UNTRUSTED_FLAGS, "ls-files", "-z", "--cached", "--ignored", "--exclude-standard",
                   timeout=shadow_mod.GIT_TIMEOUT_S, optional_locks=False)
    if done.returncode != 0:
        raise RevertRefused(503, "ignore_rules_unreadable", "git could not read this checkout's ignore rules")
    return wanted & {p for p in done.stdout.split("\0") if p}


def _parents_ok(top: Path, rel: str, going: Set[str]) -> bool:
    parts = rel.split("/")[:-1]
    for depth in range(1, len(parts) + 1):
        sub = "/".join(parts[:depth])
        try:
            st = os.lstat(top / sub)
        except FileNotFoundError:
            return True
        if stat.S_ISDIR(st.st_mode):
            continue
        return sub in going
    return True


def _present(top: Path, rel: str) -> bool:
    parts = rel.split("/")
    for depth in range(1, len(parts)):
        try:
            if not stat.S_ISDIR(os.lstat(top / "/".join(parts[:depth])).st_mode):
                return False
        except FileNotFoundError:
            return False
    return os.path.lexists(top / rel)


def _emptied_by(top: Path, rel: str, going: Set[str]) -> bool:
    folder = top / rel
    if os.path.islink(folder) or not os.path.isdir(folder):
        return False
    for root, dirs, files in os.walk(folder, followlinks=False):
        base = Path(root).relative_to(top).as_posix()
        links = [d for d in dirs if os.path.islink(os.path.join(root, d))]
        if any(f"{base}/{name}" not in going for name in files + links):
            return False
    return True


def _fingerprint(target: Checkpoint, plan: RevertPlan) -> str:
    body = json.dumps([target.id, target.commit_sha, plan.current_tree, plan.change, plan.create, plan.delete,
                       plan.kept], sort_keys=True)
    return hashlib.sha256(body.encode("utf-8", "surrogateescape")).hexdigest()


def plan_between(paths: shadow_mod.RepoPaths, target: Checkpoint, current_tree: str, left_now: Iterable[str]) -> RevertPlan:
    protected = set(target.left_out) | set(left_now) | _real_index_skip_worktree(paths)
    plan = RevertPlan(current_tree=current_tree)
    kept: Dict[str, str] = {}
    change: List[str] = []
    create: List[str] = []
    delete: List[str] = []
    for old_mode, new_mode, letter, rel in _diff(paths, current_tree, target.tree_sha):
        if _unsafe(rel):
            kept[rel] = KEPT_UNSAFE
        elif rel in protected:
            kept[rel] = KEPT_LEFT_OUT
        elif GITLINK in (old_mode, new_mode):
            kept[rel] = KEPT_SUBMODULE
        elif letter == "A":
            create.append(rel)
        elif letter == "D":
            delete.append(rel)
        else:
            change.append(rel)
    for rel in _ignored(paths, delete):
        kept[rel] = KEPT_IGNORED
    delete = [r for r in delete if r not in kept]
    going = set(delete)
    top = paths.work_tree
    for rel in delete + change:
        if not _parents_ok(top, rel, set()):
            kept[rel] = KEPT_UNSAFE
    for rel in create:
        if not _parents_ok(top, rel, going) or (_present(top, rel) and not _emptied_by(top, rel, going)):
            kept[rel] = KEPT_IN_THE_WAY
    plan.change = sorted(r for r in change if r not in kept)
    plan.create = sorted(r for r in create if r not in kept)
    plan.delete = sorted(r for r in delete if r not in kept)
    plan.kept = [{"path": p, "reason": kept[p]} for p in sorted(kept)]
    plan.fingerprint = _fingerprint(target, plan)
    return plan


def preview(store: CheckpointStore, target: Checkpoint, state_root: Path) -> RevertPlan:
    paths = resolve_paths(target, state_root)
    with capture_mod.repo_lock(paths.shadow):
        try:
            tree, left_now = capture_mod.tree_now(paths)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RevertRefused(503, "files_unreadable", "git could not read the files as they are now") from exc
        return plan_between(paths, target, tree, left_now)


def prove_readable(paths: shadow_mod.RepoPaths, commit_sha: str) -> int:
    listed = _git(paths, "ls-tree", "-r", "-t", "-z", "--full-tree", commit_sha)
    if listed.returncode != 0:
        raise RevertRefused(409, "checkpoint_unreadable", "this snapshot can no longer be read")
    wanted: List[str] = []
    for entry in listed.stdout.split("\0"):
        meta = entry.split("\t", 1)[0].split(" ")
        if len(meta) == 3 and meta[1] in ("blob", "tree"):
            wanted.append(meta[2])
    if not wanted:
        return 0
    checked = _git(paths, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                   input_bytes=("\n".join(wanted) + "\n").encode())
    lines = checked.stdout.splitlines()
    missing = sum(1 for line in lines if line.split(" ")[-1] not in ("blob", "tree"))
    if checked.returncode != 0 or len(lines) != len(wanted) or missing:
        raise RevertRefused(409, "checkpoint_unreadable",
                            f"this snapshot can no longer be read ({missing or 'some'} of {len(wanted)} parts are gone)")
    return len(wanted)


def _unlink_inside(top: Path, rel: str) -> Optional[str]:
    *parents, name = rel.split("/")
    fd = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parents:
            try:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return None
            except OSError:
                return KEPT_UNSAFE
            os.close(fd)
            fd = nxt
        try:
            st = os.lstat(name, dir_fd=fd)
        except FileNotFoundError:
            return None
        if stat.S_ISDIR(st.st_mode):
            return KEPT_IN_THE_WAY
        os.unlink(name, dir_fd=fd)
        return None
    finally:
        os.close(fd)


def _remove_empty_parents(top: Path, rels: Iterable[str]) -> None:
    folders = sorted({"/".join(r.split("/")[:d]) for r in rels for d in range(1, r.count("/") + 1)},
                     key=lambda f: f.count("/"), reverse=True)
    for folder in folders:
        try:
            os.rmdir(top / folder)
        except OSError:
            continue


def _apply(paths: shadow_mod.RepoPaths, target: Checkpoint, plan: RevertPlan) -> List[Dict[str, str]]:
    top = paths.work_tree
    late: List[Dict[str, str]] = []
    gone: List[str] = []
    for rel in plan.delete:
        reason = _unlink_inside(top, rel)
        if reason is None:
            gone.append(rel)
        else:
            late.append({"path": rel, "reason": reason})
    _remove_empty_parents(top, gone)
    writes: List[str] = []
    for rel in plan.change + plan.create:
        target_path = top / rel
        if not _parents_ok(top, rel, set()):
            late.append({"path": rel, "reason": KEPT_IN_THE_WAY})
        elif rel in plan.create and _present(top, rel):
            late.append({"path": rel, "reason": KEPT_IN_THE_WAY})
        elif os.path.isdir(target_path) and not os.path.islink(target_path):
            late.append({"path": rel, "reason": KEPT_IN_THE_WAY})
        else:
            writes.append(rel)
    if writes:
        scratch = paths.shadow.parent / capture_mod.SCRATCH_DIRNAME
        scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        index = scratch / f"revert-{os.getpid()}-{uuid_module.uuid4().hex}"
        try:
            if _git(paths, "read-tree", target.tree_sha, index=index).returncode != 0:
                raise RevertRefused(500, "revert_failed", "git could not read the snapshot's files")
            done = _git(paths, "checkout-index", "-f", "-z", "--stdin", index=index, timeout=WRITE_TIMEOUT_S,
                        input_bytes="\0".join(writes).encode("utf-8", "surrogateescape") + b"\0")
            if done.returncode != 0:
                raise RevertRefused(500, "revert_failed", "some files could not be written")
        finally:
            for leftover in (index, Path(str(index) + ".lock")):
                try:
                    leftover.unlink()
                except FileNotFoundError:
                    pass
    return late


def revert(store: CheckpointStore, target: Checkpoint, fingerprint: str, state_root: Path) -> RevertResult:
    paths = resolve_paths(target, state_root)
    started = time.monotonic()
    with capture_mod.repo_lock(paths.shadow):
        taken = capture_mod.capture(paths.work_tree, session_uuid=target.session_uuid, conversation=target.conversation,
                                    prompt_uuid=f"safety-{uuid_module.uuid4().hex}", store=store,
                                    state_root=state_root, kind=KIND_SAFETY, locked=True)
        safety = taken.checkpoint
        if safety is None:
            raise RevertRefused(503, "safety_snapshot_failed",
                                f"the safety snapshot could not be taken ({taken.skipped}); nothing was changed")
        try:
            prove_readable(paths, target.commit_sha)
            prove_readable(paths, safety.commit_sha)
            plan = plan_between(paths, target, safety.tree_sha, safety.left_out)
            if plan.fingerprint != fingerprint:
                raise RevertRefused(409, "changed_since_preview",
                                    "the files changed since the preview; look at it again before reverting")
        except RevertRefused:
            cleanup.drop(store, [safety])
            raise
        try:
            late = _apply(paths, target, plan)
        except (OSError, RevertRefused) as exc:
            logger.warning("checkpoint_revert_failed", work_tree=str(paths.work_tree), error=type(exc).__name__)
            raise RevertRefused(500, "revert_failed", "the revert stopped part way; reverting to the safety snapshot "
                                f"taken just before it (#{safety.id}) undoes it", safety_id=safety.id) from exc
    logger.info("checkpoint_reverted", work_tree=str(paths.work_tree), target=target.id, safety=safety.id,
                changed=len(plan.change), created=len(plan.create), deleted=len(plan.delete),
                kept=len(plan.kept) + len(late), ms=int((time.monotonic() - started) * 1000))
    return RevertResult(plan=plan, safety=safety, kept=plan.kept + late)
