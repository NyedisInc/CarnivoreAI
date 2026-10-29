
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

import structlog
from fastapi import HTTPException

from src.core.automations import models as m
from src.core.automations import scheduler_log
from src.core.automations.targets.recipe import _tell, _wants
from src.core.app_alerts import constants as alert_const
from src.core.session_delivery import bring_up

logger = structlog.get_logger()

QUEUE_TIMEOUT_S = 2 * 3600.0
QUEUE_STEP_S = 5.0
R_ASLEEP, R_MISSING, R_DEAD, R_BLOCKED, R_QUEUE_TIMEOUT, R_BRING_UP = (
    "session_asleep", "session_missing", "session_dead", "session_blocked", "target_busy", "bring_up_failed")


def validate_target(target: Dict[str, Any]) -> Optional[str]:
    from src.core.automations import contract  # noqa: PLC0415

    return contract.project_problem(target.get("project_id")) if target.get("if_gone") == "start" else None


async def login_hint(app_state: Any, target: Dict[str, Any]) -> Optional[str]:
    from src.api import session_account_listing  # noqa: PLC0415

    info = await bring_up.find_live(bring_up.ops_for_app(app_state), target["session_uuid"])
    return session_account_listing.cached_account(info) if info is not None else None


async def _locate(ops: Any, target: Dict[str, Any]) -> tuple:
    uuid = target["session_uuid"]
    live = await bring_up.find_live(ops, uuid)
    if live is not None:
        if live.activity_status == "dead":
            return None, "dead", m.RunOutcome(status=m.FAILED, reason=R_DEAD)
        return live.session.id, "live", None
    if await bring_up.is_asleep(ops, uuid):
        if target["if_asleep"] == "skip":
            return None, "asleep", m.RunOutcome(status=m.SKIPPED, reason=R_ASLEEP)
        return await bring_up.wake_by_uuid(ops, uuid), "woken", None
    if target["if_gone"] == "fail":
        return None, "gone", m.RunOutcome(status=m.FAILED, reason=R_MISSING)
    return await bring_up.start_in_project(ops, int(target["project_id"])), "started", None


async def deliver_queued(ops: Any, request: Any, session_id: str, text: str, timeout: float,
                         on_queued: Callable[[], None] = lambda: None) -> Dict[str, Any]:
    from src.api.one_shot_routes import paste_through_gates  # noqa: PLC0415
    from src.cplugs.sdk import turn_events  # noqa: PLC0415

    loop = asyncio.get_running_loop()
    began, deadline, attempts = loop.time(), loop.time() + timeout, 0
    ended = asyncio.Event()

    def listener(ses_id: Optional[str]) -> None:
        if ses_id in (None, session_id):
            loop.call_soon_threadsafe(ended.set)

    stop = turn_events.subscribe(listener)
    try:
        while True:
            attempts += 1
            ended.clear()
            try:
                await paste_through_gates(request, session_id, text, idle_only=True)
                return {"queued_s": round(loop.time() - began, 1), "attempts": attempts}
            except HTTPException as exc:
                if bring_up.refusal_code(exc) not in bring_up.BUSY_CODES:
                    raise
                if attempts == 1:
                    on_queued()
            left = deadline - loop.time()
            if left <= 0:
                raise asyncio.TimeoutError
            try:
                await asyncio.wait_for(ended.wait(), min(QUEUE_STEP_S, left))
            except asyncio.TimeoutError:
                pass
    finally:
        stop()


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    from src.cplugs.host.session_actions import AppRequest  # noqa: PLC0415

    target = automation["target"]
    ops = bring_up.ops_for_app(ctx.app_state)
    request = AppRequest(SimpleNamespace(state=ctx.app_state))
    try:
        session_id, how, stop = await _locate(ops, target)
    except bring_up.BringUpFailed as exc:
        return _finish(ctx.store, automation, run_row, m.RunOutcome(status=m.FAILED, reason=R_BRING_UP, error=str(exc)))
    if stop is not None:
        return _finish(ctx.store, automation, run_row, stop)
    record = [{"session_uuid": target["session_uuid"], "session_id": session_id, "how": how}]
    timeout = float(automation.get("max_runtime_s") or QUEUE_TIMEOUT_S)
    try:
        ids = {"automation_id": automation["automation_id"], "run_id": run_row["run_id"], "session_id": session_id}
        sent = await deliver_queued(ops, request, session_id, target["text"], timeout,
                                    on_queued=lambda: scheduler_log.write("queued", **ids, how=how))
    except asyncio.TimeoutError:
        logger.warning("automation_session_message_target_busy", run_id=run_row["run_id"], waited_s=timeout)
        return _finish(ctx.store, automation, run_row, m.RunOutcome(status=m.FAILED, reason=R_QUEUE_TIMEOUT, sessions=record))
    except HTTPException as exc:
        code = bring_up.refusal_code(exc)
        reason = R_MISSING if code in bring_up.GONE_CODES else R_BLOCKED
        return _finish(ctx.store, automation, run_row, m.RunOutcome(status=m.FAILED, reason=reason, sessions=record, error=code))
    logger.info("automation_session_message_delivered", run_id=run_row["run_id"], session_id=session_id, how=how,
                queued_s=sent["queued_s"])
    scheduler_log.write("delivered", **ids, how=how, queued_s=sent["queued_s"])
    return _finish(ctx.store, automation, run_row, m.RunOutcome(status=m.SUCCEEDED, sessions=record, report={"delivery": {**sent, "how": how}}))


def _finish(store: Any, automation: Dict[str, Any], run_row: Dict[str, Any], outcome: m.RunOutcome) -> m.RunOutcome:
    failed = outcome.status == m.FAILED
    delivery = automation["delivery"]
    if failed and delivery.get("notify", True) and (delivery.get("notify_on") or "failure") in ("failure", "always"):
        _tell("automation_failed", automation, run_row["run_id"], alert_const.SEV_WARN, store)
    elif not failed and delivery.get("notify_on") == "always" and _wants(automation, False):
        _tell("automation_report", automation, run_row["run_id"], alert_const.SEV_INFO, store)
    return outcome
