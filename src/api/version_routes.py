
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.core.db_health import live_state
from src.core.db_integrity_status import (
    integrity_block,
    unresolvable_integrity_block,
)
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_state import DatastoreState
from src.core.static_asset_keys import client_build_key
from src.core.update_check import UpdateChecker
from src.core.version import resolve_version

router = APIRouter()

_checker: Optional[UpdateChecker] = None

_datastore_state: Optional[DatastoreState] = None


def set_update_checker(checker: Optional[UpdateChecker]) -> None:
    global _checker
    _checker = checker


def set_datastore_state(state: Optional[DatastoreState]) -> None:
    global _datastore_state
    _datastore_state = state


def _datastore_block() -> dict:
    from src.config import settings, state_paths

    try:
        state_dir = settings.get_state_dir()
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "degraded_db_unreadable",
            "healthy": False,
            "readonly": True,
            "migrations_paused": True,
            "restore_offered": False,
            "schema_version": "CANNOT_DETERMINE",
            "schema_version_state": "cannot_determine",
            "code_schema_version": CURRENT_SCHEMA_VERSION,
            "config_version": "CANNOT_DETERMINE",
            "config_version_state": "cannot_determine",
            "trail_status": "unreadable",
            "trail_corrupt_line": None,
            "last_migration_at": None,
            "message": (
                "the state directory could not be resolved, so the "
                "database could not even be looked for."
            ),
            "detail": str(exc),
            "failed_entry_uuid": None,
            "state_dir_note": state_paths.state_dir_legacy_note(),
            "integrity": unresolvable_integrity_block(
                "the state directory could not be resolved, so the "
                "cached integrity verdict could not even be looked for"
            ),
        }
    block = live_state(
        _datastore_state, state_dir, CURRENT_SCHEMA_VERSION
    ).to_dict()
    block["state_dir_note"] = state_paths.state_dir_legacy_note()
    block["integrity"] = integrity_block(state_dir)
    return block


def _folded_update(block: Optional[dict]) -> Optional[dict]:
    from src.core.app_update import store

    app = store.status()
    if not app["attached"]:
        return block
    block = block or {"current_version": resolve_version(), "remote": ""}
    state = app["state"]
    status = "update_available" if state in ("available", "downloading", "ready") else (
        "current" if state == "current" else "unknown")
    return {**block, "status": status, "latest_version": app["latest_version"] if status == "update_available" else "",
            "checked_at": app["checked_at"] or 0.0, "upgrade_command": "",
            "reason": "" if status != "unknown" else (app["detail"] or f"the app updater says {state}")}


@router.get("/version", dependencies=[Depends(require_auth)])
async def get_version() -> dict:
    """Return the installed version and the cached update-check result.

    Returns:
        The shape documented in this module's docstring. Never blocks on a
        network call.
    """
    if _checker is None:
        return {
            "version": resolve_version(),
            "update": _folded_update({
                "status": "unknown",
                "current_version": resolve_version(),
                "latest_version": "",
                "remote": "",
                "checked_at": 0.0,
                "reason": "the update checker is not running",
                "upgrade_command": "",
            }),
            "data": _datastore_block(),
            "client_build": client_build_key(),
        }
    status = _checker.status()
    return {
        "version": resolve_version(),
        "update": _folded_update(status.to_dict() if _checker.applicable() else None),
        "data": _datastore_block(),
        "client_build": client_build_key(),
    }
