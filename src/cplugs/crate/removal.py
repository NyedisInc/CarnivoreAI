
from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders, record, refs, service
from src.cplugs.crate import service_crates as svc
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.errors import CrateApiError, conflict, invalid, not_found
from src.cplugs.crate.jobs import runner
from src.cplugs.crate.models import RemoveBody
from src.cplugs.sdk import exports as sx

logger = structlog.get_logger()

_SIDE_SUFFIXES = (".sha256", ".README.txt")
_VOLUME_TRASH = ".Trashes"


def home_trash() -> Path:
    return Path.home() / ".Trash"


def trash_for(path: Path) -> Path:
    home = home_trash()
    try:
        home.mkdir(mode=0o700, exist_ok=True)
        if os.stat(path).st_dev == os.stat(home).st_dev:
            return home
        parts = path.resolve().parts
        if len(parts) >= 3 and parts[1] == K.VOLUMES_ROOT.strip("/"):
            drive = Path(*parts[:3]) / _VOLUME_TRASH / str(os.getuid())
            drive.mkdir(mode=0o700, parents=True, exist_ok=True)
            return drive
    except OSError as exc:
        raise CrateApiError(500, "trash_unavailable", f"the Trash could not be used ({type(exc).__name__})") from exc
    raise CrateApiError(500, "trash_unavailable", "there is no Trash on the drive this crate is on")


def _free_stem(trash: Path, name: str) -> str:
    stem, suffix = (name[:-len(".crate.age")], ".crate.age") if name.endswith(".age") else (name[:-len(".crate")], ".crate")
    count, candidate = 1, name
    while any(os.path.lexists(trash / f"{candidate}{extra}") for extra in ("",) + _SIDE_SUFFIXES):
        count += 1
        candidate = f"{stem}-{count}{suffix}"
    return candidate


def _check_name(name: str) -> None:
    if not K.UPLOAD_NAME_RE.match(name or "") or Path(name).name != name or ".." in name:
        raise invalid("bad_crate_name", "the file is not named like a crate (crate-...crate or crate-...crate.age)")


def _file_in(env: CrateEnv, folder: str, name: str) -> Path:
    """The crate file ``name`` in a crate folder, proved to be a regular file directly inside it.

    Raises CrateApiError: 409 ``folder_unavailable``; 422 ``bad_crate_name``, ``crate_refused``; 404 ``crate_not_found``.
    """
    _check_name(name)
    try:
        base = folders.resolve(env, folder)
    except folders.FolderUnavailable as exc:
        raise conflict(exc.code, exc.detail) from exc
    path = base / name
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise not_found("crate_not_found", f"no crate {name} in the {folder} folder; it may already be gone") from exc
    if not stat.S_ISREG(st.st_mode) or os.path.realpath(path.parent) != os.path.realpath(base):
        raise invalid("crate_refused", f"{name} is not a regular crate file in the {folder} folder")
    return path


def _bundle_ids(env: CrateEnv) -> Dict[str, sx.Bundle]:
    return {b.bundle_id: b for b in svc.known_bundles(env)}


def _resolve_target(env: CrateEnv, body: RemoveBody, known: Dict[str, sx.Bundle]) -> Tuple[str, str, Optional[str]]:
    if body.bundle_id:
        found = known.get(body.bundle_id)
        if found is None:
            raise not_found("bundle_not_found", f"no bundle {body.bundle_id}")
        named = body.folder is not None
        for folder in ([body.folder] if named else [K.FOLDER_PRIMARY, K.FOLDER_SECOND]):
            try:
                base = os.path.realpath(folders.resolve(env, folder))
            except folders.FolderUnavailable as exc:
                if named:
                    raise conflict(exc.code, exc.detail) from exc
                continue
            for loc in found.locations:
                if os.path.realpath(Path(loc.where).parent) == base and refs.location_state(loc.where) == K.LOCATION_PRESENT:
                    return folder, Path(loc.where).name, found.bundle_id
        where = f"the {body.folder} folder" if named else "either crate folder"
        raise not_found("crate_not_found", f"bundle {body.bundle_id} has no copy in {where} now")
    if not body.folder or not body.name:
        raise invalid("bad_target", "name a crate: bundle_id, or folder (primary or second) and name")
    return body.folder, body.name, svc.bundle_id_of(body.name) if svc.bundle_id_of(body.name) in known else None


def _refuse_if_busy(name: str, bundle_id: Optional[str]) -> None:
    asked = runner.running_request()
    if not asked:
        return
    source = asked.get("source") if isinstance(asked.get("source"), dict) else {}
    ids = {asked.get("bundle_id"), source.get("bundle_id")} - {None}
    names = {asked.get("name"), source.get("name")} - {None}
    if (bundle_id and bundle_id in ids) or name in names:
        raise conflict("crate_in_use", f"a job is working on {name}; wait for it or cancel it first")


def _move(path: Path, trash: Path, final: str) -> Path:
    dest = trash / final
    try:
        if os.path.lexists(dest):
            raise FileExistsError(dest)
        os.rename(path, dest)
    except OSError as exc:
        raise CrateApiError(500, "remove_failed", f"{path.name} could not be moved to the Trash ({type(exc).__name__})") from exc
    return dest


def _trash_one(env: CrateEnv, folder: str, name: str) -> Dict[str, Any]:
    path = _file_in(env, folder, name)
    trash = trash_for(path)
    final = _free_stem(trash, name)
    landed = _move(path, trash, final)
    moved: List[str] = []
    for suffix in _SIDE_SUFFIXES:
        side = path.parent / f"{name}{suffix}"
        if side.is_symlink() or not side.is_file():
            continue
        try:
            _move(side, trash, f"{final}{suffix}")
            moved.append(suffix)
        except CrateApiError as exc:
            logger.warning("crate_sidecar_left", name=name, suffix=suffix, code=exc.code)
    logger.info("crate_removed", folder=folder, name=name, sidecars=len(moved))
    return {"folder": folder, "name": name, "trash": str(landed), "sidecars": moved}


def remove_blocking(env: CrateEnv, body: RemoveBody) -> Dict[str, Any]:
    known = _bundle_ids(env)
    folder, name, bundle_id = _resolve_target(env, body, known)
    _file_in(env, folder, name)
    _refuse_if_busy(name, bundle_id)
    removed = [_trash_one(env, folder, name)]
    skipped: List[Dict[str, str]] = []
    if body.also_second and folder == K.FOLDER_PRIMARY:
        try:
            removed.append(_trash_one(env, K.FOLDER_SECOND, name))
        except CrateApiError as exc:
            skipped.append({"folder": K.FOLDER_SECOND, "name": name, "reason": exc.code})
    local_removed = False
    if bundle_id:
        try:
            fresh = refs.find_bundle(env, bundle_id)
            if not refs.reachable(fresh):
                record.mark_removed(env, bundle_id)
                local_removed = True
        except (sx.MainDbUnreadable, sqlite3.Error, sx.BundleNotFound, CrateApiError) as exc:
            # could not
            logger.warning("crate_remove_unmarked", bundle_id=bundle_id, error=type(exc).__name__)
            skipped.append({"folder": folder, "name": name, "reason": "record_not_marked"})
    return {"removed": removed, "bundle_id": bundle_id, "local_removed": local_removed, "skipped": skipped}


async def remove_crate(ctx: Any, body: RemoveBody) -> Dict[str, Any]:
    answer = await asyncio.to_thread(lambda: remove_blocking(service.env_of(ctx), body))
    ctx.notify("jobs", None)
    return answer
