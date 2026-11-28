
from __future__ import annotations

import asyncio
import sqlite3
import functools
import time
from contextlib import closing
from typing import Any, Optional

import structlog

from src.core.federation import mesh_peers
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.jobs import agent_facts, agent_host, agent_launch, carry, host_admit, install, keep_sync, member_view, paths, place, prewarm, replicas, tell
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.feed import JobsFeed
from src.core.pack.jobs.host import Host, default_request_for
from src.core.pack.jobs.ssh import readings as ssh_readings
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)

SWEEP_EVERY_S = 600.0
RETRY_BUILD_S = 60.0
READOPT_WAIT_S = 60.0
_built: dict = {}


def engine() -> Engine:
    if "engine" not in _built:
        raise JobError("jobs_not_ready", "auto-delegate is not ready yet", 503)
    return _built["engine"]


def host() -> Host:
    if "host" not in _built:
        raise JobError("jobs_not_ready", "auto-delegate is not ready yet", 503)
    return _built["host"]


def worker_hooks() -> "tuple":
    if "worker_hooks" not in _built:
        raise JobError("jobs_not_ready", "auto-delegate is not ready yet", 503)
    return _built["worker_hooks"]


def _publish_installing(tool: Optional[str]) -> None:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    if wired is not None and wired.keeper is not None:
        wired.keeper.set_installing(tool)
        wired._changed()  # noqa: SLF001


def _reprobe_after_install() -> None:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    if wired is not None and wired.keeper is not None:
        wired.keeper.refresh("install")
        wired._changed()  # noqa: SLF001


def _install_id(state_dir: Any) -> Optional[str]:
    from src.core.db import connect, db_path_for, get_meta
    from src.core.db_models import META_INSTALL_ID

    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        return get_meta(conn, META_INSTALL_ID)


def build(app: Any = None) -> "tuple[Host, Engine]":
    from src.config import settings

    state_dir = settings.get_state_dir()
    jobs_root = paths.check_root(paths.default_jobs_root())
    install_id = _install_id(state_dir)
    if not install_id:
        raise JobError("no_install_id", "this computer has no install id yet", 503)
    the_host = Host(state_dir=state_dir, jobs_root=jobs_root, install_id=install_id)
    agent = {"facts_for": functools.partial(agent_facts.caller_launch_facts, app), "notifier": functools.partial(tell.notify_caller, app)} if app is not None else {}
    the_engine = Engine(state_dir=state_dir, jobs_root=jobs_root, install_id=install_id, **agent)
    if app is not None:
        the_host.agent.bind(agent_host.AgentDeps.from_app(app))
    from src.core.pack.reserve.holds import HOLDS

    def owns(job_id: str, caller: str) -> bool:
        row = the_host.store.host_get(job_id)
        return HOLDS.owner(job_id) == caller or (row is not None and row.caller_install == caller)

    installer = install.Installer(the_host.store, jobs_root, restrictions=the_host._restrictions, owns_job=owns,  # noqa: SLF001
                                  on_installing=_publish_installing, on_done=_reprobe_after_install)
    _wire_feed(app, the_host, the_engine)
    _wire_jobs_load_extra(the_host)
    _built.update(host=the_host, engine=the_engine, installer=installer)
    return the_host, the_engine


def _wire_jobs_load_extra(the_host: Host) -> None:
    try:
        from src.core.pack.jobs.types import HostState
        from src.core.pack.machines import runtime
        from src.core.pack.reserve.holds import HOLDS

        wired = runtime.wiring()
        if wired is None:
            return

        def jobs_load() -> dict:
            live = the_host.store.host_list([HostState.PREPARING, HostState.RUNNING, HostState.PARKED])
            warm = sorted({r["project_uid"] for r in the_host.store.slot_rows() if r.get("project_uid") and r.get("memo")})[:64]
            held_cpu, held_ram, held_n = HOLDS.total()
            return {"active_count": len(live), "held_cpu": held_cpu, "held_ram_gb": held_ram, "held_n": held_n, "warm_projects": warm}

        wired.runtime.collector.add_extra("jobs_load", jobs_load)
    except Exception:  # noqa: BLE001
        pass


def _keep_sync(the_engine: Engine) -> keep_sync.KeepSync:
    from src.core.federation import peer_links

    async def warm(peer: str, uid: str, commit: str, deps: Any, setup: Any) -> dict:
        try:
            request = default_request_for(peer)
        except JobError as exc:
            return {"ok": False, "reason": exc.code}
        return await prewarm.send(request, uid, commit, deps, setup)

    def may_prewarm() -> bool:
        from src.core.mcp import beast_mode

        return beast_mode.approval_skip("delegate")

    async def make_copy(name: str, uid: str, peer: str) -> bool:
        from src.core.pack.identity import home

        made = await replicas.ensure(name, uid, peer, store=the_engine.store)
        home.notify_changed()
        return made

    syncer = keep_sync.KeepSync(the_engine.store, carry=functools.partial(carry.default_carry, copy_send=True), view_for=place.live_view, gauge=host_admit.own_snapshot, prewarm=warm,
                                project_of=carry.project_row, may_prewarm=may_prewarm, make_copy=make_copy,
                                members=functools.partial(member_view.for_copies, store=the_engine.store, self_iid=the_engine.install_id))
    if peer_links.LINKS is not None:
        peer_links.LINKS.add_connect_listener(syncer.on_reconnect)
    if caps_mod.mesh_on():
        mesh_peers.add_connect_listener(syncer.on_reconnect)
    return syncer


def _announce_caller_usage(app: Any, caller_session: str) -> None:
    async def _go() -> None:
        from src.core.resource_push import notifier, topics

        info = await agent_facts.info_for_caller(getattr(app.state, "session_manager", None), caller_session)
        if info is not None and info.session is not None:
            notifier.notify(topics.keyed(topics.SESSION_USAGE, info.session.id))

    try:
        asyncio.get_running_loop().create_task(_go()).add_done_callback(_log_usage_announce)
    except RuntimeError as exc:
        log.debug("pack_jobs_usage_announce_no_loop", error=str(exc))


def _log_usage_announce(task: "asyncio.Task[None]") -> None:
    if not task.cancelled() and task.exception() is not None:
        log.warning("pack_jobs_usage_announce_failed", error=type(task.exception()).__name__)


def _wire_feed(app: Any, the_host: Host, the_engine: Engine) -> None:
    hub = getattr(getattr(app, "state", None), "event_hub", None)
    if hub is None:
        log.warning("pack_jobs_feed_no_hub", detail="no event hub at boot: jobs are not pushed, the jobs list is read by polling")
        return
    feed = JobsFeed(hub, the_engine.store, on_caller=functools.partial(_announce_caller_usage, app))
    for store in (the_engine.store, the_host.store):
        store.on_change, store.on_removed = feed.changed, feed.removed
    _built["feed"] = feed


async def _wait_readopt(app: Any) -> None:
    task = getattr(getattr(app.state, "session_manager", None), "_boot_readopt_task", None)
    if task is None or task.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), READOPT_WAIT_S)
    except asyncio.TimeoutError:
        log.warning("pack_jobs_boot_readopt_wait_timed_out", seconds=READOPT_WAIT_S)
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("pack_jobs_boot_readopt_failed", error=type(exc).__name__)


async def _run(app: Any) -> None:
    while True:
        try:
            the_host, the_engine = build(app)
            break
        except (JobError, OSError, sqlite3.Error) as exc:
            log.warning("pack_jobs_boot_failed", error=type(exc).__name__, detail=str(exc)[:200])
            await asyncio.sleep(RETRY_BUILD_S)
    app.state.pack_jobs_host, app.state.pack_jobs_engine = the_host, the_engine
    app.state.pack_jobs_installer = _built["installer"]
    ssh_readings.shared(the_engine.store).bind()
    _built["installer"].recover()
    await _wait_readopt(app)
    _built["worker_hooks"] = agent_launch.worker_hooks(app)
    syncer = _keep_sync(the_engine)
    sync_task = asyncio.create_task(syncer.run(), name="pack-jobs-keep-sync")
    try:
        await _loop(the_host, the_engine)
    except asyncio.CancelledError:
        sync_task.cancel()
        for task in [*the_engine._tasks.values(), *the_host._tasks.values()]:
            task.cancel()
        raise


async def _loop(the_host: Host, the_engine: Engine) -> None:
    try:
        log.info("pack_jobs_recovered", host=await asyncio.to_thread(the_host.recover), engine=await the_engine.recover(),
                 agents=await the_host.recover_agents())
    except Exception as exc:  # noqa: BLE001
        log.warning("pack_jobs_recover_failed", error=type(exc).__name__)
    while True:
        await asyncio.sleep(SWEEP_EVERY_S)
        try:
            await asyncio.to_thread(the_host.sweep, time.time())
            await the_engine.sweep()
            await the_host.agent.sweep_watches()
        except Exception as exc:  # noqa: BLE001
            log.warning("pack_jobs_sweep_failed", error=type(exc).__name__)


def start(app: Any) -> "asyncio.Task[None]":
    return asyncio.create_task(_run(app), name="pack-jobs")
