
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from src.api import peer_auth
from src.api.auth import require_auth
from src.config import settings
from src.core.db import DatastoreUnreadableError
from src.core.federation import peer_fanout, peer_launchers
from src.core.hosts import store

router = APIRouter(tags=["launchers"])


@router.get("/launchers/summary", response_model=peer_launchers.LauncherSummary,
            dependencies=[Depends(peer_auth.require_peer_sessions)])
async def get_launchers_summary() -> peer_launchers.LauncherSummary:
    """This computer's launchers: id, name, family. No flag, env, secret, account or command."""
    return peer_launchers.summary_of(settings.get_launch_profiles())


@router.get("/launchers/computer/{host_key}", dependencies=[Depends(require_auth)])
async def get_computer_launchers(host_key: str, request: Request) -> Dict[str, Any]:
    """One paired computer's launchers, asked at request time; ``{status: unavailable, reason}`` when it cannot answer."""
    if peer_fanout.is_peer_call(request):
        return {"status": "unavailable", "reason": "not_local"}
    answers = await peer_fanout.ask_peers("/launchers/summary", peer_auth.open_db, only=host_key)
    if not answers and _is_ssh_host(host_key):
        return {"status": "ssh", "families": peer_launchers.ssh_families()}
    return peer_launchers.shown_for(answers)


def _is_ssh_host(host_key: str) -> bool:
    try:
        with closing(peer_auth.open_db()) as conn:
            return store.get_host(conn, host_key).kind == "ssh"
    except (DatastoreUnreadableError, store.HostsUnavailable, store.HostNotFound):
        return False
