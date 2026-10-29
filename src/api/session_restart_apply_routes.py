
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from src.api.peer_auth import require_peer_sessions
from src.config import settings
from src.core import restart_inflight
from src.core.agent_families import get_family
from src.core.session_label import sanitize_tmux_name
from src.models import RestartSessionResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post(
    "/sessions/{session_uuid}/restart",
    response_model=RestartSessionResponse,
    status_code=201,
    dependencies=[Depends(require_peer_sessions)],
)
async def restart_session(request: Request, session_uuid: str):
    """Restart a stopped row, refusing a second restart of it while one runs.

    Description: the route seam. Holds the per-row restart claim
      (src/core/restart_inflight.py) around :func:`_restart_session`, so a
      double click answers 409 instead of spawning a second pane.
    Inputs: request (Request). session_uuid (str) - the row's durable id.
    Output: RestartSessionResponse.
    Raises: HTTPException 409 when a restart of this row is in progress,
      plus everything :func:`_restart_session` raises.
    """
    try:
        with restart_inflight.claim(session_uuid):
            return await _restart_session(request, session_uuid)
    except restart_inflight.RestartInFlightError as exc:
        raise HTTPException(
            status_code=409, detail=restart_inflight.http_detail(exc)
        )


async def _restart_session(request: Request, session_uuid: str):
    from contextlib import closing

    from src.core import session_restart
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    session_manager = request.app.state.session_manager
    db_path = db_path_for(settings.get_state_dir())

    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail="no datastore yet, so there is no session to restart",
        )

    def _resolve():
        from src.api.remote_route_guard import stored_host_key

        with closing(connect(db_path, create=False)) as conn:
            host_key = stored_host_key(conn, session_uuid)
            remote = {} if host_key == "local" else {"check_transcript": False}
            return session_restart.resolve_restart_source(
                conn, session_uuid=session_uuid, **remote
            ), host_key

    try:
        source, host_key = await run_in_threadpool(_resolve)
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if source.outcome == session_restart.RESTART_UNRESOLVED:
        raise HTTPException(
            status_code=404, detail=source.detail or "session not found"
        )

    if host_key != "local":
        return await _restart_remote(session_manager, session_uuid, host_key, source)

    from src.api.recreate_routes import _socket_name
    from src.core import restart_live_gate

    running = await run_in_threadpool(
        restart_live_gate.bound_instance_running,
        db_path, session_uuid, _socket_name(),
    )
    if running:
        logger.warning("restart_refused_already_running", session_uuid=session_uuid)
        raise HTTPException(
            status_code=409,
            detail={
                "code": restart_live_gate.ALREADY_RUNNING_CODE,
                "message": "this session is already running",
            },
        )

    if source.outcome == session_restart.RESTART_CONVERSATION_MISSING:
        logger.warning(
            "restart_refused_conversation_missing",
            replaced_session_uuid=session_uuid,
            replaced_session_id=source.parent_id,
            conversation_row_id=source.conversation_row_id,
            claude_session_uuid=source.claude_session_uuid,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                source.detail
                or "the conversation this session names is not on disk"
            ),
        )

    resumable = source.outcome == session_restart.RESTART_RESUMABLE
    label = (source.title or "").strip() or None
    tmux_safe_name = (sanitize_tmux_name(label) or None) if label else None

    logger.info(
        "api_restart_session_request",
        replaced_session_uuid=session_uuid,
        replaced_session_id=source.parent_id,
        conversation="resumed" if resumable else "none_recorded",
        conversation_row_id=source.conversation_row_id,
        label=label,
    )

    import uuid as _uuid

    from src.api.launch_profile_errors import refuse_gone_profile

    refuse_gone_profile(settings, source.agent_type, source.launch_record)
    # active account
    from src.core.account_switch import restart_account
    from src.core.account_switch.launch_env import _config_path

    account_plan = await restart_account.resolve(
        _config_path(), session_uuid=session_uuid, family=restart_account.family_of(source.agent_type))
    try:
        child = await session_manager.create_session(
            session_id=f"ses_{_uuid.uuid4().hex[:8]}",
            working_dir=source.working_dir,
            project_name=tmux_safe_name,
            agent_type=source.agent_type,
            model=source.model,
            agent_extra_args=(
                session_restart.resume_arguments(
                    source.claude_session_uuid,
                    family=get_family(source.agent_type).name,
                )
                if resumable else None
            ),
            label=label,
            reuse_session_id=source.parent_id,
            claude_account=account_plan.account_id,
        )
    except Exception as exc:
        logger.warning(
            "restart_create_failed",
            replaced_session_uuid=session_uuid,
            label=label,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"could not create the replacement session: {exc}",
        )

    child_tmux = getattr(child, "tmux_session", None)

    def _verify_reuse():
        with closing(connect(db_path, create=False)) as conn:
            row = conn.execute(
                "SELECT tmux_name, lifecycle FROM sessions WHERE id = ? "
                "LIMIT 1",
                (source.parent_id,),
            ).fetchone()
            if row is None:
                return False
            return (
                row["tmux_name"] == child_tmux
                and row["lifecycle"] == "running"
            )

    reused = False
    detail = source.detail if not resumable else None
    try:
        reused = bool(await run_in_threadpool(_verify_reuse))
    except DatastoreUnreadableError as exc:
        # could not
        note = (
            f"the session was restarted, but whether it kept its "
            f"original record could not be confirmed: {exc}"
        )
        detail = f"{detail} {note}" if detail else note
    else:
        if not reused:
            note = (
                "the session was restarted, but it could not keep its "
                "original record and now has a separate one; it works, "
                "and it may appear as a second entry"
            )
            detail = f"{detail} {note}" if detail else note

    return RestartSessionResponse(
        success=True,
        session=child.model_dump() if hasattr(child, "model_dump") else {},
        conversation="resumed" if resumable else "none_recorded",
        replaced_session_id=source.parent_id,
        row_reused=reused,
        title_carried=label,
        detail=detail,
    )


async def _restart_remote(session_manager, session_uuid: str, host_key: str, source):
    from src.core.hosts.registry import HostUnavailable
    from src.core.hosts.remote_restart import RemoteRestartRefused, restart_stopped

    try:
        result = await restart_stopped(session_manager, session_uuid=session_uuid,
                                       host_key=host_key, source=source)
    except HostUnavailable as exc:
        raise HTTPException(status_code=exc.status,
                            detail={"code": exc.code, "detail": str(exc)})
    except RemoteRestartRefused as exc:
        raise HTTPException(status_code=exc.status, detail=(
            {"code": exc.code, "message": exc.detail} if exc.code else exc.detail))
    except (ValueError, RuntimeError) as exc:
        logger.warning("restart_remote_create_failed", host=host_key, error=str(exc))
        raise HTTPException(status_code=500,
                            detail=f"could not create the replacement session: {exc}")
    return RestartSessionResponse(**result)
