
from __future__ import annotations

import asyncio
import time
from contextlib import closing
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

import structlog
from fastapi import HTTPException

from src.core.automations import models as m
from src.cplugs.host.session_actions import AppRequest
from src.cplugs.sdk import turn_events

logger = structlog.get_logger()

RUN_TIMEOUT_S = 7200.0
RUNS_KEPT_WITH_SESSIONS = 3
DONE_STATES = ("finished_unread", "idle")
WORKING_STATES = ("working", "working_subagent")

_marks: Dict[int, Dict[str, str]] = {}
_by_ses_id: Dict[str, "tuple[str, str]"] = {}
_seen_working: Set[str] = set()
_tasks: Set["asyncio.Task[None]"] = set()
_unsubscribe: Optional[Any] = None
launching: Set[str] = set()


def mark_for_row(session_row_id: Optional[int]) -> Optional[Dict[str, str]]:
    return _marks.get(session_row_id) if session_row_id is not None else None


def _refresh_marks(rows: List[Dict[str, Any]]) -> None:
    fresh = {r["session_row_id"]: {"automation_id": r["automation_id"], "run_id": r["run_id"], "name": r["automation_name"]}
             for r in rows if r["session_row_id"] is not None}
    _marks.clear()
    _marks.update(fresh)


def record_launch(store: Any, automation: Dict[str, Any], run_id: str, member_index: int, launched: Any) -> bool:
    if not launched.session_uuid:
        return False
    store.add_run_sessions(run_id, [{"session_uuid": launched.session_uuid, "session_row_id": launched.session_row_id,
                                     "member_index": member_index}])
    if launched.session_row_id is not None:
        _marks[launched.session_row_id] = {"automation_id": automation["automation_id"], "run_id": run_id, "name": automation["name"]}
    _by_ses_id[launched.id] = (launched.session_uuid, run_id)
    return True


def _request(app_state: Any) -> AppRequest:
    return AppRequest(SimpleNamespace(state=app_state))


def _stored_state(row_id: Optional[int], session_uuid: str) -> str:
    from src.config import settings  # noqa: PLC0415
    from src.core import session_sleep  # noqa: PLC0415
    from src.core.db import connect, db_path_for  # noqa: PLC0415

    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        found = conn.execute("SELECT * FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    if found is None or found["archived_at"]:
        return "gone"
    return "asleep" if session_sleep.is_asleep(dict(found)) else "live"


async def _sleep(app_state: Any, store: Any, row: Dict[str, Any]) -> bool:
    from src.api import session_sleep_routes  # noqa: PLC0415
    from src.core import session_sleep  # noqa: PLC0415

    try:
        result = await session_sleep_routes.sleep_by_uuid(
            app_state, row["session_uuid"], source=session_sleep.LIFECYCLE_SOURCE_SLEPT_BY_TIMER, fresh_ok=False)
    except HTTPException as exc:
        logger.info("automation_run_sleep_failed", run_id=row["run_id"], status=exc.status_code)
        return False
    if result.status != "asleep":
        logger.info("automation_run_sleep_refused", run_id=row["run_id"], code=result.code)
        return False
    await asyncio.to_thread(store.mark_run_session, row["run_id"], row["session_uuid"], slept=True)
    return True


async def on_turn_end(app_state: Any, store: Any, ses_id: str) -> None:
    known = _by_ses_id.get(ses_id)
    if known is None:
        return
    session_uuid, run_id = known
    rows = [r for r in await asyncio.to_thread(store.run_session_rows, run_id) if r["session_uuid"] == session_uuid]
    if not rows or rows[0]["slept_at"] or rows[0]["closed_at"]:
        return
    if await _sleep(app_state, store, {**rows[0], "run_id": run_id}):
        await _settle(store, time.time())


def subscribe(app_state: Any, store: Any) -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
    loop = asyncio.get_running_loop()

    def listener(ses_id: Optional[str]) -> None:
        if not ses_id or ses_id not in _by_ses_id:
            return

        def start() -> None:
            task = loop.create_task(on_turn_end(app_state, store, ses_id), name="automation-turn-end")
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)

        loop.call_soon_threadsafe(start)

    _unsubscribe = turn_events.subscribe(listener)


def unsubscribe() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None


async def _settle(store: Any, now: float) -> None:
    from src.core.automations.targets import blueprint  # noqa: PLC0415

    for run in await asyncio.to_thread(store.live_runs):
        rows = [] if run["run_id"] in launching else await asyncio.to_thread(store.run_session_rows, run["run_id"])
        if not rows:
            continue
        if all(r["slept_at"] or r["closed_at"] for r in rows):
            await asyncio.to_thread(store.update_run, run["run_id"], status=m.SUCCEEDED, ended_at=now)
        elif run["started_at"] and now - run["started_at"] > RUN_TIMEOUT_S:
            await asyncio.to_thread(store.update_run, run["run_id"], status=m.FAILED, reason="timeout", ended_at=now)
            await asyncio.to_thread(blueprint.tell_failed, store, run)


async def _retain(app_state: Any, store: Any, rows: List[Dict[str, Any]], states: Dict[str, str]) -> None:
    from src.api import session_sleep_routes  # noqa: PLC0415

    for row in rows:
        if row["newer"] < RUNS_KEPT_WITH_SESSIONS or row["closed_at"] or states.get(row["session_uuid"]) != "asleep":
            continue
        try:
            await session_sleep_routes.kill_asleep_session(_request(app_state), row["session_uuid"])
        except HTTPException as exc:
            if exc.status_code != 404:
                logger.info("automation_run_close_left", run_id=row["run_id"], status=exc.status_code)
                continue
        await asyncio.to_thread(store.mark_run_session, row["run_id"], row["session_uuid"], closed=True)


async def sweep(app_state: Any, store: Any, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    rows = await asyncio.to_thread(store.active_run_sessions)
    _refresh_marks(rows)
    if not rows:
        return
    states = {r["session_uuid"]: await asyncio.to_thread(_stored_state, r["session_row_id"], r["session_uuid"]) for r in rows}
    infos: Dict[int, Any] = {}
    if any(s == "live" for s in states.values()):
        infos = {i.session_row_id: i for i in await app_state.session_manager.list_session_infos() if i.session_row_id is not None}
    asking: Set[str] = set()
    for row in rows:
        if row["slept_at"] and states[row["session_uuid"]] == "asleep":
            continue
        state = states[row["session_uuid"]]
        if state == "gone":
            await asyncio.to_thread(store.mark_run_session, row["run_id"], row["session_uuid"], closed=True)
            continue
        if state == "asleep":
            await asyncio.to_thread(store.mark_run_session, row["run_id"], row["session_uuid"], slept=True)
            continue
        info = infos.get(row["session_row_id"])
        status = getattr(info, "activity_status", None)
        if status in WORKING_STATES:
            _seen_working.add(row["session_uuid"])
        elif status == "question":
            asking.add(row["run_id"])
        elif status in DONE_STATES and (row["session_uuid"] in _seen_working or row["run_status"] not in m.LIVE_STATUSES):
            if await _sleep(app_state, store, row):
                states[row["session_uuid"]] = "asleep"
    await _flip_waiting(store, asking)
    await _settle(store, now)
    await _retain(app_state, store, await asyncio.to_thread(store.active_run_sessions), states)


async def _flip_waiting(store: Any, asking: Set[str]) -> None:
    for run in await asyncio.to_thread(store.live_runs):
        if run["run_id"] in asking and run["status"] == m.RUNNING:
            await asyncio.to_thread(store.update_run, run["run_id"], status=m.WAITING)
        elif run["run_id"] not in asking and run["status"] == m.WAITING:
            if await asyncio.to_thread(store.run_session_rows, run["run_id"]):
                await asyncio.to_thread(store.update_run, run["run_id"], status=m.RUNNING)
