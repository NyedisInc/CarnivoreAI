
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.manifest import HOME_FOLDER, ManifestError, ManifestStore, check_unit
from src.cplugs.save.vault import restore
from src.cplugs.save.vault.units import PlannedFile, UnitPlan

if TYPE_CHECKING:  # pragma: no cover
    from src.cplugs.save.vault.store import Vault

logger = structlog.get_logger()

STATUS_SWITCHED_OFF = "switched_off"
_MAX_TARGET_TRIES = 100


class FolderRefused(RuntimeError):
    pass


def skipped(rel: PurePosixPath) -> bool:
    if any(part in K.FOLDER_SKIP_DIRS for part in rel.parts[:-1]):
        return True
    return rel.name in K.FOLDER_SKIP_NAMES or rel.name.endswith(K.FOLDER_SKIP_SUFFIXES)


def _read_order(rel: str) -> tuple:
    last = any(rel.startswith(prefix) or f"/{prefix}" in f"/{rel}" for prefix in K.FOLDER_READ_LAST)
    return (last, rel)


def _overlaps(a: Path, b: Path) -> bool:
    ra, rb = Path(os.path.realpath(a)), Path(os.path.realpath(b))
    return ra == rb or ra in rb.parents or rb in ra.parents


def plan_folder(unit: str, root: Path, vault_root: Path, unreadable: Optional[List[str]] = None) -> Optional[UnitPlan]:
    """The files of one folder unit, or None when the folder is not there (absent, unmounted, not a folder). Blocking.

    Inputs: unit (``<plugin>.<data id>``); root (the declared folder); vault_root (refused when the two overlap); unreadable (when given,
      collects the folders that could not be listed: their files are then NOT read as deleted, see ``store.Vault.capture_folder``).
    Output: UnitPlan (kind ``folder``; an empty folder plans no files). Raises: FolderRefused.
    Example: plan_folder('reviewboard.boards', Path('/x/boards'), Path('/s/vault')).files[0].rel -> 'board-1/board.json'
    """
    try:
        check_unit(unit)
    except ManifestError as exc:
        raise FolderRefused(str(exc)) from exc
    if not root.is_dir() or root.is_symlink():
        return None
    if _overlaps(root, vault_root):
        raise FolderRefused(f"{root} and the vault {vault_root} overlap; a folder unit never holds the vault")
    plan = UnitPlan(unit, K.KIND_FOLDER, K.FAMILY_PLUGIN)

    def onerror(exc: OSError) -> None:
        logger.warning("vault_folder_unit_unreadable", unit=unit, path=str(exc.filename), error=str(exc))
        if unreadable is not None:
            unreadable.append(str(exc.filename))

    found: List[PlannedFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=onerror):
        dirnames[:] = sorted(d for d in dirnames if not os.path.islink(os.path.join(dirpath, d)) and d not in K.FOLDER_SKIP_DIRS)
        for name in filenames:
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            rel = PurePosixPath(full.relative_to(root).as_posix())
            if not skipped(rel):
                found.append(PlannedFile(full, K.ROLE_FOLDER_FILE, HOME_FOLDER, str(rel)))
    plan.files = sorted(found, key=lambda f: _read_order(f.rel))
    return plan


def restore_target(root: Path, point_id: str) -> Path:
    base = f"{root.name}{K.RESTORED_SUFFIX}{point_id}"
    root.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, _MAX_TARGET_TRIES + 1):
        target = root.parent / (base if attempt == 1 else f"{base}-{attempt}")
        try:
            target.mkdir()
        except FileExistsError:
            continue
        return target
    raise FileExistsError(f"no free name beside {root} for {base}")


def status_row(manifests: ManifestStore, unit: str, root: Optional[Path], status: str, detail: str = "") -> Dict[str, Any]:
    points = manifests.point_ids(unit)
    newest = manifests.newest(unit) if points else None
    return {"unit": unit, "root": str(root) if root is not None else "", "status": status, "points": len(points),
            "bytes": newest.raw_bytes() if newest else 0, "stored_bytes": sum(f.stored_bytes for f in newest.files) if newest else 0,
            "files": len(newest.files) if newest else 0, "last_point_at": newest.created_at if newest else None, "detail": detail}


def folder_units(manifests: ManifestStore) -> List[str]:
    out: List[str] = []
    for unit in manifests.units():
        if "." not in unit:
            continue
        newest = manifests.newest(unit)
        if newest is not None and newest.kind == K.KIND_FOLDER:
            out.append(unit)
    return out


def restore_folder(vault: "Vault", unit: str, point_id: Optional[str] = None) -> Tuple[Path, restore.RestoreResult, str]:
    manifest = vault.manifests.read(unit, point_id) if point_id else vault.manifests.newest(unit)
    if manifest is None:
        raise ManifestError(f"no point of {unit} in the vault")
    if manifest.kind != K.KIND_FOLDER or not manifest.working_dir:
        raise ManifestError(f"{unit} is not a plugin folder unit")
    target = restore_target(Path(manifest.working_dir), manifest.point_id)
    result = restore.restore_to_homes(vault.blobs, manifest, {HOME_FOLDER: target})
    logger.info("vault_folder_restored", unit=unit, point_id=manifest.point_id, target=str(target), files=len(result.written))
    return target, result, manifest.point_id
