
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Mapping, Optional

from src.core import project_worktree
from src.core.pack.carry import land, wip as wip_mod
from src.core.pack.migrate.receive import MigrateRefused
from src.core.pack.transport import tarball

CLOUD_NAMES = frozenset({"dropbox", "onedrive", "icloud drive", "google drive", "googledrive", "box", "box sync", "mobile documents", "cloudstorage", "mega", "sync"})


def home_dir() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def in_cloud_sync(path: str) -> bool:
    return any(p.lower() in CLOUD_NAMES or p.lower().startswith(("onedrive", "googledrive", "dropbox")) for p in path.split(os.sep) if p)


def _missing_parents(path: str) -> List[str]:
    missing: List[str] = []
    here = os.path.dirname(path)
    while not os.path.lexists(here):
        missing.append(here)
        here = os.path.dirname(here)
    if os.path.islink(here) or not os.path.isdir(here):
        raise MigrateRefused("unsafe_path", "a link or file is in the way of the worktree folder", 422)
    return missing[::-1]


def _links_on_the_way(anchor: str, path: str) -> bool:
    here = os.path.dirname(path)
    while here != anchor and here.startswith(anchor + os.sep):
        if os.path.islink(here):
            return True
        here = os.path.dirname(here)
    return False


def _candidates(root: str, unit: Mapping[str, Any], repo: str, worktree_root: str) -> List[str]:
    out: List[str] = []
    home, rel = home_dir(), unit.get("home_rel")
    if rel and not os.path.isabs(rel) and not tarball.unsafe_member(rel):
        path = os.path.normpath(os.path.join(home, rel))
        real_root = os.path.realpath(root) + os.sep
        if path.startswith(home + os.sep) and not in_cloud_sync(rel) and not _links_on_the_way(home, path) and not (path + os.sep).startswith(real_root) \
                and not real_root.startswith(path + os.sep):
            out.append(path)
    try:
        base = str(project_worktree.resolve_root(worktree_root))
    except project_worktree.WorktreeRefused as exc:
        if not out:
            raise MigrateRefused("carry_failed", "this computer's worktree folder is not usable: " + exc.detail, 422) from exc
        return out
    name = project_worktree.branch_slug(os.path.basename(unit["src"].rstrip("/")))
    out.append(os.path.join(base, project_worktree.branch_slug(os.path.basename(repo)), name))
    return out


def _registered(repo: str, path: str, air_gap: bool) -> bool:
    listed = wip_mod._out(land._git(repo, "worktree", "list", "--porcelain", air_gap=air_gap))
    return any(os.path.realpath(ln[len("worktree "):]) == os.path.realpath(path) for ln in listed.splitlines() if ln.startswith("worktree "))


def _already_here(repo: str, path: str, unit: Mapping[str, Any], air_gap: bool) -> bool:
    if not os.path.isdir(path) or os.path.islink(path) or not _registered(repo, path, air_gap) or land._head(path, air_gap) != unit["head"]:
        return False
    if unit.get("wip"):
        return wip_mod.restored(path, unit["wip"], unit["index"], air_gap=air_gap)
    return not wip_mod.is_dirty(path, tracked_only=False, air_gap=air_gap)


def _undo(repo: str, path: str, parents: List[str], branch: Optional[str], air_gap: bool) -> None:
    if os.path.lexists(path):
        land._git(repo, "worktree", "remove", "--force", path, air_gap=air_gap)
        shutil.rmtree(path, ignore_errors=True)
    land._git(repo, "worktree", "prune", air_gap=air_gap)
    if branch:
        land._git(repo, "branch", "-D", branch, air_gap=air_gap)
    for folder in reversed(parents):
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)


def apply_worktree(root: str, unit: Mapping[str, Any], blob: Optional[str], wip_ref: str, worktree_root: str, *, air_gap: bool) -> Dict[str, Any]:
    repo = land.unit_dir(root, unit["rel"])
    air = air_gap
    if not os.path.isdir(os.path.join(repo, ".git")) or os.path.islink(os.path.join(repo, ".git")) or land._git(repo, "cat-file", "-e", f"{unit['head']}^{{commit}}", air_gap=air).returncode != 0:
        raise MigrateRefused("carry_failed", f"the commits of {unit['rel']} did not arrive here, so its worktree cannot be made", 409)
    try:
        if unit.get("wip") and (not blob or land._git(repo, "-c", "transfer.fsckObjects=true", "fetch", "--no-tags", "--force", blob, f"+{wip_ref}:{wip_ref}", air_gap=air).returncode != 0):
            raise MigrateRefused("bundle_unverified", "the uncommitted work did not verify against this checkout", 409)
        return _land(root, repo, unit, blob, worktree_root, air)
    finally:
        wip_mod.drop(repo, wip_ref, air_gap=air)


def _land(root: str, repo: str, unit: Mapping[str, Any], blob: Optional[str], worktree_root: str, air: bool) -> Dict[str, Any]:
    landed = None
    for path in _candidates(root, unit, repo, worktree_root):
        if os.path.lexists(path):
            if _already_here(repo, path, unit, air):
                return {"kind": "worktree", "head": unit["head"], "restored": bool(unit.get("wip")), "path": path, "paths": {unit["src"]: path}}
            continue
        landed = path
        break
    if landed is None:
        raise MigrateRefused(land.OWN, "no free place for the worktree here: the folders it could take already hold something else")
    parents = _missing_parents(landed)
    land._room(os.path.dirname(parents[0] if parents else landed),
               land._tree_bytes(repo, unit["head"], air) + (os.path.getsize(blob) if blob else 0))
    branch, made = unit.get("branch"), None
    if branch:
        have = wip_mod._out(land._git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{branch}^{{commit}}", air_gap=air))
        if have and have != unit["head"]:
            raise MigrateRefused(land.OWN, f"{unit['rel']} here has its own branch {branch} at another commit, so the worktree was not made")
        args = [landed, branch] if have else ["-b", branch, landed, unit["head"]]
        made = None if have else branch
    else:
        args = ["--detach", landed, unit["head"]]
    os.makedirs(os.path.dirname(landed), exist_ok=True)
    done = False
    try:
        if land._git(repo, "worktree", "add", "-q", *args, air_gap=air).returncode != 0:
            raise MigrateRefused("carry_failed", f"git could not make the worktree for {unit['rel']} here (its branch may be checked out already)", 409)
        if unit.get("wip"):
            try:
                wip_mod.restore(landed, unit["head"], unit["wip"], unit["index"], air_gap=air)
            except wip_mod.WipError as exc:
                raise MigrateRefused(land.OWN if exc.code == "wip_conflict" else "carry_failed", exc.detail) from exc
        done = True
        return {"kind": "worktree", "head": unit["head"], "restored": bool(unit.get("wip")), "path": landed, "paths": {unit["src"]: landed}}
    finally:
        if not done:
            _undo(repo, landed, parents, made, air)
