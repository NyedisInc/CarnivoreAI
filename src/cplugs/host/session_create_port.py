
from __future__ import annotations

import math
import secrets
import time
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.mcp import pending, write_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.cplugs.host import capabilities, session_actions, session_create_launch as launch_mod
from src.cplugs.runtime import guards
from src.models.blueprints import check_opening_prompt

logger = structlog.get_logger()

ACTION = "plugin_session_create"
CALLER_PREFIX = "cplug:"
MAX_PENDING_PER_PLUGIN = pending.MAX_PENDING_PER_CALLER
WAIT_SECONDS = 120.0
SETTLE_SECONDS = 5.0
DENIAL_COOLDOWN_SECONDS = 60.0
WITHDRAWN = "the plugin stopped"

CARD_REASONS: Dict[str, str] = {
    "not_standing": "the plugin is no longer running with this permission, so nothing was started",
    "launch_changed": "the project's folder or launch changed since you were asked, so nothing was started",
    "cap_reached": "too many sessions started by plugins are already live, so nothing was started",
    "create_failed": "the session could not be started (the server log has the detail)",
}

Standing = Callable[[str], str]
Starter = Callable[..., Awaitable[str]]


class SessionCreatePort:

    def __init__(self, app: Any, *, standing: Standing, store: Optional[pending.PendingActions] = None, wait_seconds: float = WAIT_SECONDS,
                 start: Starter = session_actions.start, live_ids: Optional[Callable[[], Awaitable[set]]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._app, self._standing, self._wait, self._start, self._clock = app, standing, wait_seconds, start, clock
        self._store = store if store is not None else pending.get_store()
        self._live_ids = live_ids or self._app_live_ids
        self._denied_until: Dict[str, float] = {}

    async def _app_live_ids(self) -> set:
        from src.core.mcp.protocol import BatchView  # noqa: PLC0415

        return await BatchView(self._app.state.session_manager, self._app).live_ids_now()

    async def create(self, plugin_id: str, project: int, prompt: str, family: Optional[str]) -> Dict[str, Any]:
        self._refuse_in_cooldown(plugin_id)
        try:
            check_opening_prompt(prompt)
        except ValueError as exc:
            raise guards.Refused("invalid_params", str(exc), {"reason": "bad_prompt"}) from exc
        launch = self._launch(project, family)
        created: List[str] = []
        failed: List[str] = []
        item = self._park(plugin_id, launch, prompt, family, self._runner(plugin_id, project, family, prompt, launch, created, failed))
        try:
            status = await pending.wait_for(item, self._wait)
            if status == pending.PENDING:
                status = self._timed_out(item)
            elif not pending.finished(item):
                status = await pending.wait_for(item, SETTLE_SECONDS)
        finally:
            if item.status == pending.PENDING:
                self._withdraw(item, WITHDRAWN)
        return self._outcome(plugin_id, item, status, created, failed)

    def _refuse_in_cooldown(self, plugin_id: str) -> None:
        left = self._denied_until.get(plugin_id, 0.0) - self._clock()
        if left > 0:
            raise guards.Refused("rate_limited", "the owner denied a request from this plugin a moment ago",
                                 {"reason": "denied_recently", "retry_after_s": math.ceil(left)})

    @staticmethod
    def _launch(project: int, family: Optional[str]) -> launch_mod.Launch:
        found = capabilities.Projects().get(project)
        if found is None or not found.get("path"):
            raise guards.Refused("not_found", f"no project {project} with a folder", {"reason": "no_project"})
        try:
            return launch_mod.resolve(found, family)
        except launch_mod.LaunchUnresolvable as exc:
            raise guards.Refused("not_found", "the project's launch profile cannot be used", {"reason": "no_launch_profile"}) from exc

    def _runner(self, plugin_id: str, project: int, family: Optional[str], prompt: str, asked: launch_mod.Launch, created: List[str],
                failed: List[str]) -> Callable[[bool], Awaitable[Dict[str, Any]]]:
        caller = AgentCaller(session_id=f"{CALLER_PREFIX}{plugin_id}", tmux_name=f"{CALLER_PREFIX}{plugin_id}",
                             current_session_id=f"{CALLER_PREFIX}{plugin_id}")

        def refuse(code: str, detail: str = "") -> pending.ActionRefused:
            failed.append(code)
            logger.warning("cplug_session_create_refused_at_approve", cplug=plugin_id, code=code, detail=detail[:300])
            return pending.ActionRefused(CARD_REASONS[code])

        async def create_one() -> Any:
            ref = await self._start(session_actions.AppRequest(self._app), project, opening_prompt=prompt or None, agent_type=asked.agent_type)
            return SimpleNamespace(id=ref)

        async def run(_approved: bool) -> Dict[str, Any]:
            standing = self._standing(plugin_id)
            if standing:
                raise refuse("not_standing", standing)
            try:
                now = launch_mod.resolve(capabilities.Projects().get(project) or {}, family)
            except (LookupError, KeyError, TypeError) as exc:
                raise refuse("launch_changed", type(exc).__name__) from exc
            if launch_mod.changed(asked, now):
                raise refuse("launch_changed", f"{asked.working_dir} -> {now.working_dir}")
            try:
                session = await write_tools.counted_create(self._live_ids, caller, create_one)
            except ToolError as exc:
                raise refuse("cap_reached", str(exc)) from exc
            except (LookupError, ValueError, HTTPException) as exc:
                raise refuse("create_failed", f"{type(exc).__name__}: {getattr(exc, 'detail', None) or exc}") from exc
            created.append(session.id)
            logger.info("cplug_session_create_approved", cplug=plugin_id, project=project, session_id=session.id)
            return _ok({"id": session.id})

        return run

    def _park(self, plugin_id: str, launch: launch_mod.Launch, prompt: str, family: Optional[str],
              run: Callable[[bool], Awaitable[Dict[str, Any]]]) -> pending.PendingAction:
        shown = {"plugin": plugin_id, **launch.shown(), "prompt": prompt, "asked_family": family or ""}
        caller = f"{CALLER_PREFIX}{plugin_id}"
        try:
            return self._store.create(
                caller_session_id=caller, caller_tmux=caller, target_session_id="", target_tmux="", action=ACTION,
                args_summary=f"plugin {plugin_id} asks to start a session in project {launch.project}", execute=lambda: run(True), args=shown,
                dedupe_key=secrets.token_hex(8),
                beast_eligible=False,
            )
        except pending.PayloadTooLargeError as exc:
            raise guards.Refused("too_large", str(exc), {"reason": "card_too_large"}) from exc
        except pending.PendingLimitError as exc:
            raise guards.Refused("rate_limited", str(exc), {"reason": "too_many_waiting", "limit": f"{MAX_PENDING_PER_PLUGIN} waiting"}) from exc

    def _withdraw(self, item: pending.PendingAction, why: str) -> bool:
        return self._store.withdraw(item.id, why)

    def _timed_out(self, item: pending.PendingAction) -> str:
        return "timeout" if self._withdraw(item, "the plugin stopped waiting for your answer") else item.status

    def _outcome(self, plugin_id: str, item: pending.PendingAction, status: str, created: List[str], failed: List[str]) -> Dict[str, Any]:
        if status == pending.APPROVED and created:
            return {"ref": created[0]}
        logger.info("cplug_session_create_refused", cplug=plugin_id, status=status, code=failed[0] if failed else "")
        if status == "timeout":
            raise guards.Refused("timeout", "the owner did not answer in time; nothing was created", {"reason": "owner_timeout"})
        if status == pending.REFUSED:
            raise guards.Refused("permission_denied", "refused when the owner approved", {"reason": failed[0] if failed else "refused_at_approve"})
        if status == pending.APPROVED:
            raise guards.Refused("internal_error", "the session could not be started", {"reason": "create_failed"})
        if item.reason != WITHDRAWN:
            self._denied_until[plugin_id] = self._clock() + DENIAL_COOLDOWN_SECONDS
        raise guards.Refused("permission_denied", "the owner denied this request", {"reason": "owner_denied"})

    def withdraw_for(self, plugin_id: str) -> int:
        caller = f"{CALLER_PREFIX}{plugin_id}"
        mine = [self._store.get(row["id"]) for row in self._store.list() if row["caller_tmux"] == caller]
        return sum(1 for item in mine if item is not None and self._withdraw(item, WITHDRAWN))


def standing_of(supervisor: Any, state_dir: Any, ability: str = "sessions.create") -> Standing:
    from src.cplugs.host import sideload  # noqa: PLC0415
    from src.cplugs.runtime.create_params import SIDELOAD_TIER  # noqa: PLC0415

    def standing(plugin_id: str) -> str:
        proc = supervisor.process(plugin_id)
        if proc is None or proc.ended is not None:
            return "not_running"
        ctx = proc.spec.ctx
        if ctx.tier != SIDELOAD_TIER:
            return "not_a_sideload"
        if ability not in ctx.granted:
            return "grant_revoked"
        if not sideload.is_on(state_dir):
            return "sideload_off"
        return ""

    return standing
