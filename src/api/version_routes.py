"""Version and release self-check routes.

Exposes the installed release tag and the cached result of the background
update check. Both are cheap reads: the update endpoint NEVER performs a
network call in the request path, it returns whatever the background thread
last stored, with its timestamp, so a stale answer is visibly stale.

CONSUMER CONTRACT. ``GET /api/v1/version`` returns exactly this shape, and it
is the documented feed for the home bottom bar's version chip:

    {
      "version": "0.8.1",          # installed tag, "" if it did not resolve
      "update": {
        "status": "current" | "update_available" | "unknown",
        "current_version": "0.8.1",
        "latest_version": "0.9.0", # "" unless status is update_available
        "remote": "https://github.com/...",
        "checked_at": 1755000000.0,  # unix seconds; 0 means never checked
        "reason": "",              # non-empty ONLY when status is unknown
        "upgrade_command": "open https://github.com/.../releases/latest"
      }
    }

``update`` IS ``null`` WHEN THE TAG CHECK DOES NOT APPLY: a packaged install (no ``.git`` under the source root, no
``updates.remote``) updates through the desktop app's updater, so nothing asked a remote. ``null`` means "not
applicable", never "up to date"; once a packaged app reports, its verdict fills the block (see ``_folded_update``).

THE PATH IS ``/api/v1/version`` AND THERE IS NO SECOND ONE. An explicit
three-value ``status`` string cannot be accidentally collapsed to two the way
``null`` versus ``false`` can.

THE COPY, all three states, lowercase to match the rest of the ui:

``unknown`` must render as its own thing. It is NOT "up to date". Anything
that collapses it into the current state is a false green.

THE ``data`` BLOCK, added by feat/datastore-and-trail, is ADDITIVE - nothing
above it was removed. It answers a DIFFERENT question from ``version``:
``version`` says which CODE is running, ``data`` says which DATA version this
install's state is at. A user attempting a rollback needs both answered at
once, because rolling back code without knowing the data version is exactly
how old code ends up reading a newer schema.

``state_dir_note`` IS ADDITIVE TOO. None on every steady-state boot - a
fresh install, an install already living under the current-named state
directory, or one with an explicit CLOUDE_STATE_DIR override. Only set to
a one-sentence string when ``state_dir()`` (src/config/state_paths.py)
fell back to running out of the legacy-named directory because its own
rename attempt could not complete; see
``state_paths.state_dir_legacy_note()``.

TWO FIELDS, BECAUSE THERE ARE TWO FACTS. ``verdict`` is what the check
found; ``freshness`` is whether anybody has looked recently. ``verdict`` is
only ever "ok" when a check actually ran AND its result is inside the
freshness window, so "never checked" reports ``cannot_determine`` and can
never be mistaken for a clean bill of health. That collapse would be a
false green manufactured by the check meant to prevent one.

A cached ``failed`` verdict ALSO degrades ``data.status`` to
``degraded_db_unreadable``, exactly as the per-request pragma used to. A
``cannot_determine`` verdict does not touch ``data.status`` at all: not
having looked is not a fault.
"""

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
    """Build the ``data`` block, re-probing the database right now.

    Description: never raises - a status endpoint that 500s tells the user
      less than one that says "I could not read it". Any unexpected error
      is converted by live_state into the named unreachable verdict.

      THE RE-PROBE IS CHEAP ON PURPOSE: one connect, one small SELECT and
      one read of a small JSON file. No pragma walks the database here.
      The ``integrity`` sub-block is the cached verdict of the daily
      background check plus its age - see this module's docstring.
    Inputs: none.
    Output: dict - see this module's docstring for the shape.
    """
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
