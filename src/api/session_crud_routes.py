
import asyncio
import base64
import os
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from src.api import session_rejoin_capture
from src.api import (
    agent_update_listing, asleep_brief, automation_listing, automation_timers_listing, description_listing, mcp_health_listing, swarm_member_listing, messaging_listing, parked_work_listing, session_account_listing, session_roles_listing, skill_fire_listing, spectator_listing,
    sleep_hold_listing, subagent_listing, timer_listing,
)
from src.api.auth import require_auth
from src.api import peer_auth
from src.api.peer_auth import require_peer_sessions
from src.core.federation import peer_listing
from src.config import settings
from src.core import session_change_notice
from src.core import single_flight
from src.core.ttl_flight import TtlFlight
from src.core.account_switch import create_account
from src.core.launch_profiles import create_seam
from src.core.sessions.errors import SessionCreateFailed, TmuxError
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_profiles.secrets import SecretError
from src.core.pipeline import triggers as save_triggers
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import RemoteRootConflict, backend_host_key, resolve_create_target
from src.core.hosts.registry import HostUnavailable
from src.models import (
    CreateSessionRequest,
    Session,
    SessionInfo,
    SuccessResponse,
)
from typing import Any, Dict, List, Optional

from src.core.swarm import leaders as swarm_leaders
from src.core.swarm import membership
from src.api.launch_profile_errors import gone_profile_error
from src.api.error_response import api_error, refusal_error

logger = structlog.get_logger()
router = APIRouter()


def _refuse_packed_folder(working_dir: str) -> None:
    import sqlite3
    from contextlib import closing

    from src.api import projects_service
    from src.config import settings
    from src.core.project_pack.guard import PACKED_MESSAGE, packed_project_name

    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            name = packed_project_name(conn, os.path.realpath(working_dir))
    except (HTTPException, sqlite3.Error):
        return
    if name:
        raise HTTPException(status_code=409, detail=f"{PACKED_MESSAGE} ({name})")


def _refuse_unsafe_project_root(settings, path: str) -> None:
    from contextlib import closing

    from src.api import projects_service
    from src.core.project_store import normalize_root
    from src.core.project_writes import ProjectRootRefused, refuse_unsafe_root

    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            refuse_unsafe_root(conn, normalize_root(path))
    except ProjectRootRefused as exc:
        raise api_error(409, "project_root_refused", exc, path=path) from exc


@router.post("/sessions", response_model=Session, status_code=201, dependencies=[Depends(require_peer_sessions)])
async def create_session(request: Request, body: CreateSessionRequest):
    """Public create route; no caller-supplied CLI arguments are accepted."""
    return await create_session_with_extra(request, body)


async def create_session_with_extra(request: Request, body: CreateSessionRequest, *,
                                    agent_extra_args: Optional[List[str]] = None,
                                    claude_account: Optional[str] = None,
                                    extra_env: Optional[Dict[str, str]] = None,
                                    session_id: Optional[str] = None):
    try:
        body.host_key, body.working_dir = resolve_create_target(body.host_key, body.working_dir)
    except RemoteRootConflict as exc:
        raise api_error(400, "remote_root_conflict", exc, step="resolve_create_target") from exc
    host_key = body.host_key or LOCAL_HOST_KEY
    if body.account_id and claude_account:
        raise HTTPException(status_code=400, detail="account_id and claude_account are two ways to name one account; pass one")
    try:
        account_plan = await create_account.plan_for_create(
            account_id=body.account_id, account_pinned=body.account_pinned, agent_type=body.agent_type,
            auto_start_claude=body.auto_start_claude,
            is_peer=getattr(getattr(request, "state", None), "peer_grant", None) is not None,
            is_local=host_key == LOCAL_HOST_KEY)
    except create_account.CreateAccountRefused as exc:
        raise api_error(400, "account_refused", exc, account_id=body.account_id) from exc
    claude_account = account_plan.account_id or claude_account
    if body.working_dir and host_key == LOCAL_HOST_KEY:
        _refuse_packed_folder(os.path.expanduser(body.working_dir))
    session_manager = request.app.state.session_manager

    try:
        import uuid
        if session_id is None:
            session_id = f"ses_{uuid.uuid4().hex[:8]}"

        if host_key != LOCAL_HOST_KEY and body.project_parent_dir:
            raise HTTPException(status_code=400, detail=(
                "a new folder cannot be created on a remote host; choose an existing one"))

        if body.working_dir and host_key == LOCAL_HOST_KEY:
            body.working_dir = os.path.expanduser(body.working_dir)

        if body.project_parent_dir:
            from src.core.project_directory import (
                ensure_project_directory,
                resolve_project_directory,
                validate_project_dir_name,
            )

            name_problem = validate_project_dir_name(body.project_name or "")
            if name_problem:
                logger.warning(
                    "project_directory_refused",
                    parent_dir=body.project_parent_dir,
                    code="illegal_name",
                )
                raise HTTPException(status_code=400, detail=name_problem)

            verdict = ensure_project_directory(
                resolve_project_directory(
                    body.project_parent_dir,
                    settings=settings,
                )
            )
            if not verdict.ok:
                logger.warning(
                    "project_directory_refused",
                    parent_dir=body.project_parent_dir,
                    code=verdict.code,
                )
                raise HTTPException(status_code=400, detail=verdict.message)
            body.working_dir = verdict.path
            _refuse_unsafe_project_root(settings, verdict.path)

        if host_key == LOCAL_HOST_KEY:
            create_seam.check_explicit_pick(settings, body.agent_type)

        prompt_args = None
        if body.opening_prompt is not None:
            from src.core.opening_prompt import prompt_launch

            body.agent_type, prompt_args = prompt_launch(
                settings, agent_type=body.agent_type, project_name=body.project_name,
                opening_prompt=body.opening_prompt, auto_start=body.auto_start_claude,
            )

        logger.info(
            "api_create_session_request",
            session_id=session_id,
            working_dir=body.working_dir,
            copy_templates=body.copy_templates,
            cols=body.cols,
            rows=body.rows,
            agent_type=body.agent_type,
            model=body.model,
        )

        member = (await membership.new_session_member(body.working_dir, body.label, body.agent_type)
                  if host_key == LOCAL_HOST_KEY and body.auto_start_claude and not agent_extra_args else None)
        try:
            session = await session_manager.create_session(
                session_id=session_id,
                working_dir=body.working_dir,
                auto_start_claude=body.auto_start_claude,
                copy_templates=body.copy_templates,
                initial_cols=body.cols,
                initial_rows=body.rows,
                project_name=body.project_name,
                agent_type=body.agent_type,
                model=body.model,
                agent_extra_args=(agent_extra_args or []) + (member["argv"] if member else []) + (prompt_args or []),
                label=(body.label or "").strip() or None,
                host_key=host_key,
                claude_account=claude_account,
                extra_env=extra_env,
            )
        except BaseException:
            if member:
                await membership.drop_new_session_member(member)
            raise
        if member:
            await membership.bind_new_session(request.app.state, member, session.id)

        await create_account.pin_after_create(session_manager, session.tmux_session, account_plan)

        if session.working_dir and host_key == LOCAL_HOST_KEY:
            from src.api import projects_service

            projects_service.touch_project_best_effort(
                settings, session.working_dir
            )

        session_change_notice.publish(
            request.app.state,
            session_change_notice.build_structural_notice("created"),
        )

        return session

    except HTTPException:
        raise
    except HostUnavailable as e:
        logger.warning("session_creation_host_unavailable", host=host_key, code=e.code)
        raise refusal_error(e, host=host_key) from e
    except LaunchProfileNotFound as e:
        raise gone_profile_error(e, getattr(e, "available", [])) from e
    except SecretError as e:
        logger.warning("session_creation_launch_secret_unavailable", error=str(e))
        raise api_error(409, "launch_secret_unavailable", e)
    except SessionCreateFailed as e:
        raise api_error(502, "session_launch_failed", e, step="spawn", session_id=session_id) from e
    except ValueError as e:
        raise api_error(400, "session_create_invalid", e, step="validation") from e
    except TmuxError as e:
        raise api_error(502, "session_launch_failed", e, step="backend", session_id=session_id) from e
    except Exception as e:  # noqa: BLE001
        raise api_error(500, "session_create_failed", e, session_id=session_id) from e


@router.get("/sessions", response_model=SessionInfo, dependencies=[Depends(require_peer_sessions)])
async def get_session(
    request: Request,
    session_id: Optional[str] = None,
    include_scrollback: bool = False,
    cols: Optional[int] = None,
    rows: Optional[int] = None,
    scrollback_lines: Optional[int] = Query(
        None, ge=1, le=session_rejoin_capture.MAX_SCROLLBACK_LINES
    ),
):
    """
    Get information about a session.

    ``session_id`` (query, optional) selects a specific session; omitted
    returns the current (most-recently-created) one. Back-compat: existing
    clients call ``GET /sessions`` with no params and get "the" session.

    ``include_scrollback`` (query, optional, default False) - when True
    and the resolved session has a live tmux backend, the response's
    ``initial_scrollback_b64`` field is populated with base64-encoded
    pane-capture bytes. Used by the launchpad's "return to running
    session" path so the client can paint pre-existing history into
    xterm before the WS opens, mirroring the adopt path. Off by default
    so existing callers see no change.

    ``cols`` / ``rows`` (query, optional) - when ``include_scrollback`` is
    True AND both are positive ints, the pane is pre-resized to the
    client's xterm geometry BEFORE the capture call. ``tmux capture-pane``
    snapshots at the pane's CURRENT width, which is whatever the most-
    recent attached client set it to. Without this pre-resize, a mobile
    client (~80 cols) rejoining a session whose pane was last sized by a
    desktop client (~144 cols) gets desktop-width scrollback bytes that
    xterm paints at mobile width - the upper/older history reflows into
    garbled rows. Forcing tmux to re-render at the client's true width
    eliminates that mismatch. The subsequent WS-handshake resize becomes
    a no-op (same dims) on this client; other attached clients see a
    window-event and negotiate to their own width on their own handshake.

    ``scrollback_lines`` (query, optional, 1 to 50000) - with
    ``include_scrollback``, the capture depth in tmux lines instead of the
    configured default. The terminal's scroll-to-top asks one step deeper
    than the rows it holds (R2-11, ``docs/terminal-client-history.md``), so
    each request is one bounded ``capture-pane -S -<N>`` snapshot. A
    non-integer or out-of-range value is refused with 422. The tmux target
    is still the stored session name. Ignored without ``include_scrollback``.

    Raises:
        HTTPException: 404 if the requested (or current) session doesn't exist
    """
    session_manager = request.app.state.session_manager

    session_info = await session_manager.get_session_info(session_id=session_id)

    if not session_info:
        raise HTTPException(status_code=404, detail="No active session")

    if include_scrollback:
        resolved_sid = session_info.session.id

        raw = await asyncio.to_thread(
            session_rejoin_capture.resize_and_capture,
            session_manager,
            session_id=resolved_sid,
            cols=cols,
            rows=rows,
            lines=scrollback_lines,
        )
        if raw:
            session_info.initial_scrollback_b64 = base64.b64encode(raw).decode("ascii")

    return session_info


@router.get(
    "/sessions/list",
    response_model=List[SessionInfo],
    dependencies=[Depends(require_peer_sessions)],
)
async def list_sessions(request: Request):
    """List ALL live sessions (oldest first).

    Multi-session: two browser tabs can each be attached to a different
    session. The launchpad's "Running Sessions" list uses this to surface
    every owned-and-live session (in addition to ``/sessions/attachable``
    for external/detached ones).
    """
    infos = await build_owner_listing(request.app.state)
    return await peer_listing.for_caller(
        infos, is_peer=getattr(request.state, "peer_grant", None) is not None, open_db=peer_auth.open_db)


OWNER_LISTING_CACHE: TtlFlight = TtlFlight("owner_listing", 1.0)


async def build_owner_listing(app_state: Any) -> List[SessionInfo]:
    return list(await OWNER_LISTING_CACHE.get(lambda: _assemble_owner_listing(app_state)))


async def _assemble_owner_listing(app_state: Any) -> List[SessionInfo]:
    session_manager = app_state.session_manager
    if hasattr(session_manager, "list_session_infos"):
        flight = single_flight.flight_on(
            session_manager,
            single_flight.SESSION_LIST_FLIGHT_ATTR,
            single_flight.SESSION_LIST_FLIGHT_NAME,
        )
        infos = await flight.run(session_manager.list_session_infos)
    else:
        one = await session_manager.get_session_info()
        infos = [one] if one else []
    await spectator_listing.mark_shared(app_state, infos)
    subagent_listing.mark_subagents(session_manager, infos)
    timer_listing.mark_timers(session_manager, infos)
    asleep = await asleep_brief.for_listing_ports()
    await automation_timers_listing.mark_automation_timers(app_state, infos, asleep=asleep)
    await session_roles_listing.mark_session_roles(app_state, infos, asleep=asleep)
    sleep_hold_listing.mark_sleep_hold(session_manager, infos)
    skill_fire_listing.mark_skill_fires(session_manager, infos)
    parked_work_listing.mark_parked_work(session_manager, infos)
    agent_update_listing.mark_agent_update(session_manager, infos)
    mcp_health_listing.mark_mcp_health(app_state, infos)
    session_account_listing.mark_session_account(app_state, infos)
    automation_listing.mark_automation(app_state, infos)
    messaging_listing.mark_messaging(app_state, infos)
    description_listing.mark_descriptions(app_state, infos)
    await swarm_member_listing.mark_swarm_members(infos)
    return infos


async def _instance_epoch(backend: Any) -> Optional[int]:
    reader = getattr(backend, "session_created_epoch", None) if backend else None
    if reader is None:
        return None
    try:
        return await reader()
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("close_instance_epoch_unread", error=str(exc))
        return None


async def _mark_closed_in_datastore(
    socket: Optional[str], name: Optional[str], epoch: Optional[int] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> int:
    from contextlib import closing

    from src.core import session_close_lifecycle
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    if not socket or not name:
        return 0
    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return 0

    def _write() -> int:
        with closing(connect(db_path, create=False)) as conn:
            moved = session_close_lifecycle.mark_closed(
                conn, socket=socket, name=name, epoch=epoch, host_key=host_key
            )
            conn.commit()
            return moved

    try:
        return await run_in_threadpool(_write)
    except DatastoreUnreadableError as exc:
        logger.warning(
            "close_lifecycle_not_recorded",
            tmux_socket=socket,
            tmux_name=name,
            error=str(exc),
            note=(
                "the session WAS destroyed; only the row's lifecycle "
                "write did not land, and the reconciler still covers it"
            ),
        )
        return 0


@router.delete("/sessions", response_model=SuccessResponse, dependencies=[Depends(require_peer_sessions)])
async def destroy_session(request: Request, session_id: Optional[str] = None, confirm_name: Optional[str] = None):
    """
    Destroy a session (kill its backend / tmux).

    ``session_id`` (query, optional) selects which session; omitted destroys
    the current one. Other live sessions are untouched. A Swarm leader's body
    needs ``confirm_name`` (query) equal to its display name (409 ``leader_protected``).

    Raises:
        HTTPException: 404 if the session doesn't exist, 409 for an unconfirmed leader, 500 on teardown error
    """
    session_manager = request.app.state.session_manager
    local_servers = request.app.state.local_servers

    try:
        logger.info("api_destroy_session_request", session_id=session_id)

        registry = request.app.state.services.registry
        backend = (
            registry.get_backend(session_id)
            if session_id
            else registry.current_backend()
        )
        active_name = (
            getattr(backend, "tmux_session", None) if backend else None
        )
        active_socket = (
            getattr(backend, "socket_name", None) if backend else None
        )
        active_host = backend_host_key(backend)
        if active_name and active_host == LOCAL_HOST_KEY:
            await swarm_leaders.require_confirm(tmux_name=active_name, confirm_name=confirm_name)
            await local_servers.clear_session(active_name)

        active_epoch = await _instance_epoch(backend) if active_name else None

        await session_manager.destroy_session(session_id=session_id)

        await _mark_closed_in_datastore(active_socket, active_name, active_epoch, active_host)

        save_triggers.schedule_for_instance(
            active_socket, active_name, active_epoch, save_triggers.EVENT_KILL, host_key=active_host)

        session_change_notice.publish(
            request.app.state,
            session_change_notice.build_structural_notice("destroyed"),
        )

        return SuccessResponse(message="Session destroyed successfully")

    except HTTPException:
        raise
    except ValueError as e:
        raise api_error(404, "session_not_found", e) from e
    except Exception as e:  # noqa: BLE001
        raise api_error(500, "session_destroy_failed", e) from e


@router.post(
    "/sessions/detach",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def detach_session(request: Request, session_id: Optional[str] = None):
    """Detach from a session WITHOUT killing tmux.

    Soft counterpart to ``DELETE /sessions`` - tears down the server-side
    backend refs (reader task, idle watcher, our pipe-pane) for THAT session
    while leaving the tmux session alive. ``session_id`` (query, optional)
    selects which session; omitted detaches the current one. Other live
    sessions are untouched.

    Returns 404 when the session isn't active. Other failures propagate as 500.
    """
    session_manager = request.app.state.session_manager

    logger.info("api_detach_session_request", session_id=session_id)

    detached = await session_manager.detach_current_session(session_id=session_id)
    if not detached:
        raise HTTPException(status_code=404, detail="No active session to detach")

    return SuccessResponse(message="Session detached")
