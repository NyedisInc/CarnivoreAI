
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core.pack.transport import bundles, gh_helper, github_account, ladder, tarball

logger = structlog.get_logger()


class CodeError(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _git(root: str, *args: str, air_gap: bool = False, timeout: float = 300.0):
    return ladder.run(["git", "-C", root, *args], air_gap=air_gap, timeout=timeout)


def _out(done: subprocess.CompletedProcess) -> str:
    return done.stdout.decode("utf-8", "replace").strip()


def head_pushed(root: str) -> bool:
    done = _git(root, "branch", "-r", "--contains", "HEAD")
    return done.returncode == 0 and bool(_out(done))


def describe(root: str, *, air_gap: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"is_repo": False, "has_commits": False, "remote": None, "branch": None, "head": None, "dirty": 0, "pushed": False}
    if not os.path.isdir(root) or not bundles.is_repo(root):
        return out
    out["is_repo"] = True
    head = _git(root, "rev-parse", "--verify", "HEAD", air_gap=air_gap)
    out["has_commits"] = head.returncode == 0
    if out["has_commits"]:
        out["head"] = _out(head)
        branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD", air_gap=air_gap)
        out["branch"] = _out(branch) if branch.returncode == 0 else None
        out["pushed"] = head_pushed(root) if not air_gap else False
    remote = None if air_gap else bundles.origin_url(root)
    out["remote"] = None if remote and ladder.remote_has_userinfo(remote) else remote
    out["dirty"] = len([ln for ln in _out(_git(root, "status", "--porcelain", air_gap=air_gap)).splitlines() if ln.strip()])
    return out


def tree_stats(root: str) -> Dict[str, int]:
    files = size = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in tarball.EXCLUDE_ANYWHERE and not (dirpath == root and d in (".next", "dist"))]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) and not os.path.exists(path):
                continue
            files += 1
            size += os.lstat(path).st_size
    return {"files": files, "bytes": size}


def _is_empty(path: str) -> bool:
    return not os.path.exists(path) or (os.path.isdir(path) and not os.listdir(path))


def _checkout_carried(root: str, sender: str, branch: Optional[str], head: str, *, air_gap: bool) -> None:
    ref = f"refs/carnivore/{sender}/heads/{branch}" if branch else None
    has_head = _git(root, "rev-parse", "--verify", "HEAD", air_gap=air_gap).returncode == 0
    if not has_head:
        done = _git(root, "checkout", "-q", "--no-overwrite-ignore", "-B", branch or "main", ref or head, air_gap=air_gap) if ref else \
            _git(root, "checkout", "-q", "--no-overwrite-ignore", "--detach", head, air_gap=air_gap)
    else:
        if _out(_git(root, "status", "--porcelain", "--untracked-files=no", air_gap=air_gap)):
            raise CodeError("checkout_failed", "the folder here has uncommitted changes, so the source's commits were not checked out")
        if branch and _out(_git(root, "symbolic-ref", "--short", "-q", "HEAD", air_gap=air_gap)) != branch:
            known = _git(root, "rev-parse", "--verify", branch, air_gap=air_gap).returncode == 0
            _git(root, "checkout", "-q", "--no-overwrite-ignore", *(() if known else ("-B",)), branch, *(() if known else (head,)), air_gap=air_gap)
        done = _git(root, "merge", "--ff-only", "-q", "--no-overwrite-ignore", head, air_gap=air_gap)
    if done.returncode != 0:
        logger.warning("pack_migrate_checkout_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        raise CodeError("checkout_failed", "git could not check the source's branch out here (this folder has its own commits that do not line up)")


def checkout_replica(root: str, sender: str, branch: str, remote: Optional[str], *, air_gap: bool) -> bool:
    if _git(root, "rev-parse", "--verify", "HEAD", air_gap=air_gap).returncode == 0:
        if remote and not ladder.remote_has_userinfo(remote) and not air_gap and not bundles.origin_url(root):
            _git(root, "remote", "add", "origin", ladder.https_url(remote), air_gap=air_gap)
        return False
    ref = f"refs/carnivore/{sender}/heads/{branch}" if branch else None
    has_head = _git(root, "rev-parse", "--verify", "HEAD", air_gap=air_gap).returncode == 0
    if not has_head:
        done = _git(root, "checkout", "-q", "-B", branch or "main", ref or head, air_gap=air_gap) if ref else \
            _git(root, "checkout", "-q", "--detach", head, air_gap=air_gap)
    else:
        if _out(_git(root, "status", "--porcelain", "--untracked-files=no", air_gap=air_gap)):
            raise CodeError("checkout_failed", "the folder here has uncommitted changes, so the source's commits were not checked out")
        if branch and _out(_git(root, "symbolic-ref", "--short", "-q", "HEAD", air_gap=air_gap)) != branch:
            known = _git(root, "rev-parse", "--verify", branch, air_gap=air_gap).returncode == 0
            _git(root, "checkout", "-q", *(() if known else ("-B",)), branch, *(() if known else (head,)), air_gap=air_gap)
        done = _git(root, "merge", "--ff-only", "-q", head, air_gap=air_gap)
    if done.returncode != 0:
        logger.warning("pack_migrate_checkout_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        raise CodeError("checkout_failed", "git could not check the source's branch out here (this folder has its own commits that do not line up)")


def checkout_replica(root: str, sender: str, branch: str, remote: Optional[str], *, air_gap: bool) -> bool:
    if remote and not ladder.remote_has_userinfo(remote) and not air_gap and not bundles.origin_url(root) and _git(root, "rev-parse", "--verify", "HEAD", air_gap=air_gap).returncode == 0:
        _git(root, "remote", "add", "origin", ladder.https_url(remote), air_gap=air_gap)
    if _git(root, "rev-parse", "--verify", "HEAD", air_gap=air_gap).returncode == 0:
        return False
    ref = f"refs/carnivore/{sender}/heads/{branch}"
    if _git(root, "rev-parse", "--verify", "-q", ref, air_gap=air_gap).returncode != 0:
        return False
    if _git(root, "checkout", "-q", "-B", branch, ref, air_gap=air_gap).returncode != 0:
        raise CodeError("checkout_failed", "git could not check the home's branch out in the replica folder")
    if remote and not ladder.remote_has_userinfo(remote) and not air_gap and not bundles.origin_url(root):
        _git(root, "remote", "add", "origin", ladder.https_url(remote), air_gap=air_gap)
    return True


def bring(rung: str, root: str, undo: Dict[str, Any], *, sender: str, meta: Mapping[str, Any], archive: Optional[str],
          air_gap: bool, github_login: Optional[str]) -> None:
    if rung in (ladder.RUNG_TAR, ladder.RUNG_UNITS):
        if not _is_empty(root):
            aside = f"{root}.before-move-{os.urandom(3).hex()}"
            os.rename(root, aside)
            undo["aside"] = aside
        undo["root_created"] = True
        if rung == ladder.RUNG_TAR:
            tarball.extract_tarball(str(archive), root)
        else:
            os.makedirs(root, exist_ok=True)
        return
    created = _is_empty(root)
    if rung == ladder.RUNG_GIT:
        if not created:
            raise CodeError("root_not_empty", "the target folder already holds files")
        if not github_login:
            raise CodeError("account_unresolved", "no GitHub account on the other computer can clone this project; send it over the link instead")
        gh = github_account.gh_path()
        if gh is None:
            raise CodeError("account_unresolved", "gh is not installed on the other computer; send it over the link instead")
        undo["root_created"] = True
        os.makedirs(os.path.dirname(root), exist_ok=True)
        try:
            ladder.clone_from_origin(str(meta["remote"]), root, gh_helper.config_pairs(github_login, gh), air_gap=air_gap)
        except RuntimeError as exc:
            raise CodeError("clone_failed", "the clone from the project's remote failed; send it over the link instead") from exc
        gh_helper.install(root, github_login, air_gap=air_gap)
        if meta.get("branch"):
            _git(root, "checkout", "-q", str(meta["branch"]), air_gap=air_gap)
        return
    if rung != ladder.RUNG_CARRIED:
        raise CodeError("bad_rung", f"unknown rung {rung!r}")
    if created:
        os.makedirs(root, exist_ok=True)
        undo["root_created"] = True
        if _git(root, "init", "-q", "-b", str(meta.get("branch") or "main"), air_gap=air_gap).returncode != 0:
            raise CodeError("checkout_failed", "git init failed on the other computer")
    elif not bundles.is_repo(root):
        raise CodeError("root_not_empty", "the target folder holds files that are not a git repository")
    bundles.apply_bundle(root, str(archive), sender, air_gap=air_gap)
    _checkout_carried(root, sender, meta.get("branch"), str(meta["head"]), air_gap=air_gap)


def check(rung: str, root: str, meta: Mapping[str, Any], *, air_gap: bool) -> List[str]:
    if rung == ladder.RUNG_UNITS:
        return []
    if rung == ladder.RUNG_TAR:
        got, want = tree_stats(root), meta.get("stats") or {}
        return [] if got == {"files": want.get("files"), "bytes": want.get("bytes")} else ["tar_stats_differ"]
    head = _git(root, "rev-parse", "HEAD", air_gap=air_gap)
    return [] if head.returncode == 0 and _out(head) == meta.get("head") else ["head_differs"]


def undo_code(undo: Mapping[str, Any], root: Optional[str]) -> None:
    if root and undo.get("root_created") and os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    if undo.get("aside") and root and os.path.isdir(undo["aside"]) and not os.path.exists(root):
        os.rename(undo["aside"], root)


def reinstall(root: str, *, timeout: float = 900.0) -> List[str]:
    failed: List[str] = []
    for argv in tarball.install_commands(root):
        try:
            done = subprocess.run(argv, cwd=root, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("pack_migrate_reinstall_failed", command=argv[0], error=type(exc).__name__)
            failed.append(" ".join(argv))
            continue
        if done.returncode != 0:
            failed.append(" ".join(argv))
    return failed
