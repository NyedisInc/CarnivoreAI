from __future__ import annotations

import uuid as uuid_lib
from contextlib import closing
from typing import Any, Callable, Optional, Tuple

import structlog
from fastapi.concurrency import run_in_threadpool

from src.config import settings
from src.core import restart_inflight, restart_live_gate, session_restart
from src.core.sessions.reuse_guard import ReuseRowTakenError
from src.core.account_switch import restart_account
from src.core.account_switch.launch_env import _config_path
from src.core.agent_families import get_family
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.hosts.registry import HostUnavailable
from src.core.hosts.remote_restart import RemoteRestartRefused, restart_stopped
from src.core.launch_profiles import restart_seam
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.session_name_claim import sanitize_tmux_name
from src.core.session_ops import row_probe
from src.core.sessions.errors import SessionError, SessionNotFound
from src.models import RestartSessionResponse

logger = structlog.get_logger()


class RestartError(SessionError):
    pass


class NoDatastore(RestartError, SessionNotFound):
    pass


class RestartSourceNotFound(RestartError, SessionNotFound):
    pass


class RestartDatastoreUnreadable(RestartError):
    pass


class AlreadyRunning(RestartError):
    pass


class ConversationMissing(RestartError):
    pass


class ConversationOffloaded(ConversationMissing):

    def __init__(self, body: dict) -> None:
        super().__init__(str(body.get("detail") or "this conversation was offloaded to the backup vault"))
        self.body = body


class RowTakenOver(RestartError):

    def __init__(self, message: str, held_tmux_name: str) -> None:
        super().__init__(message)
        self.held_tmux_name = held_tmux_name


class ReplacementCreateFailed(RestartError):

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.context = context


class RemoteRestartFailed(RestartError):

    def __init__(self, message: str, host: str) -> None:
        super().__init__(message)
        self.host = host


RESTART_ERRORS = (RestartError, LaunchProfileNotFound, restart_inflight.RestartInFlightError)


def _resolve(db_path: Any, session_uuid: str) -> Tuple[Any, str]:
    with closing(connect(db_path, create=False)) as conn:
        host_key = row_probe.stored_host_key(conn, session_uuid)
        remote = {} if host_key == "local" else {"check_transcript": False}
        return session_restart.resolve_restart_source(conn, session_uuid=session_uuid, **remote), host_key


async def _refuse_if_running(db_path: Any, session_uuid: str) -> None:
    running = await run_in_threadpool(restart_live_gate.bound_instance_running, db_path, session_uuid, row_probe.socket_name())
    if running:
        logger.warning("restart_refused_already_running", session_uuid=session_uuid)
        raise AlreadyRunning("this session is already running")


def _verify_reuse(db_path: Any, parent_id: int, child_tmux: Optional[str]) -> bool:
    with closing(connect(db_path, create=False)) as conn:
        row = conn.execute("SELECT tmux_name, lifecycle FROM sessions WHERE id = ? LIMIT 1", (parent_id,)).fetchone()
        return row is not None and row["tmux_name"] == child_tmux and row["lifecycle"] == "running"


async def _create_replacement(app_state: Any, session_uuid: str, source: Any, label: Optional[str], resumable: bool) -> Any:
    restart_seam.check_relaunch(settings, source.agent_type, source.launch_record)
    tmux_safe_name = (sanitize_tmux_name(label) or None) if label else None
    account_plan = await restart_account.resolve(_config_path(), session_uuid=session_uuid,
                                                 family=restart_account.family_of(source.agent_type))
    extra = session_restart.resume_arguments(source.claude_session_uuid, family=get_family(source.agent_type).name) if resumable else None
    try:
        return await app_state.session_manager.create_session(
            session_id=f"ses_{uuid_lib.uuid4().hex[:8]}", working_dir=source.working_dir, project_name=tmux_safe_name,
            agent_type=source.agent_type, model=source.model, agent_extra_args=extra, label=label,
            reuse_session_id=source.parent_id, claude_account=account_plan.account_id)
    except ReuseRowTakenError as exc:
        raise RowTakenOver(str(exc), exc.held_tmux_name) from exc
    except Exception as exc:  # noqa: BLE001
        raise ReplacementCreateFailed(str(exc), replaced_session_uuid=session_uuid, label=label) from exc


def _default_unconfirmed_note(exc: BaseException) -> str:
    logger.error("restart_record_unconfirmed", error_type=type(exc).__name__)
    return "the session was restarted, but whether it kept its original record could not be confirmed"


async def _reuse_detail(db_path: Any, source: Any, child: Any, resumable: bool,
                        unconfirmed_note: Callable[[BaseException], str]) -> Tuple[bool, Optional[str]]:
    detail = source.detail if not resumable else None
    try:
        reused = bool(await run_in_threadpool(_verify_reuse, db_path, source.parent_id, getattr(child, "tmux_session", None)))
    except DatastoreUnreadableError as exc:
        note = unconfirmed_note(exc)
        return False, f"{detail} {note}" if detail else note
    if reused:
        return True, detail
    note = ("the session was restarted, but it could not keep its original record and now has a separate one; "
            "it works, and it may appear as a second entry")
    return False, f"{detail} {note}" if detail else note


async def _restart_remote(session_manager: Any, session_uuid: str, host_key: str, source: Any) -> RestartSessionResponse:
    try:
        result = await restart_stopped(session_manager, session_uuid=session_uuid, host_key=host_key, source=source)
    except (HostUnavailable, RemoteRestartRefused) as exc:
        raise RemoteRestartFailed(str(exc), host_key) from exc
    except (ValueError, RuntimeError) as exc:
        raise ReplacementCreateFailed(str(exc), host=host_key, step="remote_create") from exc
    return RestartSessionResponse(**result)


async def _restart_unclaimed(app_state: Any, session_uuid: str,
                             unconfirmed_note: Callable[[BaseException], str] = _default_unconfirmed_note) -> RestartSessionResponse:
    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        raise NoDatastore("no datastore yet, so there is no session to restart")
    try:
        source, host_key = await run_in_threadpool(_resolve, db_path, session_uuid)
    except DatastoreUnreadableError as exc:
        raise RestartDatastoreUnreadable(str(exc)) from exc
    if source.outcome == session_restart.RESTART_UNRESOLVED:
        raise RestartSourceNotFound(source.detail or "session not found")
    if host_key != "local":
        return await _restart_remote(app_state.session_manager, session_uuid, host_key, source)
    await _refuse_if_running(db_path, session_uuid)
    if source.outcome == session_restart.RESTART_CONVERSATION_MISSING:
        logger.warning("restart_refused_conversation_missing", replaced_session_uuid=session_uuid, replaced_session_id=source.parent_id,
                       conversation_row_id=source.conversation_row_id, claude_session_uuid=source.claude_session_uuid, offloaded=source.offloaded)
        if source.offloaded:
            from src.core.backup_health import offload_guard

            info = offload_guard.lookup(source.claude_session_uuid)
            if info is not None:
                raise ConversationOffloaded(offload_guard.refusal_body(info))
        raise ConversationMissing(source.detail or "the conversation this session names is not on disk")
    resumable = source.outcome == session_restart.RESTART_RESUMABLE
    label = (source.title or "").strip() or None
    logger.info("api_restart_session_request", replaced_session_uuid=session_uuid, replaced_session_id=source.parent_id,
                conversation="resumed" if resumable else "none_recorded", conversation_row_id=source.conversation_row_id, label=label)
    child = await _create_replacement(app_state, session_uuid, source, label, resumable)
    reused, detail = await _reuse_detail(db_path, source, child, resumable, unconfirmed_note)
    return RestartSessionResponse(
        success=True, session=child.model_dump() if hasattr(child, "model_dump") else {},
        conversation="resumed" if resumable else "none_recorded", replaced_session_id=source.parent_id,
        row_reused=reused, title_carried=label, detail=detail)


async def restart_stopped_session(app_state: Any, session_uuid: str, *,
                                  unconfirmed_note: Callable[[BaseException], str] = _default_unconfirmed_note) -> RestartSessionResponse:
    with restart_inflight.claim(session_uuid):
        return await _restart_unclaimed(app_state, session_uuid, unconfirmed_note)
