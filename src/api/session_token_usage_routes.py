"""What one session has spent, and how full its context is.

ONE READ-ONLY ENDPOINT. It opens a transcript and reports numbers out of
it. It does not shell out, does not touch tmux, spawns nothing and
writes nothing - asking what a session has cost can never change what
the session is doing.

TWO SCOPES IN ONE ANSWER, AND THEY ARE NOT MIXED UP. The counts are one
CONVERSATION's, read out of its transcript. The ``account`` block is the
whole ACCOUNT's, taken from the ledger poller's in-memory snapshot, and
every session running under the same login shares it. It rides this
endpoint rather than a second fetch so the panel makes one request, and
it is resolved by ``session_token_usage/account_resolve.py``, which
answers ``None`` rather than guessing when it cannot tell which account
a session spends from. NOTHING HERE CALLS A PROVIDER OR REFRESHES A
TOKEN: Claude's refresh token is single use, and a second client
refreshing it logs the user's own CLI out.

A REFUSAL IS STILL A 200, with one exception. The response's ``state``
field carries the three outcomes, so "could not read this session's
transcript" is a measured answer the panel renders, not a server fault.
The one 404 is an UNKNOWN SESSION ID: there is no session to report on,
which is a different fact from a session whose usage we could not read.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.config import settings
from src.core.account_switch import pane_account, store
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.session_token_usage.account_resolve import resolve_session_account
from src.core.session_token_usage.reader import (
    SessionSubject,
    read_session_token_usage,
)
from src.models.session_token_usage import SessionTokenUsage

logger = structlog.get_logger()
router = APIRouter()


@router.get(
    "/sessions/{session_id}/token-usage",
    response_model=SessionTokenUsage,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_token_usage(
    request: Request, session_id: str
) -> SessionTokenUsage:
    """Token spend, cost estimate and context headroom for one session.

    Description: resolves the session the way its siblings do, through
      ``session_manager.get_session_info``, which accepts both a created
      id and an ``adopted:<tmux-name>`` id. Reads the conversation uuid
      off the stored row, then hands the three facts to the family
      dispatch on a worker thread.
    Inputs: request (Request) - carries the session manager on app state.
      session_id (str) - a session row id, created or adopted.
    Output: SessionTokenUsage - flat, one level, three states.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/adopted:cloude_x/token-usage
    """
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "the token usage read")

    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(
            status_code=404, detail=f"No session with id {session_id!r}"
        )

    tmux_name = info.tmux_session
    working_dir = info.session.working_dir if info.session is not None else None

    conversation_uuid = (
        session_manager._claude_uuid_for_tmux_name(tmux_name) if tmux_name else None
    )

    subject = SessionSubject(
        agent_family=info.agent_family,
        conversation_uuid=conversation_uuid,
        working_dir=working_dir,
    )
    usage = await asyncio.to_thread(read_session_token_usage, subject)

    config_path = Path(settings.auth_config_file).expanduser()
    profile_dir = None
    unattributable = False
    provider = pane_account.FAMILY_PROVIDER.get(info.agent_family or "")
    if provider and tmux_name:
        pane = await pane_account.read_pane_profile(
            session_manager._tmux_socket_name(), tmux_name, PROFILE_ENV_VARS[provider]
        )
        profile_dir = pane.value if pane.readable else None
        unattributable = not pane.readable and await asyncio.to_thread(
            _switched_in, config_path, provider
        )
    usage.account = None if unattributable else await asyncio.to_thread(
        resolve_session_account,
        config_path,
        agent_family=info.agent_family,
        profile_dir=profile_dir,
    )

    logger.debug(
        "session_token_usage_read",
        session_id=session_id,
        state=usage.state,
        family=usage.family,
        account=usage.account.id if usage.account is not None else None,
    )
    return usage


def _switched_in(config_path: Path, provider: str) -> bool:
    """Has an account been switched in for this provider? Never raises.

    Inputs: config_path (Path); provider (str).
    Output: bool - False when config.json cannot be read, which keeps the
      pre-switch behaviour (the default-login deduction).
    """
    try:
        return store.read_switch(config_path).active_for(provider) is not None
    except (FileNotFoundError, ValueError, OSError):
        return False
