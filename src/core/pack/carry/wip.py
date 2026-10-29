
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from typing import Dict, Optional

import structlog

from src.core.pack.transport import ladder

logger = structlog.get_logger()

WIP_NS = "refs/carnivore-wip"
_IDENT = {"GIT_AUTHOR_NAME": "carnivore", "GIT_AUTHOR_EMAIL": "carnivore@localhost",
          "GIT_COMMITTER_NAME": "carnivore", "GIT_COMMITTER_EMAIL": "carnivore@localhost"}
_RAW = ("-c", "core.autocrlf=false", "-c", "core.safecrlf=false")


class WipError(Exception):
    """The work in progress could not be captured or restored; ``code`` is stable (``wip_failed``, ``wip_conflict``)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def ref_name(op_id: str, rel: str) -> str:
    return f"{WIP_NS}/{op_id}/{hashlib.sha1(rel.encode()).hexdigest()[:12]}"


def _git(repo: str, *args: str, env=None, air_gap: bool = False, timeout: float = 300.0):
    return ladder.run(["git", "-C", repo, *_RAW, *args], air_gap=air_gap, env=env, timeout=timeout)


def _out(done) -> str:
    return done.stdout.decode("utf-8", "replace").strip()


def is_dirty(repo: str, *, tracked_only: bool, air_gap: bool = False) -> bool:
    args = ("status", "--porcelain", "--untracked-files=no") if tracked_only else ("status", "--porcelain")
    return bool(_out(_git(repo, *args, air_gap=air_gap)))


def _trees(repo: str, air_gap: bool) -> Dict[str, str]:
    index = _out(_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index", air_gap=air_gap))
    scratch = tempfile.mkdtemp(prefix="carry-wip-")
    try:
        tmp_index = os.path.join(scratch, "index")
        if os.path.isfile(index):
            shutil.copyfile(index, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index, **_IDENT}
        staged = _git(repo, "write-tree", env=env, air_gap=air_gap)
        added = _git(repo, "add", "-A", env=env, air_gap=air_gap) if staged.returncode == 0 else staged
        tree = _git(repo, "write-tree", env=env, air_gap=air_gap) if added.returncode == 0 else added
        if tree.returncode != 0:
            logger.warning("pack_carry_wip_failed", step="trees", stderr_bytes=len(tree.stderr))
            raise WipError("wip_failed", "git could not read the uncommitted work (unmerged paths?)")
        return {"index": _out(staged), "work": _out(tree)}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def capture(repo: str, ref: str, *, air_gap: bool = False) -> Optional[Dict[str, str]]:
    if not is_dirty(repo, tracked_only=False, air_gap=air_gap):
        return None
    head = _out(_git(repo, "rev-parse", "-q", "--verify", "HEAD", air_gap=air_gap))
    parents = ["-p", head] if head else []
    trees = _trees(repo, air_gap)
    env = _IDENT
    made = _git(repo, "commit-tree", trees["index"], *parents, "-m", "carnivore wip index", env=env, air_gap=air_gap)
    wip = _git(repo, "commit-tree", trees["work"], *parents, "-p", _out(made), "-m", "carnivore wip", env=env, air_gap=air_gap) if made.returncode == 0 else made
    if wip.returncode != 0 or _git(repo, "update-ref", ref, _out(wip), air_gap=air_gap).returncode != 0:
        raise WipError("wip_failed", "git could not commit the uncommitted work")
    return {"wip": _out(wip), "index": _out(made)}


def drop(repo: str, ref: str, *, air_gap: bool = False) -> None:
    _git(repo, "update-ref", "-d", ref, air_gap=air_gap)


def restored(repo: str, wip: str, index: str, *, air_gap: bool = False) -> bool:
    try:
        trees = _trees(repo, air_gap)
    except WipError:
        return False
    want = {k: _out(_git(repo, "rev-parse", f"{c}^{{tree}}", air_gap=air_gap)) for k, c in (("index", index), ("work", wip))}
    return trees == want


def restore(repo: str, head: str, wip: str, index: str, *, air_gap: bool = False) -> None:
    added = _out(_git(repo, "diff", "--name-only", "--no-renames", "--diff-filter=A", head, f"{wip}^{{tree}}", air_gap=air_gap)) if head else ""
    if any(os.path.lexists(os.path.join(repo, name)) for name in added.splitlines()):
        raise WipError("wip_conflict", "a file here is in the way of the uncommitted work that was sent")
    moved = _git(repo, "read-tree", "-m", "-u", head, f"{wip}^{{tree}}", air_gap=air_gap)
    if moved.returncode != 0:
        logger.warning("pack_carry_wip_conflict", stderr_bytes=len(moved.stderr))
        raise WipError("wip_conflict", "a file here is in the way of the uncommitted work that was sent")
    if _git(repo, "read-tree", f"{index}^{{tree}}", air_gap=air_gap).returncode != 0:
        raise WipError("wip_failed", "git could not put the staged state back")


def applied_ref(sender: str, rel: str) -> str:
    return f"refs/carnivore/{sender}/wip-applied/{hashlib.sha1(rel.encode()).hexdigest()[:12]}"


def mark_applied(repo: str, ref: str, wip: str, *, air_gap: bool = False) -> None:
    _git(repo, "update-ref", ref, wip, air_gap=air_gap)


def undo_applied(repo: str, ref: str, *, air_gap: bool = False) -> bool:
    prev = _out(_git(repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}", air_gap=air_gap))
    if not prev:
        return False
    index, head = (_out(_git(repo, "rev-parse", "-q", "--verify", f"{prev}^{n}", air_gap=air_gap)) for n in (2, 1))
    if not (index and head) or _out(_git(repo, "rev-parse", "-q", "--verify", "HEAD", air_gap=air_gap)) != head or not restored(repo, prev, index, air_gap=air_gap):
        return False
    done = _git(repo, "read-tree", f"{prev}^{{tree}}", air_gap=air_gap)
    _git(repo, "update-index", "-q", "--refresh", air_gap=air_gap)
    done = _git(repo, "read-tree", "-m", "-u", f"{prev}^{{tree}}", head, air_gap=air_gap) if done.returncode == 0 else done
    if done.returncode != 0:
        raise WipError("wip_failed", "git could not take back the work an earlier attempt left here")
    _git(repo, "update-ref", "-d", ref, air_gap=air_gap)
    return True
