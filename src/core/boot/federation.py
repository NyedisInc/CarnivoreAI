
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

from src.config import settings
from src.core import resource_push
from src.core.boot.steps import BootStep, FailureMode, teardown_slot
from src.core.boot.teardown import stop_task
from src.core.setup_state import current_setup_state

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()

_FEDERATION_SWALLOW = "startup must never fail on federation; a missing dns_sd, socket or peer is a named state, not a dead server"


@dataclass
class _LinkHandles:

    listener: Optional[object] = None
    pair_socket: Optional[object] = None
    events_task: Optional["asyncio.Task[None]"] = None
    notification_sync_task: Optional["asyncio.Task[None]"] = None
    pack_machines_task: Optional["asyncio.Task[None]"] = None
    pack_maintain_task: Optional["asyncio.Task[None]"] = None
    computers_rt: Optional[object] = None


@dataclass
class _DiscoveryHandle:

    discovery: Optional[object] = None


def _discovery_steps() -> list[BootStep]:
    held = _DiscoveryHandle()

    async def start(ctx: "BootContext") -> None:
        from src.core.federation.discovery import Discovery, testslot_instance_name
        from src.core.hosts.machine_identity import ioreg_platform_uuid

        from src.core.computers import runtime as _computers_runtime
        from src.core.federation.fed_key import local_fid

        _platform_uuid = await asyncio.to_thread(ioreg_platform_uuid)
        _federation_fid = await asyncio.to_thread(local_fid, settings.get_state_dir())
        _slot_name = testslot_instance_name(os.environ)
        held.discovery = Discovery(
            config_path=Path(settings.auth_config_file).expanduser(),
            fid_provider=lambda: _computers_runtime.advertised_fid() or _federation_fid,
            platform_uuid_provider=lambda: _platform_uuid,
            link_port_provider=_computers_runtime.advertised_link_port,
            advertise_allowed=not os.environ.get("CARNIVORE_SETTINGS_ENV_FILE") or _slot_name is not None,
            **({"name_provider": lambda: _slot_name} if _slot_name else {}),
        )
        ctx.app.state.federation_discovery = held.discovery

    def stop(_ctx: "BootContext") -> None:
        if held.discovery is not None:
            held.discovery.stop()

    return [BootStep(
        name="federation_discovery", order=620, start=start, stop=stop, stop_order=teardown_slot(6),
        failure=FailureMode.DEGRADED, degrades_on=(Exception,), failure_event="federation_discovery_start_failed",
        swallow_reason=_FEDERATION_SWALLOW,
    )]


def _byoai_feature_steps() -> list[BootStep]:

    def start(ctx: "BootContext") -> None:
        from src.core.skill_manager import card_art as _skill_card_art

        _skill_card_art.register_feature()
        from src.core.skill_manager import card_summary as _skill_card_summary

        _skill_card_summary.register_feature()
        from src.core.automations import schedule_nl as _automations_schedule_nl

        _automations_schedule_nl.register_feature()
        from src.api.skill_card_art_backfill import queue_missing as _queue_card_art

        ctx.app.state.card_art_backfill = asyncio.create_task(_queue_card_art(ctx.app))

    return [BootStep(name="byoai_features", order=630, start=start)]


async def _start_link(ctx: "BootContext", held: _LinkHandles) -> None:
    app = ctx.app
    from src.api import peer_auth as _peer_auth
    from src.core.federation import peer_links as _peer_links
    from src.core.federation.peer_listener import PeerListener, socket_path_for
    from src.core.hosts.ssh_master import default_instance_tag

    _fed_dir = Path.home() / ".carnivore" / "fed"
    held.listener = PeerListener(app, socket_path_for(_fed_dir, default_instance_tag()))
    await held.listener.start()
    from src.core.federation.pair_socket import PairSocket

    held.pair_socket = PairSocket(str(_fed_dir / f"pair-{default_instance_tag()}.sock"), settings.get_state_dir())
    await held.pair_socket.start()
    _peer_links.LINKS = _peer_links.PeerLinks(open_db=_peer_auth.open_db, listener_path=held.listener.path)
    from src.api.door_auth import door_login_tokens, door_totp_ok
    from src.core.computers.runtime import ComputersRuntime, LazyPack
    from src.core.computers.this_label import this_label as _fed_label
    from src.core import version as _version
    from src.core.pack.machines import runtime as _pack_machines

    door_file_name = f"door-{default_instance_tag()}.sock"
    app.state.door_file_name = door_file_name
    held.computers_rt = ComputersRuntime(
        open_db=_peer_auth.open_db, pack=LazyPack(_pack_machines.wiring), fed_dir=_fed_dir,
        listener_path=held.listener.path, config_path=Path(settings.auth_config_file).expanduser(),
        host=settings.host, label=_fed_label(), app_version=_version.resolve_version(),
        door_path=str(_fed_dir / door_file_name), door_totp_ok=door_totp_ok,
        door_login=door_login_tokens, refresh_store=lambda: app.state.refresh_store,
        setup_status=lambda: current_setup_state().status,
        discovery=lambda: getattr(app.state, "federation_discovery", None), notify=resource_push.notify)
    await held.computers_rt.prepare(_peer_links.LINKS)
    await _peer_links.LINKS.boot()
    await _start_pack_layer(ctx, held)


async def _start_pack_layer(ctx: "BootContext", held: _LinkHandles) -> None:
    app = ctx.app
    services = ctx.services
    from src.api import peer_auth as _peer_auth
    from src.core import version as _version
    from src.core.computers.this_label import this_label as _fed_label
    from src.core.federation import peer_events as _peer_events
    from src.core.federation import peer_links as _peer_links
    from src.core.pack.machines import runtime as _pack_machines
    from src.core.stats import rollup as _stats_rollup


    held.events_task = asyncio.create_task(_peer_events.run(app.state, _peer_auth.open_db), name="federation-peer-events")
    from src.core.notifications.sync import runtime as _notify_sync

    held.notification_sync_task = _notify_sync.start(app.state, _peer_auth.open_db)
    held.pack_machines_task = _pack_machines.start(
        _peer_auth.open_db, lambda: _peer_links.LINKS, label=_fed_label(), app_version=_version.resolve_version(),
        state_dir=lambda: str(settings.get_state_dir()),
        pipeline_rev=lambda: _stats_rollup.advertised_revisions(getattr(app.state, "stats_store", None)))
    from src.core.pack.relay import runtime as _pack_relay

    _pack_relay.start(_peer_auth.open_db, lambda: _peer_links.LINKS)
    from src.core.pack.skills import wiring as _pack_skills

    from src.core.pack.skills.watch import raise_open_file_limit as _raise_nofile

    _raise_nofile()
    _pack_skills.start(lambda: _peer_links.LINKS, services)
    from src.core.pack.placement import enhanced as _pack_placement_ai, maintain as _pack_maintain

    _pack_placement_ai.register_feature()
    held.pack_maintain_task = _pack_maintain.start(app, _pack_machines.wiring())
    from src.api import pack_copy_sync as _pack_copy_sync

    _pack_copy_sync.subscribe(app.state)
    await held.computers_rt.start()


async def _stop_link(ctx: "BootContext", held: _LinkHandles) -> None:
    if held.computers_rt is not None:
        await ctx.stop_part("computers_runtime", held.computers_rt.stop)
    await stop_task(held.pack_maintain_task, wait=False)
    from src.api import pack_copy_sync as _pack_copy_sync_stop

    await ctx.stop_part("pack_copy_sync", _pack_copy_sync_stop.unsubscribe)
    await stop_task(held.pack_machines_task, wait=False)
    await stop_task(held.notification_sync_task, wait=False)
    if held.events_task is not None:
        await stop_task(held.events_task, wait=False)
        from src.core.federation import peer_event_stream as _peer_event_stream

        await ctx.stop_part("peer_event_stream", _peer_event_stream.stop)
    if held.listener is not None:
        from src.core.federation import peer_links as _peer_links

        if _peer_links.LINKS is not None:
            await ctx.stop_part("peer_links", _peer_links.LINKS.shutdown)
            _peer_links.LINKS = None
        await ctx.stop_part("federation_listener", held.listener.stop)
        if held.pair_socket is not None:
            await ctx.stop_part("federation_pair_socket", held.pair_socket.stop)


def _link_steps() -> list[BootStep]:
    held = _LinkHandles()

    async def start(ctx: "BootContext") -> None:
        await _start_link(ctx, held)

    async def stop(ctx: "BootContext") -> None:
        await _stop_link(ctx, held)

    return [BootStep(
        name="federation_link", order=640, stop_parts=("computers_runtime", "pack_copy_sync", "peer_event_stream", "peer_links", "federation_listener", "federation_pair_socket"), start=start, stop=stop, stop_order=teardown_slot(5),
        failure=FailureMode.DEGRADED, degrades_on=(Exception,), failure_event="federation_link_start_failed",
        swallow_reason=_FEDERATION_SWALLOW, stop_after_failed_start=True,
    )]


def steps() -> list[BootStep]:
    return [*_discovery_steps(), *_byoai_feature_steps(), *_link_steps()]
