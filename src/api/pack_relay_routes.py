
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.api.peer_auth import open_db
from src.config import settings
from src.core.computers import direction
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.relay import runtime as relay_runtime, targets
from src.core.provider_ledger import accounts_store

router = APIRouter(prefix="/pack/relay", tags=["pack-relay"], dependencies=[Depends(require_auth)])


class RelayBody(BaseModel):
    """The machines this account relays to. An empty list switches the account off."""

    model_config = ConfigDict(extra="forbid")

    machines: List[str] = Field(max_length=32)


def _claude_account_ids() -> List[str]:
    try:
        rows = accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except (OSError, ValueError):
        return []
    return [a.id for a in rows if a.provider == "claude"]


def _read() -> Dict[str, Any]:
    accounts_ids = _claude_account_ids()
    with closing(open_db()) as conn:
        out: Dict[str, Any] = targets.summary(conn)
        defaults = [a for a in accounts_ids if targets.default_mode(conn, a)]
    candidates = relay_runtime.candidate_ids() if defaults else []
    for account in defaults:
        have = {e["machine"] for e in out.get(account, [])}
        out.setdefault(account, []).extend(
            {"machine": iid, "profile": "", "state": "on", "last_expiry_pushed": None, "last_push_at": None}
            for iid in candidates if iid not in have)
    return {"accounts": out, "default_on": defaults}


def _write(account: str, install_ids: List[str], sender_install_id: str) -> List[str]:
    with closing(open_db()) as conn:
        return targets.set_machines(conn, account, install_ids, sender_install_id)


@router.get("")
async def get_relay() -> Dict[str, Any]:
    """Per account: each target machine, its relay state and the last expiry pushed. Empty means nothing relays."""
    return await asyncio.to_thread(_read)


@router.put("/{account}")
async def put_relay(account: str, body: RelayBody, request: Request) -> Dict[str, Any]:
    """Set exactly which machines mirror this Claude account (none switches it off). 404 for an unknown account or machine."""
    if account not in await asyncio.to_thread(_claude_account_ids):
        raise HTTPException(404, {"code": "account_unknown", "detail": "no Claude account here has that id"})
    install_ids: List[str] = []
    wired = machines_runtime.wiring()
    if body.machines:
        if wired is None:
            raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"})
        peers = await asyncio.to_thread(wired.peers)
        for name in body.machines:
            found = wired.runtime.resolve(name, peers)
            if found is None or found == wired.runtime.install_id:
                raise HTTPException(404, {"code": "machine_unknown",
                                          "detail": f"no other machine in the Pack matches {name[:64]}"})
            if direction.contained(found):
                raise HTTPException(409, {"code": direction.REFUSAL_CODE, "detail": "that computer is set to one way and receives no credentials"})
            install_ids.append(found)
    dropped = await asyncio.to_thread(_write, account, install_ids, wired.runtime.install_id if wired is not None else "")
    if dropped and relay_runtime.RELAY is not None:
        await relay_runtime.RELAY.revoke(account, dropped)
    return await asyncio.to_thread(_read)
