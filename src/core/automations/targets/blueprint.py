
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.automations import models as m
from src.core.automations import run_sessions
from src.core.automations import notify_policy
from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import automation as placement_store
from src.models.blueprints_launch import LaunchedSession, MemberOutcome
from src.plugins.host.session_actions import AppRequest

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
    if notify_policy.decide(automation, True):
        notify_policy.tell(notify_policy.FAILED_TYPE, automation, run["run_id"], store)


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
    placement = await _placement_of(automation["automation_id"])
    started: List[Dict[str, Any]] = []
    failure: Optional[str] = None
    run_sessions.launching.add(run_id)
    try:
        for index in wanted:
            member = saved.spec.sessions[index]
            if placement == placement_store.AUTO and not member.host_key:
                outcome = await _launch_by_auto(request, ctx, index, member, root)
            else:
                outcome = await steps.launch_member(request, index, member, root, {}, None, None, existing=None)
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



async def _placement_of(automation_id: str) -> str:
    try:
        return await asyncio.to_thread(placement_store.get, automation_id)
    except JobError as exc:
        logger.info("automation_placement_unread", automation_id=automation_id, code=exc.code)
        return placement_store.HERE


class _LocalDone(Exception):

    def __init__(self, outcome: Any) -> None:
        super().__init__("local")
        self.outcome = outcome


async def _launch_by_auto(request: Any, ctx: Any, index: int, member: Any, root: str) -> Any:
    from src.api import blueprints_launch as steps  # noqa: PLC0415
    from src.api.blueprints_peer_member import SHADOW_WAIT_SECONDS, _POLL, _shadow_row, check_supported  # noqa: PLC0415
    from src.core.pack.session_place import create as create_mod  # noqa: PLC0415
    from src.core.pack.session_place.plan import request_for  # noqa: PLC0415
    from src.core.pack.session_place.types import Starter  # noqa: PLC0415
    from src.core.session_name_claim import sanitize_tmux_name  # noqa: PLC0415
    from src.models import CreateSessionRequest  # noqa: PLC0415

    async def here() -> Any:
        return await steps.launch_member(request, index, member, root, {}, None, None, existing=None)

    try:
        check_supported(member)
    except steps.StepFailed:
        return await here()
    try:
        body = CreateSessionRequest(working_dir=member.folder.path, project_name=sanitize_tmux_name(member.label), label=member.label,
                                    agent_type=member.family, model=member.model, opening_prompt=member.opening_prompt)
    except ValueError:
        return await here()
    want = request_for(member.family, working_dir=member.folder.path)

    async def local(_body: Any) -> Any:
        raise _LocalDone(await here())

    try:
        placed = await create_mod.create_placed(ctx.app_state, want, Starter(kind="automation", model=member.model), body, local_create=local)
    except _LocalDone as done:
        return done.outcome
    except JobError as exc:
        logger.info("automation_placement_stays_here", index=index, code=exc.code)
        return await here()
    far = placed.session
    name, host_key = str(far["tmux_session"]), str(far["host_key"])
    row_id, shadow_uuid = None, None
    for _ in range(int(SHADOW_WAIT_SECONDS / _POLL)):
        row_id, shadow_uuid = await asyncio.to_thread(_shadow_row, host_key, name)
        if row_id is not None:
            break
        await asyncio.sleep(_POLL)
    session = LaunchedSession(id=far["id"], tmux_session=name, session_row_id=row_id, session_uuid=shadow_uuid)
    return MemberOutcome(index=index, label=member.label, state="launched", folder=steps.FolderView(mode="existing", path=member.folder.path),
                         session=session)
