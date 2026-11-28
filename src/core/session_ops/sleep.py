from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import structlog
from fastapi.concurrency import run_in_threadpool

from src.core import restart_inflight, session_change_notice, session_sleep, unread_follow_up
from src.core.db import connect
from src.core.pipeline import triggers as save_triggers
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.session_ops import close_intent, row_probe
from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TMUX_UNKNOWN
from src.core.sessions.errors import SessionError

logger = structlog.get_logger()


class SleepFailed(SessionError):

    def __init__(self, message: str, tmux_name: Optional[str] = None) -> None:
        super().__init__(message)
        self.tmux_name = tmux_name


class SleepStillPresent(SessionError):
    pass


SLEEP_ERRORS = (row_probe.RowError, SleepFailed, SleepStillPresent, restart_inflight.RestartInFlightError)


@dataclass(frozen=True)
class SleepOutcome:

    status: str
    session_uuid: str
    session_name: Optional[str] = None
    code: Optional[str] = None
    detail: str = ""


def _refused(row: dict, refusal: session_sleep.SleepRefusal) -> SleepOutcome:
    logger.info("session_sleep_refused", session_uuid=row.get("session_uuid"), tmux_name=row.get("tmux_name"), code=refusal.code)
    return SleepOutcome("refused", str(row.get("session_uuid")), row.get("tmux_name"), refusal.code, refusal.detail)


def _record_sleep(row: dict, source: str) -> int:
    with closing(connect(row_probe.db_path(), create=False)) as conn:
        moved = session_sleep.mark_asleep(conn, row_id=int(row["id"]), tmux_name=str(row["tmux_name"]),
                                          tmux_created_epoch=int(row["tmux_created_epoch"]), source=source)
        conn.commit()
        return moved


async def _close_and_confirm(app_state: Any, name: str, socket: str, session_id: Optional[str]) -> None:
    await app_state.local_servers.clear_session(name)
    try:
        await session_sleep.close_for_sleep(app_state.session_manager, name=name, socket=socket,
                                          session_id=session_id)
    except RuntimeError as exc:
        logger.error("session_sleep_close_failed", tmux_name=name, error=str(exc))
        raise SleepFailed(f"failed to close {name!r} for sleep: {exc}", tmux_name=name) from exc
    after = await run_in_threadpool(row_probe.measure_presence, name, socket)
    if after.outcome != TMUX_GONE:
        logger.error("session_sleep_still_present", tmux_name=name, presence=after.outcome)
        raise SleepStillPresent(f"{name!r} was asked to close but the socket still reads {after.outcome}, so it was not marked asleep")


async def _stop_under_claim(app_state: Any, session_uuid: str, source: str, fresh_ok: bool) -> Tuple[Optional[SleepOutcome], dict, str, str, int]:
    row = row_probe.resolve_row(await run_in_threadpool(row_probe.read_row, session_uuid), session_uuid)
    refusal = session_sleep.sleep_refusal(row, fresh_ok=fresh_ok)
    if refusal is not None:
        return _refused(row, refusal), row, "", "", 0
    name = row_probe.safe_name(str(row.get("tmux_name") or ""))
    socket = str(row.get("tmux_socket") or row_probe.socket_name())
    presence = await run_in_threadpool(row_probe.measure_row_presence, row, name, socket, require_known_epoch=True)
    if presence.outcome == TMUX_UNKNOWN:
        unknown = session_sleep.SleepRefusal(
            session_sleep.REFUSED_PRESENCE_UNKNOWN, f"cannot sleep: {presence.detail.rstrip('. ')}. nothing was stopped")
        return _refused(row, unknown), row, name, presence.outcome, 0
    unread_follow_up.carry_into_sleep(app_state.session_manager, row)
    if presence.outcome == TMUX_PRESENT:
        await _close_and_confirm(app_state, name, socket, presence.session_id)
    moved = await run_in_threadpool(_record_sleep, row, source)
    return None, row, name, "gone_other_instance" if presence.other_instance else presence.outcome, moved


async def sleep_session(app_state: Any, session_uuid: str, *, source: str = session_sleep.LIFECYCLE_SOURCE_SLEPT,
                        fresh_ok: bool = False) -> SleepOutcome:
    with restart_inflight.claim(session_uuid):
        refusal, row, name, presence, moved = await _stop_under_claim(app_state, session_uuid, source, fresh_ok)
    if refusal is not None:
        return refusal
    session_change_notice.publish(app_state, session_change_notice.build_structural_notice("slept"))
    if not moved:
        if presence == TMUX_PRESENT:
            close_intent.keep_stopped(LOCAL_HOST_KEY, str(row.get("tmux_socket") or row_probe.socket_name()), name,
                                      row.get("tmux_created_epoch"))
        return _refused(row, session_sleep.SleepRefusal(
            session_sleep.REFUSED_ROW_MOVED,
            "the session was closed, but its record changed while it was being put to sleep, so it was not marked asleep"))
    save_triggers.schedule_for_uuid(session_uuid, save_triggers.EVENT_SLEEP)
    logger.info("session_slept", session_uuid=session_uuid, tmux_name=name, presence=presence)
    return SleepOutcome("asleep", session_uuid, name, detail="asleep. wake it from the session menu to resume the same conversation")


async def auto_sleep_session(app_state: Any, session_uuid: str) -> SleepOutcome:
    return await sleep_session(app_state, session_uuid, source=session_sleep.LIFECYCLE_SOURCE_SLEPT_BY_TIMER)
