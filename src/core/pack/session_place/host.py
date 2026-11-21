
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.crosstalk.spawn_rules import agent_cli_flags
from src.core.launch_profiles.resolve import default_profile
from src.core.launch_profiles.permissions import UnsupportedPosture, permission_flags
from src.core.pack.identity import home
from src.core.pack.jobs import agent_launch, host_admit
from src.core.pack.jobs.agent_account import AccountPick
from src.core.pack.jobs.types import JobError
from src.core.pack.machines import restrictions as restrict
from src.core.pack.placement import workload
from src.core.pack.reserve.holds import HOLDS
from src.core.pack.session_place import copy_ready
from src.core.pack.session_place.plan import clean
from src.core.pack.session_place.wire import PeerCreateAnswer, PeerCreateBody

log = structlog.get_logger(__name__)

HOLD_S = host_admit.ADMIT_HOLD_S
_RANK = {"ask": 1, "accept_edits": 2, "skip_all": 3}
TOTAL_WAIT_S = 90.0


class _KeyedLocks:

    def __init__(self) -> None:
        self._held: Dict[str, List[Any]] = {}

    @contextlib.asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        entry = self._held.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._held.pop(key, None)


_REQUEST_LOCKS = _KeyedLocks()
_COPY_LOCKS = _KeyedLocks()


async def default_live_folders(app: Any) -> List[str]:
    infos = await app.state.session_manager.list_session_infos()
    return [os.path.realpath(i.session.working_dir) for i in infos if i.tmux_session and getattr(i, "activity_status", None) != "dead" and i.session.working_dir]


def default_config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def default_profiles() -> Sequence[Any]:
    from src.config import settings

    return list(settings.get_launch_profiles())


@dataclass
class Seams:

    live_folders: Callable[[Any], Awaitable[List[str]]] = default_live_folders
    config_path: Callable[[], Path] = default_config_path
    profiles: Callable[[], Sequence[Any]] = default_profiles
    extra: Dict[str, Any] = field(default_factory=dict)


def seams_of(app: Any) -> Seams:
    return getattr(app.state, "session_place_seams", None) or Seams()


def _plain(profile: Any) -> bool:
    return getattr(profile, "custom_command", None) is None and not getattr(profile, "before_launch", None)


def launch_choice(body: PeerCreateBody, profiles: Sequence[Any]) -> Tuple[str, List[str], str]:
    family, wanted = body.family, ("ask" if body.posture == "unknown" else body.posture)
    effort = agent_cli_flags(family, body.effort, False) if body.effort and family != "shell" else []
    if family != "shell":
        try:
            permission_flags(family, wanted)
        except UnsupportedPosture:
            wanted = "ask"

    def flags_for(profile: Any) -> Optional[List[str]]:
        if profile.harness != family or not _plain(profile):
            return None
        if family == "shell":
            return []
        if profile.permissions == "harness_default":
            return list(permission_flags(family, wanted))
        return [] if _RANK.get(profile.permissions, 3) <= _RANK[wanted] else None

    named = next((p for p in profiles if body.profile_name and p.id.lower() == body.profile_name.lower() and p.harness == family), None)
    default = default_profile(list(profiles), family)
    others = [p for p in profiles if p.harness == family and p is not named and p.id != default.id]
    for profile, agent_type in ([(named, named.id)] if named is not None else []) + [(default, family)] + [(p, p.id) for p in others]:
        flags = flags_for(profile)
        if flags is None:
            continue
        if profile is named:
            return agent_type, effort + flags, clean(f"profile {named.id} on this computer")
        why = f"{'this computer default' if profile is default else 'profile ' + profile.id} {family} profile, {wanted} posture"
        if body.profile_name:
            why = f"profile {body.profile_name[:40]} here is not usable at the starter's posture, so {why}" if named is not None \
                else f"no profile named {body.profile_name[:40]} here, so {why}"
        return agent_type, effort + flags, clean(why)
    raise JobError("posture_unsafe", clean(f"this computer has no plain {family} profile at the {wanted} posture or lower"), 409)


def _plan(body: PeerCreateBody, agent_type: str, flags: List[str], pick: Optional[AccountPick]) -> agent_launch.LaunchPlan:
    return agent_launch.LaunchPlan(agent_type=agent_type, model=body.model, extra_args=flags, extra_env=dict(pick.extra_env) if pick else {},
                                   opening_prompt="", account_id=pick.account_id if pick else None)


def _inside(folder: str, root: str) -> bool:
    current = folder
    while True:
        if current == root:
            return True
        try:
            if os.path.samefile(current, root):
                return True
        except OSError:
            pass
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def _note(state: copy_ready.CopyState, body: PeerCreateBody) -> str:
    base = f"started on commit {state.head[:10]}"
    if state.moved:
        return clean(f"{base}; the copy was moved forward to the home's latest commit")
    if state.ahead:
        return clean(f"{base}; this computer's copy is ahead of the home's {body.home_head[:10]}")
    return clean(f"{base}, the home's latest commit")


async def create(app: Any, caller: str, body: PeerCreateBody) -> PeerCreateAnswer:
    host = getattr(app.state, "pack_jobs_host", None)
    if host is None:
        raise JobError("jobs_not_ready", "this computer is not ready to start sessions yet", 503)
    deps = host.agent._need()
    try:
        async with asyncio.timeout(TOTAL_WAIT_S):
            async with _REQUEST_LOCKS.hold(body.request_id):
                return await _create(app, host, deps, caller, body)
    except TimeoutError as exc:
        raise JobError("host_timeout", "this computer took too long to start the session", 503) from exc


async def _create(app: Any, host: Any, deps: Any, caller: str, body: PeerCreateBody) -> PeerCreateAnswer:
    seams = seams_of(app)
    project = await asyncio.to_thread(host._gate_sync, caller, body.project_uid)
    if project["pack_state"] != home.REPLICA:
        raise JobError("project_not_here", "this computer holds no copy of that project", 409)
    prior = await asyncio.to_thread(host.store.host_place_get, body.request_id)
    if prior is not None:
        if prior["caller_install"] != caller or prior["project_uid"] != body.project_uid:
            raise JobError("request_id_taken", "that request id was used for something else", 409)
        if prior["answer"]:
            return PeerCreateAnswer.model_validate_json(prior["answer"])
        if await deps.listed(prior["session_id"]):
            await host.agent._stop_quietly(prior["session_id"], prior["session_uuid"])
    await _enforce_cap(host, deps, caller, body.project_uid, project)
    snapshot = await asyncio.to_thread(host_admit.own_snapshot)
    host_admit.check_pegged(snapshot)
    work = workload.resolve({"kind": workload.KIND_SESSION})
    said: List[str] = []

    def fits(held_cpu: float, held_ram: float) -> bool:
        sentence = host._admit(workload.Workload(work.kind, work.est_cpu_cores + held_cpu, work.est_ram_gb + held_ram, work.est_disk_gb))
        if sentence:
            said.append(sentence)
        return not sentence

    if not await asyncio.to_thread(HOLDS.try_hold, body.request_id, caller, work.est_cpu_cores, work.est_ram_gb, HOLD_S, fits):
        raise JobError("host_busy", clean(said[-1] if said else "this computer has no room for another session now"), 503)
    try:
        return await _launch(app, host, deps, seams, caller, body, project)
    except BaseException:
        HOLDS.drop(body.request_id)
        raise


async def _enforce_cap(host: Any, deps: Any, caller: str, project_uid: str, project: Dict[str, Any]) -> None:
    placed = 0
    for row in await asyncio.to_thread(host.store.host_place_list):
        if row["answer"] and await deps.listed(row["session_id"]):
            placed += 1
    live = host._live_agents() + await asyncio.to_thread(host._agent_jobs_live) + placed
    restrict.enforce(host._restrictions(), restrict.ACTION_HOST_AGENTS, project_uid=project_uid, company_uid=project.get("company_uid"), live_agents=live)


async def _launch(app: Any, host: Any, deps: Any, seams: Seams, caller: str, body: PeerCreateBody, project: Dict[str, Any]) -> PeerCreateAnswer:
    pick: Optional[AccountPick] = None
    if body.family != "shell":
        if not deps.harness_present(body.family):
            raise JobError("no_harness", f"{body.family} is not installed on this computer", 409)
        pick = await asyncio.to_thread(deps.resolve_account, body.family, body.account_key, caller)
    root = os.path.realpath(str(project["root"]))
    async with _COPY_LOCKS.hold(root):
        live = [f for f in await seams.live_folders(app) if _inside(f, root)]
        state = await asyncio.to_thread(copy_ready.ready, root, caller, body.branch, body.home_head, air_gap=bool(project.get("air_gap")), in_use=bool(live))
        if not state.ok:
            raise JobError(state.code or copy_ready.NOT_READY, clean(state.detail), 409)
        agent_type, flags, used = launch_choice(body, await asyncio.to_thread(seams.profiles))
        session_id = f"ses_{uuid.uuid4().hex[:8]}"
        await asyncio.to_thread(host.store.host_place_put, body.request_id, caller_install=caller, project_uid=body.project_uid, session_id=session_id, answer="")
        label = clean(body.label, 120) or clean(project.get("name"), 120) or body.family
        future = asyncio.ensure_future(deps.create_worker(_plan(body, agent_type, flags, pick), session_id, label, root))
        try:
            ref = await asyncio.shield(future)
        except asyncio.CancelledError:
            made = await asyncio.gather(future, return_exceptions=True)
            await host.agent._stop_quietly(session_id, getattr(made[0], "session_uuid", None))
            raise
        except Exception as exc:  # noqa: BLE001
            await host.agent._stop_quietly(session_id, None)
            raise host.agent._create_error(exc) from exc
    if pick is not None and body.family == "claude":
        pin = pick.account_id or (body.account_key if pick.how == "relay" else None)
        if pin:
            from src.core.account_switch import session_pin

            await asyncio.to_thread(session_pin.carry, seams.config_path(), ref.session_uuid, pin)
    answer = PeerCreateAnswer(session_id=ref.session_id, session_uuid=ref.session_uuid, tmux_name=ref.tmux_name, epoch=ref.epoch, working_dir=root,
                              account_label=clean(pick.label if pick else ""), account_how=pick.how if pick else "", profile_used=used,
                              copy_note=_note(state, body))
    await asyncio.to_thread(host.store.host_place_put, body.request_id, session_uuid=ref.session_uuid, answer=json.dumps(answer.model_dump()))
    HOLDS.extend(body.request_id, host_admit.RUN_HOLD_S)
    log.info("session_place_started", family=body.family, moved=state.moved, ahead=state.ahead)
    return answer
