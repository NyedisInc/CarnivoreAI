
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from src.api import recreate_routes as rr
from src.core.pack.identity import home as project_home
from src.core.pack.move import account as account_launch
from src.core.session_recreate import RECREATE
from src.core.session_respawn import RESPAWN_TRANSCRIPT_MISSING
from src.api.error_response import api_error

TRANSCRIPT_MISSING_CODE = "transcript_missing"

logger = structlog.get_logger()


async def recreate_by_uuid(
    session_uuid: str,
    agent_type: str,
    *,
    get_manager: Callable[[], Any],
    row_overrides: Optional[Dict[str, Any]] = None,
    account_id: Optional[str] = None,
    account_pinned: bool = False,
    fresh: bool = False,
    extra_env: Optional[Dict[str, str]] = None,
    fresh_if_transcript_absent: bool = False,
    fork: bool = False,
    swarm_args: Optional[List[str]] = None,
) -> "rr.RecreateResponse":
    from src.api.launch_profile_errors import unknown_profile_codes
    from src.api.swarm_switch_routes import refuse_held_body
    from src.config import settings

    await refuse_held_body(session_uuid)

    config_dir = (extra_env or {}).get("CLAUDE_CONFIG_DIR")
    corpus = Path(config_dir) / "projects" if config_dir else None
    facts = await run_in_threadpool(rr._gather, session_uuid, row_overrides, fresh=fresh, corpus_root=corpus)
    if fresh_if_transcript_absent and not fresh and facts["directory"].refuses:
        fresh = True
        facts = await run_in_threadpool(rr._gather, session_uuid, row_overrides, fresh=True, corpus_root=corpus)
    if not fork and not fresh and facts.get("extra_args"):
        fork = await _share_fork_due(session_uuid, facts["row"])
    if fork and facts["extra_args"]:
        facts["extra_args"] = [*facts["extra_args"], "--fork-session"]
    if swarm_args:
        facts["extra_args"] = [*swarm_args, *(facts["extra_args"] or [])]
    row = facts["row"]
    name = facts["name"]
    presence = facts["presence"]
    session_uuid = str(row.get("session_uuid"))
    await project_home.require_active(row.get("working_dir"))

    choice = rr.validate_agent_choice(
        settings,
        agent_type,
        model=row.get("model"),
        extra_args=facts["extra_args"],
    )
    plan = rr.plan_recreate(
        row,
        row_read_ok=True,
        presence=presence,
        choice_verdict=choice.verdict,
        choice_command=choice.command,
        choice_detail=choice.detail,
        agent_type=agent_type,
        directory=facts["directory"],
    )
    if plan.kind != RECREATE or not plan.actionable:
        missing = plan.kind == RESPAWN_TRANSCRIPT_MISSING
        logger.info(
            "recreate_refused",
            name=name,
            session_uuid=session_uuid,
            presence=presence.outcome,
            kind=plan.kind,
        )
        return rr.RecreateResponse(
            status="refused",
            session_uuid=session_uuid,
            session_name=name,
            presence=plan.presence,
            conversation=plan.conversation,
            command=plan.command,
            working_dir=plan.working_dir,
            detail=plan.detail,
            **({"code": TRANSCRIPT_MISSING_CODE, "codes": [TRANSCRIPT_MISSING_CODE]} if missing
               else unknown_profile_codes(settings, agent_type, choice.verdict)),
        )

    import uuid as _uuid

    from src.core.account_switch import restart_account
    from src.core.account_switch.launch_env import _config_path
    from src.core.account_switch.session_pin import PinError

    try:
        account_plan = await restart_account.resolve(
            _config_path(), session_uuid=session_uuid, family=restart_account.family_of(agent_type),
            requested=account_id, pinned_box=account_pinned)
    except PinError as exc:
        raise api_error(400, "account_refused", exc, session_uuid=session_uuid) from exc
    if extra_env is None and not account_id and restart_account.family_of(agent_type) == restart_account.ACCOUNT_FAMILY:
        launch = await run_in_threadpool(account_launch.launch_for_session, _config_path(), session_uuid)
        if launch is None:
            return rr.RecreateResponse(
                status="refused", session_uuid=session_uuid, session_name=name, presence=plan.presence,
                conversation=plan.conversation, command=plan.command, working_dir=plan.working_dir,
                detail=account_launch.NOT_USABLE_DETAIL, code=account_launch.NOT_USABLE_CODE, codes=[account_launch.NOT_USABLE_CODE])
        extra_env = launch["extra_env"]
    from src.core.sessions.name_locks import hold_adopt

    manager = get_manager()
    try:
        async with hold_adopt(manager, plan.tmux_name):
            session = await manager.create_session(
                session_id=f"ses_{_uuid.uuid4().hex[:8]}",
                working_dir=plan.working_dir,
                auto_start_claude=True,
                project_name=plan.tmux_name,
                agent_type=agent_type,
                model=row.get("model"),
                agent_extra_args=facts["extra_args"],
                label=plan.label,
                reuse_session_id=plan.reuse_session_id,
                claude_account=account_plan.account_id,
                extra_env=extra_env,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        raise api_error(500, "session_recreate_failed", exc, name=name, session_uuid=session_uuid) from exc

    await restart_account.persist(_config_path(), session_uuid, account_plan)
    if fresh and plan.reuse_session_id is not None:
        await run_in_threadpool(_clear_conversation, int(plan.reuse_session_id))
    logger.info(
        "recreate_started",
        name=name,
        session_uuid=session_uuid,
        tmux_session=getattr(session, "tmux_session", None),
        agent_type=agent_type,
        conversation=plan.conversation,
    )
    return rr.RecreateResponse(
        status="started",
        session_uuid=session_uuid,
        session_name=name,
        session_id=getattr(session, "id", None),
        tmux_session=getattr(session, "tmux_session", None),
        presence=plan.presence,
        conversation=plan.conversation,
        command=plan.command,
        working_dir=plan.working_dir,
        detail=plan.detail,
    )


async def _share_fork_due(session_uuid: str, row: Dict[str, Any]) -> bool:
    from src.core.crate_import import fork_marker

    try:
        return await run_in_threadpool(fork_marker.wake_forks_at, rr._db_path(), session_uuid, row.get("claude_session_uuid"))
    except (rr.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.error("share_fork_marker_unreadable", session_uuid=session_uuid, error=str(exc)[:120])
        raise HTTPException(status_code=503, detail="the share marker could not be read; nothing was started")


def _clear_conversation(row_id: int) -> None:
    from contextlib import closing

    from src.core.db import connect

    with closing(connect(rr._db_path(), create=False)) as conn:
        conn.execute("UPDATE sessions SET claude_session_uuid = NULL WHERE id = ?", (row_id,))
        conn.commit()
