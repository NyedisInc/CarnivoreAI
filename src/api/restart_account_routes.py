
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.config import settings
from src.core.account_switch import pane_account, restart_account, session_pin
from src.core.account_switch.active import effective_active
from src.core.account_switch.launch_env import _config_path
from src.core.account_switch import store
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.models import RestartAccountOption, RestartAccountsResponse
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(tags=["sessions"])

EMPTY = RestartAccountsResponse()


def _read_row(session_uuid: str) -> Optional[dict]:
    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return None
    with closing(connect(db_path, create=False)) as conn:
        row = conn.execute(
            "SELECT tmux_name, tmux_socket, agent_type, host_key FROM sessions "
            "WHERE session_uuid = ? LIMIT 1", (session_uuid,)).fetchone()
    if row is None or (row["host_key"] or "local") != "local":
        return None
    return {"tmux_name": row["tmux_name"], "socket": row["tmux_socket"], "agent_type": row["agent_type"]}


def _build(config_path: Path, session_uuid: Optional[str], accounts_all, options, current_id: Optional[str]):
    pinned_id = session_pin.pin_for(config_path, session_uuid)
    ids = {o.id for o in options}
    pinned = pinned_id in ids
    selected = pinned_id if pinned else None
    active = effective_active(accounts_all, store.read_switch(config_path), session_pin.PIN_PROVIDER).account_id
    active_id = active if active in ids else None
    if selected is None:
        selected = active_id or (current_id if current_id in ids else None)
    out: List[RestartAccountOption] = [
        RestartAccountOption(id=a.id, name=a.name, color=a.color, is_current=a.id == current_id)
        for a in options
    ]
    return RestartAccountsResponse(options=out, selected_id=selected, current_id=current_id, active_id=active_id, pinned=pinned)


@router.get(
    "/sessions/{session_uuid}/restart/accounts",
    response_model=RestartAccountsResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def restart_accounts(session_uuid: str) -> RestartAccountsResponse:
    """The accounts this session can restart on and still resume.

    Description: only claude accounts whose profile is the default login or a
      managed profile with first-run setup done and shared transcripts
      (``session_pin.is_launchable``), because a conversation started under one
      account resumes on another only through those shared links. The pane's
      own account is read from tmux (read only).
    Inputs: session_uuid (str) - the row's durable key.
    Output: RestartAccountsResponse - ``options`` empty when nothing applies.
    Raises: HTTPException 503 (datastore unreadable), 500 (config.json unusable).
    """
    try:
        row = await run_in_threadpool(_read_row, session_uuid)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="restart_accounts") from exc
    if row is None or restart_account.family_of(row["agent_type"]) != restart_account.ACCOUNT_FAMILY:
        return EMPTY
    config_path = _config_path()
    try:
        accounts_all = await run_in_threadpool(session_pin.all_accounts, config_path)
        options = await run_in_threadpool(session_pin.launchable_accounts, config_path)
        current_id = None
        if row["tmux_name"]:
            current_id = await pane_account.resolve_pane_account(
                row["socket"], row["tmux_name"], session_pin.PIN_PROVIDER, accounts_all)
        return await run_in_threadpool(_build, config_path, session_uuid, accounts_all, options, current_id)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("restart_accounts_unreadable", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="the account list could not be read")


@router.get("/launch/accounts", response_model=RestartAccountsResponse, dependencies=[Depends(require_auth)])
async def launch_accounts() -> RestartAccountsResponse:
    """The accounts a NEW agent can launch on (the launch picker's account dropdown), owner only.

    Description: the same launchable list the restart dialog offers (``session_pin.launchable_accounts``);
      ``selected_id`` is the effective active account when it is launchable, else None; ``current_id`` is None
      and ``pinned`` false, since no session exists yet. Read only.
    Output: RestartAccountsResponse.
    Raises: HTTPException 500 (config.json unusable).
    """
    config_path = _config_path()
    try:
        accounts_all = await run_in_threadpool(session_pin.all_accounts, config_path)
        options = await run_in_threadpool(session_pin.launchable_accounts, config_path)
        return await run_in_threadpool(_build, config_path, None, accounts_all, options, None)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("launch_accounts_unreadable", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="the account list could not be read")
