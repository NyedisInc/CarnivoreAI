
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.config import settings
from src.config.provider_accounts import profile_dir_for
from src.core.claude_rename import detect_claude_version
from src.core.live_install_roots import CLAUDE_DIR_NAME, HARNESS_MOD, TRASH_DIR_NAME
from src.core.mods import inventory, registry
from src.core.provider_ledger import accounts_store
from src.core.resource_push import notifier
from src.core.resource_push.topics import MODS
from src.core.skills.installer import trash_stamp
from src.core.skills.targets import TrashFolderIsLink, move_to_trash
from src.models.mods import ModsResponse, RemoveResponse, SetEnabledRequest, SetEnabledResponse

logger = structlog.get_logger()

router = APIRouter(tags=["mods"])

_MOD_ID = re.compile(r"^[0-9a-f]{16}$")


ACCOUNTS_OK, ACCOUNTS_UNREADABLE = "ok", "accounts_unreadable"


def account_settings_files() -> Tuple[List[Path], str]:
    try:
        accounts = accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except FileNotFoundError:
        return [], ACCOUNTS_OK
    except ValueError as exc:
        logger.warning("mods_accounts_unreadable", error=type(exc).__name__)
        return [], ACCOUNTS_UNREADABLE
    return ([Path(profile_dir_for(a)).expanduser() / "settings.json" for a in accounts if a.provider == "claude"],
            ACCOUNTS_OK)


def _require_accounts(status: str) -> None:
    if status != ACCOUNTS_OK:
        raise HTTPException(status_code=409, detail={"code": ACCOUNTS_UNREADABLE, "detail": "the account list could not be read, so no settings file was changed"})


def _ledger_rows(request: Request) -> List[Dict[str, str]]:
    rows = []
    with request.app.state.services.catalog.ledger() as ledger:
        for item in ledger.list():
            if item.kind != "mod":
                continue
            paths = [t.path for t in ledger.targets(item.install_id) if t.harness == HARNESS_MOD]
            if paths:
                rows.append({"install_id": item.install_id, "item_id": item.item_id, "path": paths[0]})
    return rows


def _scan(request: Request) -> Dict[str, Any]:
    files, status = account_settings_files()
    data = inventory.build_inventory(Path.home(), files, _ledger_rows(request))
    data["accounts"] = {"status": status}
    version = detect_claude_version()
    data["claude"] = {"version": ".".join(map(str, version)) if version else None,
                      "ok": bool(version and version >= inventory.MIN_CLAUDE_VERSION)}
    return data


def _find(data: Dict[str, Any], mod_id: str) -> Dict[str, Any]:
    hit = next((m for m in data["mods"] if _MOD_ID.match(mod_id) and m["mod_id"] == mod_id), None)
    if hit is None:
        raise HTTPException(status_code=404, detail="unknown mod")
    return hit


def _refuse_if_all_failed(results: List[Dict[str, Any]]) -> None:
    bad = [r for r in results if r["status"] not in (registry.OK, registry.MISSING)]
    if bad and all(r["status"] != registry.OK for r in results):
        raise HTTPException(status_code=409, detail={"code": bad[0]["status"], "detail": "the settings file was not changed"})


@router.get("/mods", response_model=ModsResponse, dependencies=[Depends(require_auth)])
async def list_mods(request: Request) -> Dict[str, Any]:
    """Every installed or registered mod, the settings groups and the claude version gate."""
    return await asyncio.to_thread(_scan, request)


@router.put("/mods/{mod_id}/enabled", response_model=SetEnabledResponse, dependencies=[Depends(require_auth)])
async def set_mod_enabled(request: Request, mod_id: str, body: SetEnabledRequest) -> Dict[str, Any]:
    """Register (on) or unregister (off) one mod in every settings group; files stay.

    Raises: 404 unknown mod; 409 ``folder_missing`` / ``not_a_mod`` when turning on a folder that cannot load;
    409 with the group's code when no settings file took the change. Partial results are returned as 200.
    """
    def work() -> Dict[str, Any]:
        files, status = account_settings_files()
        _require_accounts(status)
        mod = _find(_scan(request), mod_id)
        if body.enabled:
            if not mod["present"]:
                raise HTTPException(status_code=409, detail={"code": "folder_missing", "detail": "the mod folder is gone"})
            if not mod["is_mod"]:
                raise HTTPException(status_code=409, detail={"code": "not_a_mod", "detail": "the folder has no hooks/hooks.json modules"})
        results = registry.set_registered(mod["path"], body.enabled, home=Path.home(), account_files=files)
        _refuse_if_all_failed(results)
        return {"mod": _find(_scan(request), mod_id), "results": results}

    return await asyncio.to_thread(work)


@router.delete("/mods/{mod_id}", response_model=RemoveResponse, dependencies=[Depends(require_auth)])
async def remove_mod(request: Request, mod_id: str) -> Dict[str, Any]:
    """Unregister a LOCAL mod folder directly under ``~/.claude/mods`` and move it to the trash.

    Raises: 404 unknown mod; 409 ``use_catalog_uninstall`` (a ledger row owns it), ``not_removable`` (outside
    ``~/.claude/mods``: switch it off instead), or the settings group's code when a file cannot be edited.
    """
    stamp = trash_stamp(request.app.state.services.clock)

    def work() -> Dict[str, Any]:
        files, status = account_settings_files()
        _require_accounts(status)
        mod = _find(_scan(request), mod_id)
        if mod["source"] == "catalog":
            raise HTTPException(status_code=409, detail={"code": "use_catalog_uninstall", "detail": "uninstall it from the catalog"})
        if not mod["removable"]:
            raise HTTPException(status_code=409, detail={"code": "not_removable", "detail": "only a folder under ~/.claude/mods can be removed; switch it off"})
        results = registry.unregister(mod["path"], home=Path.home(), account_files=files)
        if any(r["status"] not in (registry.OK, registry.MISSING) for r in results):
            raise HTTPException(status_code=409, detail={"code": next(r["status"] for r in results if r["status"] not in (registry.OK, registry.MISSING)),
                                                         "detail": "a settings file could not be edited, so nothing was removed"})
        entry = Path(os.path.realpath(inventory.mods_root(Path.home()))) / os.path.basename(os.path.normpath(mod["path"]))
        if entry.exists() or entry.is_symlink():
            trash = Path.home() / CLAUDE_DIR_NAME / TRASH_DIR_NAME
            try:
                trashed = str(move_to_trash(entry, trash, stamp))
            except TrashFolderIsLink:
                raise HTTPException(status_code=409, detail={"code": "target_unsafe", "detail": "the trash folder is a link"})
            except FileExistsError:
                raise HTTPException(status_code=409, detail={"code": "trash_name_taken", "detail": "retry in a second"})
            except OSError as exc:
                logger.warning("mod_remove_failed", error=type(exc).__name__)
                raise HTTPException(status_code=500, detail="the folder could not be moved to the trash")
        else:
            trashed = ""
        notifier.notify(MODS)
        return {"mod_id": mod_id, "name": mod["name"], "trashed_to": trashed, "results": results}

    return await asyncio.to_thread(work)
