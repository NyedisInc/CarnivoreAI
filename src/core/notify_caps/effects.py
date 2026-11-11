
from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core.mcp import federated
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.mcp.protocol import BatchView
from src.core.notify_caps import owner_reply_port
from src.core.notify_caps.owner_reply_port import OwnerReplyDeclined, OwnerReplyRefused, OwnerReplyUnavailable

logger = structlog.get_logger()

Result = Tuple[int, Dict[str, Any]]

GONE: Result = (409, {"error": "already_answered", "where": "elsewhere"})


def is_remote(session_id: str) -> bool:
    return session_id.startswith("remote:")


async def peer_info(session_id: str) -> Optional[Any]:
    for info in await federated.peer_infos():
        if info.session.id == session_id:
            return info
    return None


def refused_from(exc: ToolError) -> Result:
    text = str(exc)
    if text.startswith("refused (409)"):
        return GONE
    return 409, {"error": "refused", "reason": text[:120]}


async def forward_dialog(session_id: str, fingerprint: str, body_choice: Dict[str, Any]) -> Result:
    info = await peer_info(session_id)
    if info is None:
        return GONE
    try:
        await federated.forward(info, "POST", "/sessions/{session_id}/dialog/answer",
                                {"fingerprint": fingerprint, "choice": body_choice, "source": "owner_phone"})
    except ToolError as exc:
        return refused_from(exc)
    return 200, {"state": "sent", "agent": str(info.label or info.tmux_session or ""), "working": False}


async def send_reply(app_state: Any, session_id: str, text: str, thread: Optional[str]) -> Result:
    from src.core.crosstalk import bus

    view = BatchView(app_state.session_manager, SimpleNamespace(state=app_state))
    caller = AgentCaller(session_id="owner", tmux_name="owner", current_session_id="owner", token_name="owner")
    try:
        result = await bus.send(view, caller, to=session_id, text=text, thread=thread, owner_approved=True)
    except ToolError as exc:
        return refused_from(exc)
    if result.get("receipt") == "stuck":
        return 409, {"error": "refused", "reason": str(result.get("reason") or "stuck")[:120]}
    return 200, {"state": "sent", "agent": "", "working": False}


async def reopen(app_state: Any, session_id: str) -> Result:
    if is_remote(session_id):
        info = await peer_info(session_id)
        if info is None:
            return GONE
        try:
            answer = await federated.forward(info, "POST", "/sessions/respawn", {"confirm_restart_live": False})
        except ToolError as exc:
            return refused_from(exc)
        name = str(info.label or info.tmux_session or "")
    else:
        from src.api.session_attach_routes import respawn_or_http

        manager = app_state.session_manager
        info = await manager.get_session_info(session_id)
        if info is None or not info.tmux_session:
            return GONE
        try:
            answer = await respawn_or_http(manager, info.tmux_session, live_restart_confirmed=False)
        except HTTPException as exc:
            return 409, {"error": "refused", "reason": str(exc.detail)[:120]}
        name = str(info.label or info.tmux_session or "")
    if not answer.get("ok", True):
        return 409, {"error": "refused", "reason": str(answer.get("kind") or "not_restarted")[:120]}
    return 200, {"state": "sent", "agent": name, "working": False}


IDLE_STATUSES = frozenset({"idle", "finished_unread"})


FRESH_WAIT_SECONDS = 4.0
FRESH_POLL_SECONDS = 0.25


def has_background_work(evidence: Any) -> bool:
    from src.core.attention.background_claims import standing_background_claims  # noqa: PLC0415
    from src.core.attention.workflow_activity import workflow_active  # noqa: PLC0415

    parked = getattr(evidence, "parked_work", None)
    return bool((getattr(evidence, "background_open", None) or 0) > 0 or standing_background_claims(evidence) > 0
                or (getattr(getattr(evidence, "subagents", None), "running", None) or 0) > 0
                or getattr(getattr(evidence, "timers", None), "live", None) or getattr(parked, "is_live", False) or workflow_active(evidence))


async def _fresh_observations(watcher: Any, session_ids: list) -> None:
    before = {sid: getattr(watcher.observation_for(sid), "revision", 0) for sid in session_ids}
    deadline = time.monotonic() + FRESH_WAIT_SECONDS
    while time.monotonic() < deadline:
        seen = {sid: watcher.observation_for(sid) for sid in session_ids}
        if all(o is None or o.stale or getattr(o, "revision", 0) > before[sid] for sid, o in seen.items()):
            return
        await asyncio.sleep(FRESH_POLL_SECONDS)


async def restart_agents(app_state: Any, session_ids: Any) -> Result:
    from src.api.session_attach_routes import respawn_or_http  # noqa: PLC0415
    from src.core.attention.evidence import STATE_DONE_IDLE  # noqa: PLC0415
    from src.core.attention.fresh_observation import watcher_of  # noqa: PLC0415
    from src.core.notifications.sources.agent_update import observation_update  # noqa: PLC0415
    from src.core.session_respawn import LIVE_RESTART_REASON_AGENT_UPDATE  # noqa: PLC0415

    manager = app_state.session_manager
    watcher = watcher_of(manager)
    ids = list(dict.fromkeys(str(s) for s in (session_ids if isinstance(session_ids, list) else [])))
    if watcher is not None:
        await _fresh_observations(watcher, [sid for sid in ids if not is_remote(sid)])
    restarted = skipped = 0
    for session_id in ids:
        info = None if is_remote(session_id) else await manager.get_session_info(session_id)
        seen = watcher.observation_for(session_id) if watcher is not None and info is not None else None
        idle = (seen is not None and not seen.stale and seen.verdict.state == STATE_DONE_IDLE
                and getattr(info, "activity_status", None) in IDLE_STATUSES and bool(info.tmux_session)
                and observation_update(seen) is not None and not has_background_work(seen.evidence))
        if not idle:
            skipped += 1
            continue
        try:
            answer = await respawn_or_http(manager, info.tmux_session, live_restart_confirmed=True, require_agent_resume=True,
                                           live_restart_reason=LIVE_RESTART_REASON_AGENT_UPDATE)
        except HTTPException as exc:
            logger.warning("notify_restart_agents_refused", detail=str(exc.detail)[:120])
            skipped += 1
            continue
        if answer.get("ok", True) or answer.get("killed_live_pane"):
            restarted += 1
        else:
            skipped += 1
    if not restarted:
        return 409, {"error": "refused", "reason": "nothing_restarted"}
    return 200, {"state": "sent", "agent": "", "working": False, "restarted": restarted, "skipped": skipped}


async def install_app_update() -> Result:
    from src.api.app_update_routes import install_now

    try:
        await install_now()
    except HTTPException as exc:
        return 409, {"error": "refused", "reason": str(exc.detail)[:120]}
    return 200, {"state": "sent", "agent": "", "working": False}


async def swarm_card_item(question_id: int) -> Optional[int]:
    from src.core.swarm import body  # noqa: PLC0415
    from src.core.db import DatastoreUnreadableError  # noqa: PLC0415

    def read(conn: Any) -> Any:
        return conn.execute("SELECT state, card_ref FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()

    try:
        row = await body.run_db(read)
    except (sqlite3.Error, OSError, DatastoreUnreadableError) as exc:
        logger.warning("notify_swarm_lookup_failed", error_type=type(exc).__name__)
        return None
    if row is None or row[0] != "open" or not str(row[1] or "").isdigit():
        return None
    return int(row[1])


async def swarm_answer(app_state: Any, question: Any, text: str) -> Result:
    try:
        item = await swarm_card_item(int(question))
    except (TypeError, ValueError):
        return 409, {"error": "refused", "reason": "bad_question"}
    if item is None:
        return GONE
    try:
        await owner_reply_port.owner_reply(app_state, item, text)
    except OwnerReplyDeclined:
        return GONE
    except OwnerReplyRefused as exc:
        return 409, {"error": "refused", "reason": exc.code[:120]}
    except OwnerReplyUnavailable:
        return 409, {"error": "refused", "reason": "swarm_off"}
    return 200, {"state": "sent", "agent": "", "working": False}
