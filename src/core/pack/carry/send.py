
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict, List, Optional

from src.core.pack.carry import land, wip
from src.core.pack.carry.scan import CarrySet, RepoUnit
from src.core.pack.migrate.plan import MigrateError, Request, call
from src.core.pack.transport import blobs, bundles, ladder, tarball

CHECK_PATH = "/federation/pack/carry/check"
APPLY_PATH = "/federation/pack/carry/apply"
_TOO_BIG = ("blob_too_large", "inbox_quota_peer", "inbox_quota_total")


def _fail(label: str, what: str, code: str) -> MigrateError:
    if code in _TOO_BIG:
        return MigrateError("carry_too_large", f"{what} is too large for {label} to take", 507, "code")
    return MigrateError("carry_failed", f"{what} did not reach {label} ({code}); fix that, then send again", 502, "code")


async def check_units(request: Request, found: CarrySet, project_uid: str, label: str) -> None:
    units = [{"kind": "repo", "rel": r.rel, "head": r.head} for r in found.repos if r.head]
    if not units:
        return
    try:
        answer = await call(request, CHECK_PATH, {"project_uid": project_uid, "units": units, "which": []}, "check")
    except MigrateError as exc:
        if exc.code == "project_not_on_target":
            return
        raise
    for unit, row in zip(units, answer.get("units", [])):
        if row.get("diverged"):
            raise MigrateError(land.OWN, f"{unit['rel']} on {label} has commits of its own, so what is sent would not line up with them; sort that out there, then send again", 409, "check")


def _bundle(path: str, dest: str, ref: Optional[str], head: str, commits: bool, air_gap: bool) -> None:
    args = ["bundle", "create", dest]
    args += ["--branches", "--tags"] if commits else []
    args += [ref] if ref else []
    args += [] if commits else [f"^{head}"]
    done = ladder.run(["git", "-C", path, *args], air_gap=air_gap, timeout=600.0)
    if done.returncode != 0:
        raise bundles.BundleError("bundle_failed", "git could not make the bundle")


async def _send_repo(request: Request, root: str, unit: RepoUnit, *, project_uid: str, op_id: str, outbox: str, air_gap: bool, label: str) -> Optional[Dict[str, Any]]:
    path = root if unit.rel == "." else os.path.join(root, unit.rel)
    commits = unit.rel != "."
    ref = wip.ref_name(op_id, unit.rel)
    fd, dest = tempfile.mkstemp(prefix="carry-", suffix=".bundle", dir=outbox)
    os.close(fd)
    os.unlink(dest)
    try:
        branch = await asyncio.to_thread(bundles.carry_branch, path)
        extra = await asyncio.to_thread(lambda: wip.capture(path, ref, air_gap=air_gap))
        if not commits and extra is None:
            return None
        await asyncio.to_thread(_bundle, path, dest, ref if extra else None, str(unit.head), commits, air_gap)
        blob_id = await blobs.send_file(request, dest, blob_id=blobs.new_id(), kind="bundle")
        remote = None if air_gap else await asyncio.to_thread(bundles.origin_url, path)
        body = {"kind": "repo", "rel": unit.rel, "branch": branch, "head": unit.head, "commits": commits, "blob_id": blob_id,
                "remote": remote if remote and land.REMOTE_RE.match(remote) else None, "src": path, **(extra or {})}
        return await call(request, APPLY_PATH, {"op_id": op_id, "project_uid": project_uid, "unit": body}, "code")
    except (bundles.BundleError, wip.WipError, blobs.BlobError) as exc:
        raise _fail(label, unit.rel, exc.code) from exc
    finally:
        await asyncio.to_thread(wip.drop, path, ref, air_gap=air_gap)
        if os.path.exists(dest):
            os.unlink(dest)


async def _send_worktree(request: Request, path: str, repo_rel: str, *, project_uid: str, op_id: str, outbox: str, air_gap: bool, label: str) -> Dict[str, Any]:
    ref = wip.ref_name(op_id, "wt:" + path)
    fd, dest = tempfile.mkstemp(prefix="carry-", suffix=".bundle", dir=outbox)
    os.close(fd)
    os.unlink(dest)
    try:
        head = (await asyncio.to_thread(lambda: land._head(path, air_gap)))
        if head is None:
            raise MigrateError("content_not_carried", f"the worktree {os.path.basename(path)} has no commit yet, so it cannot be sent", 409, "code")
        branch = await asyncio.to_thread(lambda: wip._out(wip._git(path, "symbolic-ref", "-q", "--short", "HEAD", air_gap=air_gap)) or None)
        extra = await asyncio.to_thread(lambda: wip.capture(path, ref, air_gap=air_gap))
        blob_id = None
        if extra:
            await asyncio.to_thread(_bundle, path, dest, ref, head, False, air_gap)
            blob_id = await blobs.send_file(request, dest, blob_id=blobs.new_id(), kind="bundle")
        home = os.path.realpath(os.path.expanduser("~"))
        real = os.path.realpath(path)
        body = {"kind": "worktree", "rel": repo_rel, "src": path, "home_rel": os.path.relpath(real, home) if real.startswith(home + os.sep) else None,
                "branch": branch, "head": head, "commits": False, "blob_id": blob_id, **(extra or {})}
        return await call(request, APPLY_PATH, {"op_id": op_id, "project_uid": project_uid, "unit": body}, "code")
    except (bundles.BundleError, wip.WipError, blobs.BlobError) as exc:
        raise _fail(label, os.path.basename(path), exc.code) from exc
    finally:
        await asyncio.to_thread(wip.drop, path, ref, air_gap=air_gap)
        if os.path.exists(dest):
            os.unlink(dest)


async def _send_files(request: Request, root: str, files: List[str], *, project_uid: str, op_id: str, outbox: str, label: str) -> Dict[str, Any]:
    members = ["./" + f for f in files if "\n" not in f and (os.path.isfile(os.path.join(root, f)) or os.path.islink(os.path.join(root, f)))]
    fd, dest = tempfile.mkstemp(prefix="carry-", suffix=".tar.zst", dir=outbox)
    os.close(fd)
    os.unlink(dest)
    try:
        await asyncio.to_thread(lambda: tarball.make_tarball(root, dest, members=members))
        blob_id = await blobs.send_file(request, dest, blob_id=blobs.new_id(), kind="tar")
        return await call(request, APPLY_PATH, {"op_id": op_id, "project_uid": project_uid, "unit": {"kind": "files", "rel": ".", "src": root, "blob_id": blob_id}}, "code")
    except (tarball.TarballError, blobs.BlobError) as exc:
        raise _fail(label, "the loose files", exc.code) from exc
    finally:
        if os.path.exists(dest):
            os.unlink(dest)


async def send_units(request: Request, found: CarrySet, *, project_uid: str, op_id: str, outbox: str, air_gap: bool, label: str) -> List[Dict[str, Any]]:
    os.makedirs(outbox, mode=0o700, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for unit in found.repos:
        if unit.head is None:
            continue
        row = await _send_repo(request, found.root, unit, project_uid=project_uid, op_id=op_id, outbox=outbox, air_gap=air_gap, label=label)
        if row is not None:
            rows.append(row)
    for path in found.worktrees:
        rows.append(await _send_worktree(request, path, found.worktree_repos.get(path, "."), project_uid=project_uid, op_id=op_id, outbox=outbox, air_gap=air_gap, label=label))
    if found.files:
        rows.append(await _send_files(request, found.root, found.files, project_uid=project_uid, op_id=op_id, outbox=outbox, label=label))
    return rows
