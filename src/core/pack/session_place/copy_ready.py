
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.pack.migrate.code import CodeError, checkout_carried
from src.core.pack.transport import ladder

log = structlog.get_logger(__name__)

NOT_READY = "copy_not_ready"
IN_USE = "copy_in_use"
_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class CopyState:

    ok: bool
    moved: bool = False
    ahead: bool = False
    head: str = ""
    code: Optional[str] = None
    detail: str = ""


def _git(root: str, *args: str, air_gap: bool) -> "subprocess.CompletedProcess[bytes]":
    return ladder.run(["git", "-C", root, *args], air_gap=air_gap, timeout=60.0)


def _text(done: "subprocess.CompletedProcess[bytes]") -> str:
    return done.stdout.decode("utf-8", "replace").strip()


def _refuse(detail: str, code: str = NOT_READY) -> CopyState:
    return CopyState(False, code=code, detail=detail)


def ready(root: str, sender: str, branch: str, head: str, *, air_gap: bool, in_use: bool = False) -> CopyState:
    if not _SHA.fullmatch(head or ""):
        return _refuse("the home sent a commit that is not a full hash")
    if _git(root, "rev-parse", "--git-dir", air_gap=air_gap).returncode != 0:
        return _refuse("the copy's folder is not a git repository")
    if _git(root, "cat-file", "-e", f"{head}^{{commit}}", air_gap=air_gap).returncode != 0:
        return _refuse("the home's latest commit did not reach this copy")
    cur = _text(_git(root, "rev-parse", "--verify", "-q", "HEAD", air_gap=air_gap))
    if not cur:
        return _move(root, sender, branch, head, air_gap)
    if cur == head:
        return CopyState(True, head=head)
    if _git(root, "merge-base", "--is-ancestor", head, cur, air_gap=air_gap).returncode == 0:
        return CopyState(True, ahead=True, head=cur)
    if _git(root, "merge-base", "--is-ancestor", cur, head, air_gap=air_gap).returncode != 0:
        return _refuse("the copy has commits of its own that do not line up with the home's")
    if in_use:
        return _refuse("the copy is in use and behind", IN_USE)
    if _text(_git(root, "status", "--porcelain", "--untracked-files=no", air_gap=air_gap)):
        return _refuse("the copy is behind and has uncommitted changes")
    own = _git(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", air_gap=air_gap)
    if own.returncode == 0 and _git(root, "merge-base", "--is-ancestor", _text(own), head, air_gap=air_gap).returncode != 0:
        return _refuse(f"the copy's own {branch[:60]} branch has commits the home's does not")
    return _move(root, sender, branch, head, air_gap)


def _move(root: str, sender: str, branch: str, head: str, air_gap: bool) -> CopyState:
    try:
        checkout_carried(root, sender, branch, head, air_gap=air_gap)
    except CodeError as exc:
        log.info("session_place_copy_move_refused", code=exc.code)
        return _refuse("the copy could not be moved to the home's latest commit")
    if _text(_git(root, "rev-parse", "--verify", "-q", "HEAD", air_gap=air_gap)) != head:
        return _refuse("the copy did not end up on the home's latest commit")
    return CopyState(True, moved=True, head=head)
