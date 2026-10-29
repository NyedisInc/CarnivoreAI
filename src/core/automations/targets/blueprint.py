
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.automations import models as m
from src.core.app_alerts import constants as alert_const
from src.core.automations import run_sessions
from src.core.automations.targets.recipe import FAILED_TYPE, _tell, _wants
from src.cplugs.host.session_actions import AppRequest

logger = structlog.get_logger()
R_LAUNCH_FAILED, R_NEEDS_CONSENT = "launch_failed", "needs_consent"


def validate_target(target: Dict[str, Any]) -> Optional[str]:
    from src.api import blueprints_routes  # noqa: PLC0415
    from src.core import blueprints_store  # noqa: PLC0415

    try:
        saved = blueprints_routes.run(blueprints_store.get_blueprint, target["blueprint_uuid"])
    except blueprints_store.BlueprintError:
        return "blueprint_missing"
    members = target.get("members")
    if members is not None and any(i >= len(saved.spec.sessions) for i in members):
        return "member_missing"
    return None


def tell_failed(store: Any, run: Dict[str, Any]) -> None:
    automation = store.get(run["automation_id"])
    delivery = {**automation["delivery"], "notify_on": automation["delivery"].get("notify_on") or "failure"}
    if _wants({**automation, "delivery": delivery}, True):
        _tell(FAILED_TYPE, automation, run["run_id"], alert_const.SEV_WARN, store)


async def run(ctx: Any, automation: Dict[str, Any], run_row: Dict[str, Any]) -> m.RunOutcome:
    from src.api import blueprints_launch as steps  # noqa: PLC0415
    from src.api import blueprints_routes  # noqa: PLC0415
    from src.core import blueprints_store  # noqa: PLC0415

    target, run_id = automation["target"], run_row["run_id"]
    request = AppRequest(SimpleNamespace(state=ctx.app_state))
    try:
        saved = await blueprints_routes.call(blueprints_store.get_blueprint, target["blueprint_uuid"])
    except HTTPException:
        return await _failed(ctx, run_row, m.R_TARGET_MISSING)
    total = len(saved.spec.sessions)
    wanted = list(range(total)) if target.get("members") is None else target["members"]
    if any(i >= total for i in wanted):
        return await _failed(ctx, run_row, m.R_TARGET_MISSING)
    root = steps.worktree_root()
    started: List[Dict[str, Any]] = []
    failure: Optional[str] = None
    run_sessions.launching.add(run_id)
    try:
        for index in wanted:
            outcome = await steps.launch_member(request, index, saved.spec.sessions[index], root, {}, None, None, existing=None)
            if outcome.state != "launched" or outcome.session is None:
                code = outcome.problem.code if outcome.problem else ""
                failure = R_NEEDS_CONSENT if code == "consent_required" else R_LAUNCH_FAILED
                logger.info("automation_blueprint_member_failed", run_id=run_id, index=index, code=code)
                break
            tracked = await asyncio.to_thread(run_sessions.record_launch, ctx.store, automation, run_id, index, outcome.session)
            if tracked:
                started.append({"session_uuid": outcome.session.session_uuid, "session_row_id": outcome.session.session_row_id,
                                "member_index": index})
    finally:
        run_sessions.launching.discard(run_id)
    if failure:
        await asyncio.to_thread(tell_failed, ctx.store, run_row)
        return m.RunOutcome(status=m.FAILED, reason=failure, sessions=started or None)
    if not started:
        return m.RunOutcome(status=m.SUCCEEDED)
    return m.RunOutcome(status=m.RUNNING, sessions=started)


async def _failed(ctx: Any, run_row: Dict[str, Any], reason: str) -> m.RunOutcome:
    await asyncio.to_thread(tell_failed, ctx.store, run_row)
    return m.RunOutcome(status=m.FAILED, reason=reason)

