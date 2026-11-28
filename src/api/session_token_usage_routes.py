
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.error_response import api_error
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote, remote_target
from src.config import settings
from src.core.account_switch import pane_account, store
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.agy.session_account import session_account
from src.core.attention.codex_pane_home import pane_codex_home
from src.core.attention.evidence import FAMILY_CODEX
from src.core.pack.jobs.usage_rollup import delegated_for
from src.core.session_token_usage.account_resolve import resolve_session_account
from src.core.session_token_usage.per_request import DEFAULT_LIMIT, MAX_LIMIT, read_session_requests
from src.core.session_token_usage.reader import (
    SessionSubject,
    read_session_token_usage,
)
from src.models.per_request_usage import SessionRequestUsage
from src.models.session_token_usage import SessionTokenUsage

logger = structlog.get_logger()
router = APIRouter()


async def _resolve_subject_ref(session_manager: Any, session_id: str) -> Optional[Dict[str, Any]]:
    fast = getattr(session_manager, "resolve_session_ref", None)
    if callable(fast):
        return await fast(session_id)
    info = await session_manager.get_session_info(session_id)
    if info is None:
        return None
    tmux_name = info.tmux_session
    return {
        "session_id": info.session.id if info.session is not None else session_id,
        "tmux_session": tmux_name,
        "working_dir": info.session.working_dir if info.session is not None else None,
        "agent_family": info.agent_family,
        "session_uuid": getattr(info, "session_uuid", None),
        "claude_session_uuid": session_manager.claude_uuid_for_tmux_name(tmux_name) if tmux_name else None,
        "tmux_created_epoch": getattr(info.session, "tmux_created_epoch", None) if info.session is not None else None,
    }


async def _read_token_usage_for_ref(session_manager: Any, session_id: str, ref: Dict[str, Any]) -> SessionTokenUsage:
    tmux_name = ref.get("tmux_session")
    working_dir = ref.get("working_dir")
    agent_family = ref.get("agent_family")
    conversation_uuid = ref.get("claude_session_uuid")
    if not conversation_uuid and tmux_name:
        conversation_uuid = await asyncio.to_thread(session_manager.claude_uuid_for_tmux_name, tmux_name)
    epoch = ref.get("tmux_created_epoch")

    subject = SessionSubject(
        agent_family=agent_family,
        conversation_uuid=conversation_uuid,
        working_dir=working_dir,
    )
    read_kwargs: Dict[str, Any] = {}
    if agent_family == FAMILY_CODEX and tmux_name:
        read_kwargs["codex_home"] = await asyncio.to_thread(pane_codex_home, session_manager.tmux_socket_name(), tmux_name)
    usage = await asyncio.to_thread(read_session_token_usage, subject, **read_kwargs)

    config_path = Path(settings.auth_config_file).expanduser()
    profile_dir = None
    unattributable = False
    provider = pane_account.FAMILY_PROVIDER.get(agent_family or "")
    if provider and tmux_name:
        pane = await pane_account.read_pane_profile_cached(
            session_manager.tmux_socket_name(), tmux_name, PROFILE_ENV_VARS[provider], epoch=epoch
        )
        profile_dir = pane.value if pane.readable else None
        unattributable = not pane.readable and await asyncio.to_thread(
            _switched_in, config_path, provider
        )
    usage.account = None if unattributable else await asyncio.to_thread(
        resolve_session_account,
        config_path,
        agent_family=agent_family,
        profile_dir=profile_dir,
    )
    if usage.family == "agy":
        usage.account = await asyncio.to_thread(session_account, settings.get_state_dir(), conversation_uuid)

    usage.delegated = await asyncio.to_thread(delegated_for, session_id, ref.get("session_uuid"))

    logger.debug(
        "session_token_usage_read",
        session_id=session_id,
        state=usage.state,
        family=usage.family,
        account=usage.account.id if usage.account is not None else None,
    )
    return usage


class SessionHydrateRequest(BaseModel):
    """Batched token-usage hydration for visible layout cells (#3290)."""

    session_ids: List[str] = Field(default_factory=list, max_length=64)


class SessionHydrateResponse(BaseModel):
    """Map of session_id -> SessionTokenUsage for resolved local sessions (#3290)."""

    token_usage: Dict[str, SessionTokenUsage] = Field(default_factory=dict)


@router.post(
    "/sessions/hydrate",
    response_model=SessionHydrateResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def hydrate_sessions(request: Request, body: SessionHydrateRequest) -> SessionHydrateResponse:
    """Hydrate token-usage payloads for multiple visible sessions in ONE HTTP round-trip (#3290)."""
    session_manager = request.app.state.session_manager
    unique_ids: List[str] = []
    seen = set()
    for sid in body.session_ids:
        s = (sid or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique_ids.append(s)
    if not unique_ids:
        return SessionHydrateResponse(token_usage={})

    sem = asyncio.Semaphore(6)

    async def _one(sid: str) -> tuple[str, Optional[SessionTokenUsage]]:
        if remote_target(session_manager, sid) is not None:
            return sid, None
        async with sem:
            ref = await _resolve_subject_ref(session_manager, sid)
            if ref is None:
                return sid, None
            return sid, await _read_token_usage_for_ref(session_manager, sid, ref)

    pairs = await asyncio.gather(*(_one(sid) for sid in unique_ids))
    return SessionHydrateResponse(
        token_usage={sid: usage for sid, usage in pairs if usage is not None}
    )


@router.get(
    "/sessions/{session_id}/token-usage",
    response_model=SessionTokenUsage,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_token_usage(
    request: Request, session_id: str
) -> SessionTokenUsage:
    """Token spend, cost estimate and context headroom for one session.

    Description: resolves the session via ``resolve_session_ref`` (zero-I/O
      in-memory lookup, falling back to ``get_session_info`` on stand-ins),
      accepting both a created id and an ``adopted:<tmux-name>`` id.
    Inputs: request (Request) - carries the session manager on app state.
      session_id (str) - a session row id, created or adopted.
    Output: SessionTokenUsage - flat, one level, three states.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/adopted:cloude_x/token-usage
    """
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "the token usage read")

    ref = await _resolve_subject_ref(session_manager, session_id)
    if ref is None:
        raise HTTPException(
            status_code=404, detail=f"No session with id {session_id!r}"
        )
    return await _read_token_usage_for_ref(session_manager, session_id, ref)


@router.get(
    "/sessions/{session_id}/token-usage/requests",
    response_model=SessionRequestUsage,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_token_usage_requests(
    request: Request,
    session_id: str,
    since: Optional[str] = Query(None, description="ISO-8601; only requests after this instant"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> SessionRequestUsage:
    """One row per model request of the session's current conversation, across main, sub-agent and workflow-agent files.

    Description: read-only and generic (no Argent knowledge): request id, agent id by file, model and four token classes,
      never dollars. Codex answers ``not_applicable``. Oldest first; ``truncated`` and ``next_since`` continue a long answer.
    Inputs: request (Request); session_id (str); since (str | None); limit (int).
    Output: SessionRequestUsage.
    Raises: HTTPException 404 - unknown session; 422 - ``since`` is not ISO-8601.
    Example: GET /api/v1/sessions/ses_abc/token-usage/requests?since=2026-11-05T10:00:00Z
    """
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "the per-request token usage read")
    ref = await _resolve_subject_ref(session_manager, session_id)
    if ref is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    tmux_name = ref.get("tmux_session")
    conv_uuid = ref.get("claude_session_uuid") or (
        await asyncio.to_thread(session_manager.claude_uuid_for_tmux_name, tmux_name) if tmux_name else None
    )
    subject = SessionSubject(
        agent_family=ref.get("agent_family"),
        conversation_uuid=conv_uuid,
        working_dir=ref.get("working_dir"),
    )
    try:
        return await asyncio.to_thread(read_session_requests, subject, since=since, limit=limit)
    except ValueError as exc:
        raise api_error(422, "token_usage_limit_invalid", exc, limit=limit) from exc


def _switched_in(config_path: Path, provider: str) -> bool:
    try:
        return store.read_switch(config_path).active_for(provider) is not None
    except (FileNotFoundError, ValueError, OSError):
        return False
