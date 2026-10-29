
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core.pack.migrate import apply, live_agents, ops, wake_after
from src.core.pack.migrate.live_agents import LiveAgent
from src.core.pack.migrate.plan import MigrateError, Plan, Request, SourceEnv, plan_project
from src.core.pack.move import interrupt as interrupt_mod, session_move, turn

logger = structlog.get_logger()
DEFAULT_WAIT_SECONDS = session_move.DEFAULT_WAIT_SECONDS


@dataclass
class LiveHooks:

    session: session_move.Hooks
    sleep_agent: Callable[[int], Awaitable[None]]
    wake_agent: Callable[[int], Awaitable[None]]


async def _gather(coros: List[Coroutine[Any, Any, Any]]) -> None:
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _refusal(exc: turn.TurnNotEnded, name: str) -> MigrateError:
    text = session_move.turn_ended_text(exc, name).replace("send again", "move the project again")
    return MigrateError("turn_not_ended", f"{text}. nothing was stopped and every agent is still here", 409, "wait")


async def _interrupt(env: SourceEnv, hooks: LiveHooks, op_id: str, agents: List[LiveAgent]) -> List[LiveAgent]:
    await apply._db(env, lambda c: ops.update(c, op_id, "source", step="interrupt", detail={"agents": len(agents)}))
    try:
        done = await interrupt_mod.interrupt_running(hooks.session.find, hooks.session.interrupt, [(a.session_uuid, a.name) for a in agents])
    except HTTPException as exc:
        raise MigrateError("interrupt_failed", f"an agent could not be interrupted: {session_move._plain(exc)}. nothing was stopped and every agent is still here", 409, "interrupt") from exc
    stopped = {u for u, _ in done}
    return [a for a in agents if a.session_uuid in stopped]


async def _wait_all(env: SourceEnv, hooks: LiveHooks, op_id: str, agents: List[LiveAgent], wait_seconds: float, settle: float, poll: float) -> None:
    told: Dict[str, str] = {}

    async def note(agent: LiveAgent, text: str) -> None:
        told[agent.session_uuid] = text
        await apply._db(env, lambda c: ops.update(c, op_id, "source", detail={"waiting_on": "; ".join(v for v in told.values() if v)}))

    async def one(agent: LiveAgent) -> None:
        try:
            await turn.wait_for_turn_end(lambda: hooks.session.find(agent.session_uuid), wait_seconds, name=agent.name, settle=settle, poll=poll,
                                         on_blocker=lambda text: note(agent, text), shells_ok=True)
        except turn.TurnNotEnded as exc:
            raise _refusal(exc, agent.name) from exc

    await _gather([one(a) for a in agents])


def _plain(exc: HTTPException) -> str:
    return session_move._plain(exc)


async def _measure_shells(hooks: LiveHooks, agents: List[LiveAgent]) -> Dict[str, Tuple[int, List[Tuple[int, str]]]]:
    held: Dict[str, Tuple[int, List[Tuple[int, str]]]] = {}
    for agent in agents:
        count = turn.shells_only(await hooks.session.find(agent.session_uuid))
        if count and hooks.session.background_members is not None:
            try:
                held[agent.session_uuid] = (count, await hooks.session.background_members(agent.session_uuid))
            except HTTPException as exc:
                raise MigrateError("shells_not_stopped", f"{agent.name}: {_plain(exc)}"[:200], 409, "wait") from exc
    return held


async def _stop_shells(env: SourceEnv, hooks: LiveHooks, op_id: str, agents: List[LiveAgent], held: Dict[str, Tuple[int, List[Tuple[int, str]]]]) -> None:
    if not any(members for _, members in held.values()):
        return
    await apply._db(env, lambda c: ops.update(c, op_id, "source", step="stop_shells", detail={"shells": sum(n for n, _ in held.values()), "waiting_on": ""}))
    for agent in agents:
        if agent.session_uuid in held and held[agent.session_uuid][1]:
            try:
                await hooks.session.stop_members(agent.session_uuid, held[agent.session_uuid][1])
            except HTTPException as exc:
                raise MigrateError("shells_not_stopped", f"{agent.name}: {_plain(exc)}"[:200], 409, "stop_shells") from exc


async def _sleep(env: SourceEnv, hooks: LiveHooks, op_id: str, agents: List[LiveAgent], slept: List[LiveAgent]) -> None:
    await apply._db(env, lambda c: ops.update(c, op_id, "source", step="sleep"))
    for agent in agents:
        slept.append(agent)
        try:
            await (hooks.sleep_agent(agent.agent_id) if agent.agent_id is not None else hooks.session.sleep(agent.session_uuid))
        except HTTPException as exc:
            raise MigrateError("sleep_refused", f"{agent.name}: {exc.detail.get('detail') if isinstance(exc.detail, dict) else exc.detail}"[:200], 409, "sleep") from exc


async def _rewake(hooks: LiveHooks, slept: List[LiveAgent]) -> None:
    for agent in slept:
        try:
            await (hooks.wake_agent(agent.agent_id) if agent.agent_id is not None else hooks.session.wake(agent.session_uuid))
        except HTTPException as exc:
            logger.warning("pack_migrate_rewake_failed", session_uuid=agent.session_uuid, status=exc.status_code)


async def _reread(env: SourceEnv, plans: List[Plan], request: Request) -> List[Plan]:
    fresh = [await plan_project(env, p.project, p.target_install_id, request, rung=p.rung, root_hint=p.target_root, target_caps=p.target_caps) for p in plans]
    for old, new in zip(plans, fresh):
        if new.blocking or new.target_root != old.target_root or new.case != old.case:
            raise MigrateError("plan_changed", f"{new.project['display_name']} changed while its agents were stopping: " + ("; ".join(new.blocking) or "the other computer's answer changed"), 409, "sleep")
    return fresh


async def migrate(env: SourceEnv, hooks: LiveHooks, request: Request, plans: List[Plan], *, kind: str, company_uid: Optional[str], op_id: str,
                  wait_seconds: float = DEFAULT_WAIT_SECONDS, settle: float = turn.SETTLE_SECONDS, poll: float = turn.POLL_SECONDS, stop_running: bool = False) -> Dict[str, Any]:
    request = apply.guarded(request)

    def read(conn: Any) -> List[LiveAgent]:
        return [a for p in plans for a in live_agents.read(conn, p.project["id"])[0]]

    agents = await apply._db(env, read)

    async def run(chosen: List[Plan], hold: bool = False) -> Dict[str, Any]:
        if kind == "project":
            return await apply.apply_project(env, chosen[0], request, op_id=op_id, hold=hold)
        return await apply.apply_company(env, chosen, request, company_uid=str(company_uid), op_id=op_id, hold=hold)

    if not agents:
        return await run(plans)
    first = plans[0]
    until = (datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = first.project["display_name"] if kind == "project" else (first.manifest["company"] or {}).get("name")
    await apply.open_op(env, op_id, kind=kind, subject_uid=first.project["uid"] if kind == "project" else str(company_uid), source_install_id=env.install_id,
                        target_install_id=first.target_install_id, fingerprint=first.fingerprint, step="wait",
                        detail={"name": name, "live": len(agents), "agents": len(agents), "wait_until": until, "stop_running": stop_running})
    slept: List[LiveAgent] = []
    interrupted: List[LiveAgent] = []
    applying = False
    try:
        if stop_running:
            interrupted = await _interrupt(env, hooks, op_id, agents)
            await apply._db(env, lambda c: ops.update(c, op_id, "source", step="wait", detail={"agents": len(agents)}))
        await _wait_all(env, hooks, op_id, agents, wait_seconds, settle, poll)
        held = await _measure_shells(hooks, agents)
        await _sleep(env, hooks, op_id, agents, slept)
        await _stop_shells(env, hooks, op_id, agents, held)
        fresh = await _reread(env, plans, request)
        applying = True
        answer = await run(fresh, hold=True)
    except asyncio.CancelledError:
        await _rewake(hooks, slept)
        await apply._db(env, lambda c: ops.update(c, op_id, "source", state="failed", error_code="cancelled"))
        logger.info("pack_migrate_live_cancelled", op_id=op_id, slept=len(slept))
        raise
    except MigrateError as exc:
        if exc.code != "machine_unreachable":
            await _rewake(hooks, slept)
        if not applying:
            await apply._db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=exc.step, error_code=exc.code, detail={"error": exc.detail}))
        raise
    except Exception:
        if not applying:
            await _rewake(hooks, slept)
            await apply._db(env, lambda c: ops.update(c, op_id, "source", state="failed", error_code="internal"))
        raise
    woke = await wake_after.wake_all(request, agents)
    if interrupted:
        failed_wake = {f["name"] for f in woke["wake_failed"]}
        going = [(a.session_uuid, a.name) for a in interrupted if a.name not in failed_wake]
        await apply._db(env, lambda c: ops.update(c, op_id, "source", step="continue", detail={"agents": len(going), **woke}))
        woke = {**woke, **await interrupt_mod.tell_continue(request, going)}
    await apply._db(env, lambda c: ops.update(c, op_id, "source", state="flipped", step="flip", detail=woke))
    logger.info("pack_migrate_woke_on_target", op_id=op_id, woken=woke["woken"], failed=len(woke["wake_failed"]))
    return answer
