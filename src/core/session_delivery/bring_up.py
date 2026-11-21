
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Set

import structlog
from fastapi import HTTPException
from src.core.session_delivery import cold_start, wake_choice
from src.core.session_startup_gate import GATE_READY
from src.models.activity_status import RESTING

logger = structlog.get_logger()

READY_TIMEOUT_S = 90.0
READY_STEP_S = 1.5
BUSY_CODES = frozenset({"pane_dialog_open", "paste_not_settled", "agent_waking", "restore_offer_open"})
GONE_CODES = frozenset({"session_gone", "session_not_found", "pane_not_an_agent", "receiver_instance_changed"})


class BringUpFailed(Exception):
    pass


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
    from src.plugins.host import capabilities, session_actions  # noqa: PLC0415

    request = session_actions.AppRequest(SimpleNamespace(state=app_state))
    return capabilities.Sessions(capabilities.local_infos_from_app(app_state), request, may_message=True)


def input_ready(info: Any) -> bool:
    return info.activity_status in RESTING and info.startup_gate == GATE_READY


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
            if match(info, keys) and input_ready(info):
                cold_start.mark_brought_up(info.session.id)
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


LeadWaker = Callable[[str], Awaitable[Optional[str]]]

_BRING_UP_LOCKS: Dict[int, asyncio.Lock] = {}


def project_lock(project_id: int) -> asyncio.Lock:
    return _BRING_UP_LOCKS.setdefault(project_id, asyncio.Lock())


def default_lead_waker(ops: SessionOps) -> LeadWaker:
    async def wake(lead_key: str) -> Optional[str]:
        live = await find_live(ops, lead_key)
        if live is not None and wake_choice.can_take(live):
            return live.session.id
        try:
            asleep = await is_asleep(ops, lead_key)
        except HTTPException as exc:
            raise BringUpFailed(f"could not read the sleeping sessions: {refusal_code(exc)}") from exc
        return await wake_by_uuid(ops, lead_key) if asleep else None

    return wake


async def _lead_or_none(own: List[Any], project_id: int, lead_key: str, wake_lead: LeadWaker) -> Optional[str]:
    try:
        return await wake_lead(lead_key)
    except BringUpFailed as exc:
        if not own:
            raise
        logger.info("session_bring_up_lead_wake_failed", project=project_id, error=str(exc)[:200])
        return None


async def _bring_up_unlocked(ops: SessionOps, project_id: int, lead_key: str, wake_lead: Optional[LeadWaker]) -> Optional[str]:
    own = wake_choice.running_agents(await ops.list(), project_id)
    keys = await ops.durable_keys(own) if own and lead_key else {}
    ready = wake_choice.running_lead(own, keys, lead_key)
    if ready is None and lead_key:
        ready = await _lead_or_none(own, project_id, lead_key, wake_lead or default_lead_waker(ops))
    if ready is None:
        ready = wake_choice.most_recent(own)
    return ready if ready is not None else await _wake_sleeper(ops, project_id)


async def _wake_sleeper(ops: SessionOps, project_id: int) -> Optional[str]:
    try:
        sleepers = await ops.asleep()
    except HTTPException as exc:
        raise BringUpFailed(f"could not read the sleeping sessions: {refusal_code(exc)}") from exc
    chosen = wake_choice.pick_sleeper(sleepers, project_id, "")
    return await wake_by_uuid(ops, chosen) if chosen else None


async def wake_newest(ops: SessionOps, project_id: int, lead_key: str = "", wake_lead: Optional[LeadWaker] = None) -> Optional[str]:
    async with project_lock(project_id):
        return await _bring_up_unlocked(ops, project_id, lead_key, wake_lead)


async def running_session(ops: SessionOps, project_id: int, lead_key: str = "") -> Optional[str]:
    own = wake_choice.running_agents(await ops.list(), project_id)
    if not own:
        return None
    return wake_choice.running_lead(own, await ops.durable_keys(own), lead_key) or wake_choice.most_recent(own)


async def wake_newest_or_start(ops: SessionOps, project_id: int, lead_key: str = "", wake_lead: Optional[LeadWaker] = None) -> str:
    async with project_lock(project_id):
        ready = await _bring_up_unlocked(ops, project_id, lead_key, wake_lead)
        return ready if ready is not None else await start_in_project(ops, project_id)


async def find_live(ops: SessionOps, session_uuid: str) -> Optional[Any]:
    infos = await ops.list()
    keys = await ops.durable_keys(infos)
    return next((i for i in infos if keys.get(i.session.id) == session_uuid), None)


async def is_asleep(ops: SessionOps, session_uuid: str) -> bool:
    return any(s["session_uuid"] == session_uuid for s in await ops.asleep())
