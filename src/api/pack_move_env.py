
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import HTTPException

from src.api import pack_migrate_env, parked_work_listing, projects_service, subagent_listing
from src.api.session_interrupt_routes import send_escape
from src.config import settings
from src.core.background_work import batch as bw_batch
from src.core.background_work import guard as bw_guard
from src.core.background_work import terminate as bw_terminate
from src.core.background_work import tree as bw_tree
from src.core.background_work.listing import list_processes
from src.core.background_work.terminate import LivenessUnmeasured
from src.core import session_change_notice, session_store
from src.core.account_switch.launch_env import _config_path
from src.core.launch_profiles.create_seam import check_explicit_pick
from src.core.pack.migrate.live import LiveHooks
from src.core.pack.move import account
from src.core.pack.move.receive import MoveTarget
from src.core.pack.move.session_move import Hooks
from src.core.pack.relay import target_side
from src.core.session_delivery import bring_up


logger = structlog.get_logger()


def move_target() -> MoveTarget:
    return MoveTarget(env=pack_migrate_env.target_env(), launch_for=lambda key, sender: account.launch_for(key, sender, _config_path()),
                      profile_check=lambda agent_type: check_explicit_pick(settings, agent_type))


def _refusal(status: str, answer: Any) -> HTTPException:
    return HTTPException(409, {"code": getattr(answer, "code", None) or status, "detail": getattr(answer, "detail", None) or status})


def source_hooks(app_state: Any) -> Hooks:
    from src.api import session_sleep_routes

    ops = bring_up.ops_for_app(app_state)

    async def sleep(uuid: str) -> None:
        answer = await session_sleep_routes.sleep_by_uuid(app_state, uuid)
        if answer.status != "asleep":
            raise _refusal(answer.status, answer)

    async def wake(uuid: str) -> None:
        answer = await session_sleep_routes.wake_by_uuid(app_state, uuid)
        if answer.status != "started":
            raise _refusal(answer.status, answer)

    async def hide(uuid: str) -> None:
        def archive() -> None:
            with closing(projects_service.open_db_or_503(settings)) as conn:
                session_store.archive_session(conn, uuid)
        await asyncio.to_thread(archive)
        session_change_notice.publish(app_state, session_change_notice.build_structural_notice("destroyed"))

    async def background_members(uuid: str) -> list[tuple[int, str]]:
        info = await bring_up.find_live(ops, uuid)
        tmux_name = getattr(info, "tmux_session", None)
        if not tmux_name:
            raise HTTPException(409, {"code": "shells_not_stopped", "detail": "the agent's pane could not be found, so its background shells were left alone"})
        socket = app_state.session_manager.tmux_socket_name()

        def run() -> tuple[list, tuple]:
            tree = bw_tree.measure(tmux_name, socket)
            return bw_batch.plan(tree, [(p.pid, p.start) for p in list_processes(tree)], self_pids=bw_guard.server_lineage())

        try:
            verdicts, members = await asyncio.to_thread(run)
        except (bw_tree.TreeError, LivenessUnmeasured) as exc:
            raise HTTPException(409, {"code": "shells_not_stopped", "detail": "the agent's background shells could not be measured, so none were stopped"}) from exc
        refused = [pid for pid, v in verdicts if not v.allowed and v.code != bw_guard.REFUSE_GONE]
        if refused:
            raise HTTPException(409, {"code": "shells_not_stopped", "detail": f"{len(refused)} background {'shell' if len(refused) == 1 else 'shells'} could not be stopped"})
        return list(members)

    async def stop_members(uuid: str, members: list[tuple[int, str]]) -> list[int]:
        try:
            result = await asyncio.to_thread(bw_terminate.terminate, members)
        except LivenessUnmeasured as exc:
            raise HTTPException(409, {"code": "shells_not_stopped", "detail": "the background shells could not be checked, so none were signalled"}) from exc
        for pid in [*result.term, *result.kill]:
            logger.info("pack_move_stopped_background_shell", session_uuid=uuid, pid=pid, outcome=result.outcome)
        if result.survivors or result.outcome == bw_terminate.OUTCOME_STILL_RUNNING:
            raise HTTPException(409, {"code": "shells_not_stopped", "detail": f"{len(result.survivors) or 1} background process could not be stopped"})
        return [*result.term, *result.kill]

    async def interrupt(uuid: str) -> None:
        info = await bring_up.find_live(ops, uuid)
        if info is None:
            raise HTTPException(409, {"code": "session_gone", "detail": "the agent is not running here any more"})
        await send_escape(app_state.session_manager, info.session.id)

    async def find(uuid: str) -> Any:
        info = await bring_up.find_live(ops, uuid)
        if info is not None:
            subagent_listing.mark_subagents(app_state.session_manager, [info])
            parked_work_listing.mark_parked_work(app_state.session_manager, [info])
        return info

    def profile_root(uuid: str) -> Optional[Path]:
        key = account.session_account_key(_config_path(), uuid)
        folder = account.session_profile_dir(_config_path(), uuid) or (target_side.find_relay_profile(key) if key else None)
        return Path(folder) / "projects" if folder else None

    return Hooks(find=find, sleep=sleep, wake=wake, hide=hide,
                 account_key=lambda uuid: account.session_account_key(_config_path(), uuid), background_members=background_members, stop_members=stop_members, interrupt=interrupt,
                 profile_root=profile_root)


def live_hooks(app_state: Any) -> LiveHooks:
    from src.core.swarm import body as swarm_body

    async def sleep_agent(agent_id: int) -> None:
        try:
            await swarm_body.sleep(app_state, agent_id, "sleep")
        except swarm_body.BodyError as exc:
            raise HTTPException(409, {"code": "sleep_refused", "detail": str(exc)}) from exc

    async def wake_agent(agent_id: int) -> None:
        try:
            await swarm_body.wake(app_state, agent_id, "manual", "owner")
        except swarm_body.BodyError as exc:
            raise HTTPException(409, {"code": "wake_refused", "detail": str(exc)}) from exc

    return LiveHooks(session=source_hooks(app_state), sleep_agent=sleep_agent, wake_agent=wake_agent)
