
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from src.core import resource_push
from src.core.resource_push import topics
from src.core.sessions import launch_overlay, session_events
from src.cplugs.sdk import ports
from src.core.argent import refresh, cards_sync, commits, cost_poller, fallback_spend, gateway_reach, health, poll_relay, outage, rollout, timeline, upstream_registry, work_items, writeback
from src.core.argent.overlay import ArgentOverlay
from src.core.argent.registration import Registrar, follow_rename
from src.core.argent.runtime import get_runtime

logger = structlog.get_logger()

PORT_NAME = "argent"
_unsubscribe: Optional[Any] = None
_login_phase: list = [None]
_unhear: Optional[Any] = None


def _live_reach() -> Optional[gateway_reach.Reach]:
    reach = gateway_reach.get()
    manager = fallback_spend.session_manager()
    if reach is not None or manager is None:
        return reach
    from src.core.hosts.ssh_master import default_control_dir, ensure_control_dir

    def side_for(host_key: str) -> Any:
        host = manager.hosts.connected().get(host_key)
        return None if host is None else host.pool

    gateway_reach.set_reach(gateway_reach.Reach(side_for=side_for, label_for=manager.hosts.label, socket_dir=ensure_control_dir(default_control_dir())))
    return gateway_reach.get()


async def _on_poll(report: health.HealthReport, enabled: bool) -> None:
    await outage.on_report(report, enabled)
    phase = await asyncio.to_thread(get_runtime().store.login_phase)
    if phase != _login_phase[0]:
        if _login_phase[0] is not None:
            resource_push.notify(topics.ARGENT_STATUS)
        _login_phase[0] = phase
    reach = _live_reach() if enabled else gateway_reach.get()
    if reach is not None and not enabled:
        await reach.close()
    elif reach is not None:
        for key in list(fallback_spend.session_manager().hosts.connected()):
            await reach.ensure(key)
    from src.core.argent import pair_sync  # noqa: PLC0415

    sync = pair_sync.get()
    if sync is not None:
        await sync.credentials_pass()
    await refresh.check_if_running()
    if enabled and sync is not None:
        await sync.poll.after_poll()
    if enabled and report.state == health.UP and report.upstream_chain is True:
        await upstream_registry.refresh()


def _on_port(name: str) -> None:
    if name != PORT_NAME:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("argent_port_changed_without_loop")
        return
    runtime = get_runtime()
    if ports.get(PORT_NAME) is not None:
        health.start(runtime.store.login_expired, on_report=_on_poll)
        outage.start()
        fallback_spend.start()
        work_items.start()
        timeline.start()
        cost_poller.start()
        commits.start()
        writeback.start()
        cards_sync.start()
        refresh.start()
        launch_overlay.register(ArgentOverlay())
        _hear_sessions()
        loop.create_task(rollout.resume_at_boot())
        return
    _deafen()
    launch_overlay.register(None)
    loop.create_task(_shutdown())


def _hear_sessions() -> None:
    global _unhear
    if _unhear is None:
        withdraw = (session_events.subscribe(Registrar()), session_events.subscribe(writeback.on_session_event))

        def _unhear_both() -> None:
            for one in withdraw:
                one()

        _unhear = _unhear_both


def _deafen() -> None:
    global _unhear
    if _unhear is not None:
        _unhear()
        _unhear = None


async def _shutdown() -> None:
    await get_runtime().login.cancel()
    await fallback_spend.stop()
    await rollout.stop()
    await work_items.stop()
    await timeline.stop()
    commits.stop()
    await writeback.stop()
    await cards_sync.stop()
    outage.stop()
    await cost_poller.stop()
    await refresh.stop()
    reach = gateway_reach.get()
    if reach is not None:
        await reach.close()
        gateway_reach.set_reach(None)
    poll_relay.forget()
    await health.stop()


def install() -> None:
    global _unsubscribe
    if _unsubscribe is None:
        _unsubscribe = ports.subscribe(_on_port)
        session_events.subscribe(follow_rename)
