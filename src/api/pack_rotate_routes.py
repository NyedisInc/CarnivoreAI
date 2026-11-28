
from __future__ import annotations

import asyncio
import sqlite3
import time
import json
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api import peer_auth
from src.api.error_response import api_error, log_failure
from src.api.pack_removed_logins_routes import mesh_route, owner_only
from src.config import settings
from src.core.pack.relay import removed_copies, rotation
from src.core.provider_ledger import accounts_store, poller
from src.core.provider_ledger.poller_scan import AUTO_DEFAULT_ACCOUNT_ID

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/pack/rotate", tags=["pack-relay"])
_GATES = [Depends(mesh_route), Depends(owner_only("rotate_owner_only"))]


class StartBody(BaseModel):
    """``POST /pack/rotate/start``: the stored account the owner is about to sign in again."""

    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=1, max_length=128)


def _accounts() -> List[Any]:
    try:
        return accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except (OSError, ValueError) as exc:
        log.warning("pack_rotate_accounts_unreadable", error_class=type(exc).__name__)
        return []


@router.get("", dependencies=_GATES)
async def rotate_state() -> Dict[str, Any]:
    """Per stored claude or codex account: whether a new sign-in was seen, what a fresh sign-in is known to do, and each removed computer's copy status;
    plus the Argent copies. Example: GET /api/v1/pack/rotate -> {"accounts": [...], "argent": {"known": true, "copies": []}, "removed_computers": 1}"""
    from src.core.argent import pair_sync

    pair = pair_sync.PAIR
    usage = {u.id: u for u in poller.snapshot().accounts}

    def read() -> Dict[str, Any]:
        return rotation.walk(lambda: peer_auth.open_db(), _accounts(), usage, None if pair is None else pair.credentials.delegate_copies, int(time.time() * 1000))

    try:
        return await asyncio.to_thread(read)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise api_error(503, "rotate_unavailable", exc) from exc


@router.post("/start", dependencies=_GATES)
async def rotate_start(request: Request) -> Dict[str, Any]:
    """Record the baseline for one stored claude or codex account; opens nothing and signs nothing (the client opens the existing login next).
    The body is read HERE, after the gates, so with the mesh switch off a malformed body still answers the unknown-path 404. The computer's own
    default claude login is not a stored account and has no in-app sign-in: 409 ``rotate_terminal_only``.
    Example: POST /api/v1/pack/rotate/start {"account": "work"} -> {"account": "work", "started_at": 1700000000000, "sign_in_seen": "not_seen"}"""
    try:
        body = StartBody.model_validate(json.loads(await request.body()))
    except (ValueError, ValidationError) as exc:
        raise api_error(400, "invalid_request", exc) from exc
    snap = {u.id: u for u in poller.snapshot().accounts}

    def write() -> Dict[str, Any]:
        found = [a for a in _accounts() if a.id == body.account and a.provider in rotation.PROVIDERS]
        if not found:
            return {}
        now = int(time.time() * 1000)
        usage = snap.get(body.account)
        with closing(peer_auth.open_db()) as conn:
            rotation.record_start(conn, body.account, found[0].provider, now, usage)
            row = rotation.read_rows(conn)[body.account]
        return {"account": body.account, "provider": found[0].provider, "started_at": now, "sign_in_seen": rotation.sign_in_seen(row, usage)}

    try:
        done = await asyncio.to_thread(write)
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise api_error(503, "rotate_unavailable", exc) from exc
    if not done:
        default = snap.get(body.account)
        if body.account == AUTO_DEFAULT_ACCOUNT_ID and default is not None and default.provider == "claude":
            raise api_error(409, "rotate_terminal_only")
        raise api_error(404, "rotate_unknown_account")
    log.info("pack_rotate_started", account=done["account"], provider=done.pop("provider"))
    return done


@router.post("/argent", dependencies=_GATES)
async def rotate_argent() -> Dict[str, Any]:
    """Cancel, at Argent, the delegates this computer minted for removed computers (one at a time). Answers each computer's state: none, dead, pending
    or expired. Example: POST /api/v1/pack/rotate/argent -> {"computers": [{"install_id": "iid-x", "state": "dead"}]}"""
    from src.core.argent import pair_sync

    pair = pair_sync.PAIR
    if pair is None:
        raise api_error(409, "rotate_argent_not_running")

    def removed() -> List[str]:
        with closing(peer_auth.open_db()) as conn:
            return [iid for iid, _state, _at in removed_copies.removed_computers(conn)]

    try:
        ids = await asyncio.to_thread(removed)
    except (sqlite3.Error, OSError) as exc:
        raise api_error(503, "rotate_unavailable", exc) from exc
    from src.core.computers import mesh_removal

    sweep = mesh_removal.REMOVAL
    try:
        cur = await asyncio.to_thread(sweep._held) if sweep is not None else None
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise api_error(503, "rotate_unavailable", exc) from exc
    if not isinstance(cur, mesh_removal.RosterV2):
        return {"computers": []}
    ids = [i for i in ids if i != sweep._self and i != cur.alpha and not cur.entry(i)]
    computers: List[Dict[str, str]] = []
    for iid in ids:
        try:
            computers.append({"install_id": iid, "state": await pair.revoke_removed(iid)})
        except (sqlite3.Error, OSError, ValueError) as exc:
            log_failure(503, "rotate_unavailable", None, error_type=type(exc).__name__)
            computers.append({"install_id": iid, "state": "unavailable"})
    return {"computers": computers}
