
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set

import structlog
from fastapi import HTTPException

logger = structlog.get_logger()

READY_TIMEOUT_S = 90.0
READY_STEP_S = 1.5
BUSY_CODES = frozenset({"pane_dialog_open", "paste_not_settled", "agent_waking", "restore_offer_open"})
GONE_CODES = frozenset({"session_gone", "session_not_found", "pane_not_an_agent", "receiver_instance_changed"})
READY_STATUSES = ("idle", "finished_unread")


class BringUpFailed(Exception):
    """A session could not be brought to its prompt; the message is the sentence a caller shows."""


class RestoreOfferOpen(BringUpFailed):

    code = "restore_offer_open"


class SessionOps(Protocol):

    async def list(self) -> List[Any]: ...  # noqa: E704

    async def durable_keys(self, infos: Optional[List[Any]] = None) -> Dict[str, str]: ...  # noqa: E704

    async def asleep(self) -> List[Dict[str, Any]]: ...  # noqa: E704

    async def wake(self, session_uuid: str) -> Dict[str, Any]: ...  # noqa: E704

    async def start(self, project_id: int) -> str: ...  # noqa: E704


def refusal_code(exc: HTTPException) -> str:
    detail = exc.detail
    return str(detail.get("code") or "refused") if isinstance(detail, dict) else "refused"


def ops_for_app(app_state: Any) -> Any:
    from src.cplugs.host import capabilities, session_actions  # noqa: PLC0415

    request = session_actions.AppRequest(SimpleNamespace(state=app_state))
    return capabilities.Sessions(capabilities.local_infos_from_app(app_state), request, may_message=True)


async def wait_ready(ops: SessionOps, match: Callable[[Any, Dict[str, str]], bool], what: str,
                     timeout: Optional[float] = None, step: Optional[float] = None) -> str:
    timeout = READY_TIMEOUT_S if timeout is None else timeout
    step = READY_STEP_S if step is None else step
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        infos = await ops.list()
        keys = await ops.durable_keys(infos)
        for info in infos:
            if match(info, keys) and info.activity_status in READY_STATUSES:
                return info.session.id
        if loop.time() + step > deadline:
            raise BringUpFailed(f"{what} did not reach its prompt within {int(timeout)} seconds")
        await asyncio.sleep(step)


async def wake_by_uuid(ops: SessionOps, session_uuid: str) -> str:
    try:
        woken = await ops.wake(session_uuid)
    except HTTPException as exc:
        raise BringUpFailed(f"could not wake the session: {refusal_code(exc)}") from exc
    if woken["status"] != "started":
        raise BringUpFailed(f"could not wake the sleeping session: {woken.get('detail') or woken.get('code') or woken['status']}")
    logger.info("session_bring_up_woken", session_uuid=session_uuid)
    return await wait_ready(ops, lambda info, keys: keys.get(info.session.id) == session_uuid, "the woken session")


def offer_holds_projects() -> Set[int]:
    from src.config import settings
    from src.core.sessions import offer_reservation
    from src.core.db import db_path_for

    state_dir = Path(settings.get_state_dir())
    return offer_reservation.offered_project_ids(state_dir, db_path_for(state_dir))


async def start_in_project(ops: SessionOps, project_id: int) -> str:
    if project_id in offer_holds_projects():
        raise RestoreOfferOpen("an open reopen offer lists a session of this project; it is held until the offer is answered")
    try:
        created = await ops.start(project_id)
    except HTTPException as exc:
        raise BringUpFailed(f"could not start a session: {refusal_code(exc)}") from exc
    except LookupError as exc:
        raise BringUpFailed(str(exc)) from exc
    logger.info("session_bring_up_started", project=project_id, session_id=created)
    return await wait_ready(ops, lambda info, _keys: info.session.id == created, "the new session")


async def wake_newest(ops: SessionOps, project_id: int) -> Optional[str]:
    try:
        sleepers = [s for s in await ops.asleep() if s["project_id"] == project_id]
    except HTTPException as exc:
        raise BringUpFailed(f"could not read the sleeping sessions: {refusal_code(exc)}") from exc
    return await wake_by_uuid(ops, sleepers[0]["session_uuid"]) if sleepers else None


async def wake_newest_or_start(ops: SessionOps, project_id: int) -> str:
    woken = await wake_newest(ops, project_id)
    return woken if woken is not None else await start_in_project(ops, project_id)


async def find_live(ops: SessionOps, session_uuid: str) -> Optional[Any]:
    infos = await ops.list()
    keys = await ops.durable_keys(infos)
    return next((i for i in infos if keys.get(i.session.id) == session_uuid), None)


async def is_asleep(ops: SessionOps, session_uuid: str) -> bool:
    return any(s["session_uuid"] == session_uuid for s in await ops.asleep())
