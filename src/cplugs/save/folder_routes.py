
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import folders, health, restore
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.manifest import ManifestError, check_unit
from src.cplugs.sdk import transcript_files as tf, vault_sources

logger = structlog.get_logger()


class FolderUnit(BaseModel):
    """One folder unit: ``<plugin>.<data id>``, its folder, the last capture's status and the newest point's size."""

    unit: str
    plugin: str = Field("", description="the plugin id, the part of the unit before its first dot")
    data_id: str = Field("", description="the plugin's data entry id, the part after it")
    plugin_name_key: str = Field("", description="catalog key of the plugin's display name; blank when the plugin is not shipped any more")
    root: str = ""
    marked: bool = Field(description="true while an enabled plugin marks the folder policy.backup: vault")
    backup_on: bool = Field(False, description="the backup menu's switch for this folder: true while it is marked and not switched off. Off means "
                                              "no NEW point is taken; the points held stay. Written through the plugin setting vaultFolderOptOut")
    status: str = ""
    points: int = 0
    bytes: int = Field(0, description="the newest point's files, before compression")
    stored_bytes: int = Field(0, description="what the newest point's chunks take in the vault")
    files: int = 0
    last_point_at: Optional[str] = None
    detail: str = ""


class FolderPoint(BaseModel):
    """One restore point of a folder unit."""

    point_id: str
    created_at: str
    reason: str = ""
    files: int = 0
    bytes: int = Field(0, description="the point's files, before compression")


class FolderPoints(BaseModel):
    """A folder unit's points, newest first."""

    unit: str
    root: str = ""
    points: List[FolderPoint]


class FolderList(BaseModel):
    """Every folder unit, marked ones first."""

    folders: List[FolderUnit]


class FolderRestoreBody(BaseModel):
    """Which point to restore; the newest when absent."""

    point_id: Optional[str] = Field(None, max_length=200)


class FolderRestoreResult(BaseModel):
    """Where the restore went and what it wrote. ``target`` is a folder that did not exist before the call."""

    unit: str
    point_id: str
    target: str
    written: int
    bytes: int


def list_now() -> FolderList:
    vault = RUNTIME.vault()
    marked = {f.unit: f for f in vault_sources.vault_folders(Path(tf.state_dir()))}
    recorded = {row.get("unit"): row for row in health.evaluate(health.read(tf.state_dir()))["folders"]}
    name_keys = vault_sources.plugin_name_keys()
    out: List[FolderUnit] = []
    for unit in list(marked) + [u for u in folders.folder_units(vault.manifests) if u not in marked]:
        root = marked[unit].root if unit in marked else None
        row: Dict[str, Any] = folders.status_row(vault.manifests, unit, root, str((recorded.get(unit) or {}).get("status") or ""),
                                                 str((recorded.get(unit) or {}).get("detail") or ""))
        if root is None and unit not in marked:
            newest = vault.manifests.newest(unit)
            row["root"] = (newest.working_dir or "") if newest else ""
        plugin, _dot, data_id = unit.partition(".")
        out.append(FolderUnit(marked=unit in marked, backup_on=unit in marked and not marked[unit].opted_out, plugin=plugin, data_id=data_id, plugin_name_key=name_keys.get(plugin, ""), **row))
    return FolderList(folders=out)


def points_now(unit: str) -> FolderPoints:
    try:
        vault = RUNTIME.vault()
        check_unit(unit)
        if unit not in folders.folder_units(vault.manifests):
            raise ManifestError(f"{unit} is not a plugin folder unit in the vault")
        found = vault.manifests.points(unit)
    except VaultUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})
    except ManifestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    rows = [FolderPoint(point_id=m.point_id, created_at=m.created_at, reason=m.reason, files=len(m.files), bytes=m.raw_bytes())
            for m in reversed(found)]
    return FolderPoints(unit=unit, root=(found[-1].working_dir or "") if found else "", points=rows)


def restore_now(unit: str, point_id: Optional[str]) -> FolderRestoreResult:
    try:
        vault = RUNTIME.vault()
        target, result, used = folders.restore_folder(vault, unit, point_id)
    except VaultUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})
    except ManifestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except restore.RestoreError as exc:
        logger.error("vault_folder_restore_failed", unit=unit, error=str(exc))
        raise HTTPException(status_code=409, detail={"code": "restore_failed", "detail": str(exc)})
    except OSError as exc:
        logger.error("vault_folder_restore_unwritable", unit=unit, error=str(exc))
        raise HTTPException(status_code=500, detail=f"could not write the restored folder: {exc}")
    return FolderRestoreResult(unit=unit, point_id=used, target=str(target), written=len(result.written), bytes=result.bytes)


def add_to(router: APIRouter) -> None:

    @router.get("/folders", response_model=FolderList)
    async def get_folders() -> FolderList:
        """Every plugin folder unit: its folder, the last capture and the newest point's size. 409 while the vault is unavailable."""
        try:
            return await run_in_threadpool(list_now)
        except VaultUnavailable as exc:
            raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})

    @router.get("/folders/{unit}/points", response_model=FolderPoints)
    async def get_folder_points(unit: str) -> FolderPoints:
        """One folder unit's restore points, newest first. 404 for a unit that is not a folder unit in the vault."""
        return await run_in_threadpool(points_now, unit)

    @router.post("/folders/{unit}/restore", response_model=FolderRestoreResult)
    async def restore_folder(unit: str, body: FolderRestoreBody) -> FolderRestoreResult:
        """Restore a folder unit's newest point (or ``point_id``) into a NEW folder beside the original; nothing existing is touched."""
        return await run_in_threadpool(restore_now, unit, body.point_id)
