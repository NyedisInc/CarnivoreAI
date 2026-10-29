"""The RECEIVING half of a carry (S3; docs/pack.md 11.2): put one unit into ``<project root>/<rel>`` and never write over local work.

``check_unit`` is a dry run. ``apply_repo`` lands a nested (or root) git repo: the carried bundle through ``bundles.apply_bundle`` (refs
under ``refs/carnivore/<sender>/``, never the receiver's own branches), the carried branch checked out fast-forward only, then the work in
progress restored. ``apply_files`` tops up non-repo content: the archive is unpacked into a scratch folder INSIDE the project root (so the
final move is a same-volume link) with the tar rung's guards, and a file moves into place only where the target path is absent or
byte-equal; any other file is ``target_has_own_changes`` and nothing at all is written. A peer-supplied ``rel`` is validated like
``move/receive._working_dir`` plus: no ``.git`` component, no symlink on the way, nothing outside the root. No file content is logged.
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core.pack.carry import wip as wip_mod
from src.core.pack.migrate.code import CodeError, _checkout_carried
from src.core.pack.migrate.receive import MigrateRefused
from src.core.pack.move.receive import _working_dir
from src.core.pack.transport import bundles, ladder, tarball

logger = structlog.get_logger()
OWN = "target_has_own_changes"
REMOTE_RE = re.compile(r"^(https://[^\s@/]+/[^\s]+|git@github\.com:[^\s]+)$")


def unit_dir(root: str, rel: str) -> str:
    path = _working_dir(root, rel)
    real_root = os.path.realpath(root)
    expected = real_root if rel == "." else os.path.normpath(os.path.join(real_root, rel))
    if (rel != "." and tarball.unsafe_member(rel)) or os.path.realpath(path) != expected:
        raise MigrateRefused("unsafe_path", "the folder is not inside its project", 422)
    return path


def _room(root: str, size: int) -> None:
    if shutil.disk_usage(root).free - tarball.FREE_MARGIN_BYTES < size:
        raise MigrateRefused("carry_too_large", "this computer does not have the room for what was sent", 507)


def _git(path: str, *args: str, air_gap: bool):
    return wip_mod._git(path, *args, air_gap=air_gap)


def _head(path: str, air_gap: bool) -> Optional[str]:
    return wip_mod._out(_git(path, "rev-parse", "-q", "--verify", "HEAD", air_gap=air_gap)) or None


def check_unit(root: str, unit: Mapping[str, Any], *, air_gap: bool) -> Dict[str, Any]:
    path = unit_dir(root, unit["rel"])
    present = os.path.exists(os.path.join(path, ".git")) and bundles.is_repo(path)
    out = {"present": present, "has_head": False, "behind": True, "own_changes": False, "diverged": False}
    if not present:
        return out
    here = _head(path, air_gap)
    out["own_changes"] = wip_mod.is_dirty(path, tracked_only=True, air_gap=air_gap)
    out["has_head"] = _git(path, "cat-file", "-e", f"{unit['head']}^{{commit}}", air_gap=air_gap).returncode == 0
    if here == unit["head"]:
        out["behind"] = False
    elif here is not None and out["has_head"]:
        out["behind"] = _git(path, "merge-base", "--is-ancestor", here, unit["head"], air_gap=air_gap).returncode == 0
        out["diverged"] = not out["behind"]
    return out


def which(names: List[str]) -> Dict[str, bool]:
    return {n: bool(shutil.which(n) or os.path.isdir(f"/Applications/{n}.app")) for n in names}


def _prepare(path: str, unit: Mapping[str, Any], air_gap: bool) -> Dict[str, Any]:
    made: Dict[str, Any] = {"git": False, "dir": False, "before": set()}
    dot_git = os.path.join(path, ".git")
    if os.path.islink(dot_git):
        raise MigrateRefused("unsafe_path", "the folder's .git is a link", 422)
    if not os.path.exists(dot_git):
        if os.path.exists(path) and not os.path.isdir(path):
            raise MigrateRefused(OWN, "a file here is in the way of a carried folder")
        made["dir"] = not os.path.exists(path)
        for here, dirs, files in os.walk(path):
            made["before"].update(os.path.join(here, n) for n in dirs + files)
        os.makedirs(path, exist_ok=True)
        made["git"] = True
        if _git(path, "init", "-q", "-b", unit["branch"], air_gap=air_gap).returncode != 0:
            _undo_prepare(path, made, None, None, air_gap)
            raise MigrateRefused("carry_failed", "git could not start a repo here", 500)
    return made


def _undo_prepare(path: str, made: Mapping[str, Any], head: Optional[str], wip: Optional[str], air_gap: bool) -> None:
    if not made["git"]:
        return
    names: List[str] = []
    if os.path.isdir(os.path.join(path, ".git")):
        names = wip_mod._out(_git(path, "ls-files", "-z", air_gap=air_gap)).split("\0")
        if head and wip:
            names += wip_mod._out(_git(path, "diff", "-z", "--name-only", "--no-renames", "--diff-filter=A", head, f"{wip}^{{tree}}", air_gap=air_gap)).split("\0")
    names = [n for n in names if n and os.path.join(path, n) not in made["before"]]
    for name in names:
        target = os.path.join(path, name)
        if os.path.islink(target) or os.path.isfile(target):
            os.unlink(target)
    for name in sorted(names, key=len, reverse=True):
        folder = os.path.dirname(os.path.join(path, name))
        while folder != path and folder.startswith(path) and folder not in made["before"] and os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
            folder = os.path.dirname(folder)
    shutil.rmtree(os.path.join(path, ".git"), ignore_errors=True)
    if made["dir"] and os.path.isdir(path) and not os.listdir(path):
        os.rmdir(path)


def _tree_bytes(path: str, rev: str, air_gap: bool) -> int:
    total = 0
    for line in wip_mod._out(_git(path, "ls-tree", "-r", "-l", rev, air_gap=air_gap)).splitlines():
        size = line.split("\t", 1)[0].split()[-1]
        total += int(size) if size.isdigit() else 0
    return total


def _original(path: str, air_gap: bool) -> Optional[Dict[str, str]]:
    sha = _head(path, air_gap)
    return {"ref": wip_mod._out(_git(path, "symbolic-ref", "-q", "HEAD", air_gap=air_gap)), "sha": sha} if sha else None


def _put_back(path: str, original: Mapping[str, str], air_gap: bool) -> None:
    target = original["ref"].removeprefix("refs/heads/") or original["sha"]
    _git(path, "checkout", "-q", "--no-overwrite-ignore", target, air_gap=air_gap)
    if original["ref"]:
        _git(path, "reset", "-q", "--keep", original["sha"], air_gap=air_gap)


def apply_repo(root: str, sender: str, unit: Mapping[str, Any], blob: Optional[str], wip_ref: str, *, air_gap: bool) -> Dict[str, Any]:
    path = unit_dir(root, unit["rel"])
    if unit["rel"] == "." and unit["commits"]:
        raise MigrateRefused("carry_failed", "the project's own repo travels with its commits, not with this call", 422)
    if not blob:
        raise MigrateRefused("no_blob", "the unit carries no bundle", 422)
    _room(root, os.path.getsize(blob))
    made = _prepare(path, unit, air_gap)
    original = None if made["git"] else _original(path, air_gap)
    done = False
    try:
        if unit["commits"]:
            bundles.apply_bundle(path, blob, sender, air_gap=air_gap)
        if unit.get("wip"):
            if _git(path, "-c", "transfer.fsckObjects=true", "fetch", "--no-tags", "--force", blob, f"+{wip_ref}:{wip_ref}", air_gap=air_gap).returncode != 0:
                raise MigrateRefused("bundle_unverified", "the uncommitted work did not verify against this checkout", 409)
        if unit.get("wip") and wip_mod.restored(path, unit["wip"], unit["index"], air_gap=air_gap) and _head(path, air_gap) == unit["head"]:
            done = True
            return {"head": unit["head"], "restored": True}
        mark = wip_mod.applied_ref(sender, unit["rel"])
        try:
            wip_mod.undo_applied(path, mark, air_gap=air_gap)
        except wip_mod.WipError as exc:
            raise MigrateRefused("carry_failed", exc.detail) from exc
        if wip_mod.is_dirty(path, tracked_only=True, air_gap=air_gap):
            raise MigrateRefused(OWN, f"{unit['rel']} here has changes of its own, so nothing was written over them")
        _room(root, _tree_bytes(path, unit["head"], air_gap) + (_tree_bytes(path, f"{unit['wip']}^{{tree}}", air_gap) if unit.get("wip") else 0))
        try:
            _checkout_carried(path, sender, unit["branch"], unit["head"], air_gap=air_gap)
        except CodeError as exc:
            raise MigrateRefused(OWN, f"{unit['rel']} here has commits of its own that do not line up with the ones sent") from exc
        if _head(path, air_gap) != unit["head"]:
            raise MigrateRefused(OWN, f"{unit['rel']} here has commits of its own beyond the ones sent")
        if unit.get("remote") and not air_gap and not bundles.origin_url(path):
            _git(path, "remote", "add", "origin", ladder.https_url(unit["remote"]), air_gap=air_gap)
        if unit.get("wip"):
            try:
                wip_mod.restore(path, unit["head"], unit["wip"], unit["index"], air_gap=air_gap)
            except wip_mod.WipError as exc:
                raise MigrateRefused(OWN if exc.code == "wip_conflict" else "carry_failed", exc.detail) from exc
            wip_mod.mark_applied(path, mark, unit["wip"], air_gap=air_gap)
        done = True
        return {"head": unit["head"], "restored": bool(unit.get("wip"))}
    except bundles.BundleError as exc:
        raise MigrateRefused(exc.code, exc.detail) from exc
    finally:
        if not done:
            if made["git"]:
                _undo_prepare(path, made, unit.get("head"), unit.get("wip"), air_gap)
            elif original is not None:
                _put_back(path, original, air_gap)
        if os.path.isdir(os.path.join(path, ".git")):
            wip_mod.drop(path, wip_ref, air_gap=air_gap)


def _same(src: str, dst: str) -> bool:
    if os.path.islink(src) or os.path.islink(dst):
        return os.path.islink(src) and os.path.islink(dst) and os.readlink(src) == os.readlink(dst)
    return os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False)


def _plan_top_up(root: str, extracted: str) -> List[tuple]:
    moves: List[tuple] = []
    clash: List[str] = []
    for here, _dirs, names in os.walk(extracted):
        for name in names + [d for d in _dirs if os.path.islink(os.path.join(here, d))]:
            src = os.path.join(here, name)
            rel = os.path.relpath(src, extracted)
            dst = os.path.join(root, rel)
            walk = os.path.dirname(rel)
            while walk:
                anc = os.path.join(root, walk)
                if os.path.islink(anc):
                    raise MigrateRefused("unsafe_path", "a link here points out of its folder", 422)
                if os.path.exists(anc) and not os.path.isdir(anc):
                    clash.append(walk)
                walk = os.path.dirname(walk)
            if os.path.lexists(dst):
                if not _same(src, dst):
                    clash.append(rel)
            else:
                moves.append((src, dst))
    if clash:
        raise MigrateRefused(OWN, f"{len(clash)} file(s) here differ from the ones sent, for example {', '.join(sorted(clash)[:3])}; nothing was written")
    return moves


def apply_files(root: str, archive: str) -> int:
    _room(root, os.path.getsize(archive))
    scratch = tempfile.mkdtemp(prefix=".carnivore-carry-", dir=root)
    try:
        extracted = os.path.join(scratch, "x")
        try:
            tarball.extract_tarball(archive, extracted)
        except tarball.TarballError as exc:
            raise MigrateRefused(exc.code, exc.detail, 422 if exc.code == "unsafe_archive" else 409) from exc
        moves = _plan_top_up(root, extracted)
        placed: List[str] = []
        try:
            for src, dst in moves:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.link(src, dst, follow_symlinks=False)
                placed.append(dst)
        except OSError as exc:
            for dst in placed:
                os.unlink(dst)
            logger.warning("pack_carry_files_failed", error=type(exc).__name__)
            raise MigrateRefused(OWN, "a file appeared here while the files were being placed; nothing was kept") from exc
        return len(moves)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
