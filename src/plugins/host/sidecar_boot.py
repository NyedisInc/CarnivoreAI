
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.db import connect, db_path_for
from src.core.skills.ledger import InstallLedger
from src.plugins.host import activity_log, capabilities, feed_fanout, folder_watch, inspector_telemetry, mcp_health_port, owner_switch, plugin_ai, plugin_bus, plugin_channels, prune_gone, sidecar_index, sidecar_registry, sidecar_services, sidecar_topics, dependencies, tier0_channels, ui_slots, webhook_routes
from src.plugins.host.session_create_port import SessionCreatePort, standing_of
from src.plugins.host.mcp_health_port import HostMcpHealth
from src.plugins.host.runtime import CPLUGS_TOPIC, Host
from src.plugins.runtime import guards, sandbox
from src.plugins.runtime.children import ChildLedger
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import REQUEST_TIMEOUT
from src.plugins.runtime.socket_server import PluginSocketManager
from src.plugins.runtime.supervisor import Supervisor, safe_mode_from_env
from src.plugins.runtime.timers import TimerScheduler

logger = structlog.get_logger()

ALERT_SEVERITY = {"crash_loop": "error", "revoked": "error", "integrity": "error", "index_expired": "warn", "safe_mode": "warn",
                  "removed": "info"}
TITLE_PREFIX = "app_alert.cplug_runtime."
SANDBOX_ALERT_KEY = "cplug.sandbox"
UI_INVALIDATE_INTERVAL = 0.5


def _provides_mcp_health(d: Any) -> bool:
    manifest = getattr(d, "manifest", None)
    if manifest is None:
        return False
    perms = getattr(manifest, "permissions", ()) or ()
    subs = getattr(manifest, "subscriptions", ()) or ()
    return "mcp.health.read" in perms or mcp_health_port.EVENT_FAMILY in subs


class SideEffects:

    def __init__(self) -> None:
        self._cancellers: Dict[str, List[Callable[[str], int]]] = {"inbox": [], "timers": [], "routes": []}

    def register(self, kind: str, canceller: Callable[[str], int]) -> None:
        self._cancellers[kind].append(canceller)

    def cancel(self, plugin_id: str) -> Mapping[str, int]:
        counts: Dict[str, int] = {}
        for kind, cancellers in self._cancellers.items():
            counts[kind] = 0
            for canceller in cancellers:
                try:
                    counts[kind] += int(canceller(plugin_id))
                except (OSError, ValueError, KeyError, RuntimeError) as exc:
                    logger.warning("cplug_side_effect_cancel_failed", cplug=plugin_id, kind=kind, error_type=type(exc).__name__)
        return counts


class SidecarRuntime:

    def __init__(self, host: Any, app: Any, loop: asyncio.AbstractEventLoop, *, raise_alert: Optional[Callable[..., Any]] = None,
                 resolve_alert: Optional[Callable[[str], Any]] = None, env_safe: Callable[[], bool] = safe_mode_from_env, app_version: Optional[str] = None) -> None:
        self.host, self.app, self.loop, self._env_safe = host, app, loop, env_safe
        self.state_dir = Path(host.state_dir)
        self._raise_alert, self._resolve_alert = raise_alert, resolve_alert
        self.route_safe = False
        self.sandbox_probe: Optional[Dict[str, Any]] = None
        self.tokens = OwnerTokens()
        self.effects = SideEffects()
        self.children = ChildLedger(self.state_dir)
        self._activity = activity_log.ActivityLog(self.state_dir)
        self._create_standing: Callable[[str], str] = lambda _pid: "not_running"
        self.session_create = SessionCreatePort(app, standing=lambda pid: self._create_standing(pid))
        self.effects.register("inbox", self.session_create.withdraw_for)
        self.timer_scheduler = TimerScheduler(self._send_timer_tick)
        self.effects.register("timers", self.timer_scheduler.cancel_for)
        self.effects.register("routes", lambda pid: webhook_routes.cancel_for_plugin(self.host, pid))
        self.socket_manager = PluginSocketManager()
        self.tier0_channels = tier0_channels.Tier0ChannelRegistry()
        self.inspector = inspector_telemetry.telemetry_for(self.state_dir)
        publish = getattr(self.host, "publish", None)
        self.inspector.bind_publisher(publish if callable(publish) else None)
        self.plugin_bus = plugin_bus.PluginBus(
            host=self.host,
            state_dir=lambda: getattr(self, "state_dir", self.host.state_dir),
            supervisor_getter=lambda: getattr(self, "supervisor", None),
            safe_mode_getter=self.safe_mode,
            on_loop=self.on_loop,
        )
        self._stop_cleanups: List[Callable[[str], None]] = []
        self.dispatcher = HostDispatcher(self._services(), self.tokens, trace_sink=self.inspector.record_event)
        self.supervisor = Supervisor(self.state_dir, app_version if app_version is not None else (dependencies.app_version() or "0"),
                                     self.dispatcher, self._supervisor_alert, self.effects.cancel, self._record_activity,
                                     safe_mode=True, children=self.children, sockets=self.socket_manager)
        self.supervisor.on_state_change = lambda pid, _state: self.inspector.notify(pid)
        self._create_standing = standing_of(self.supervisor, self.state_dir)
        self.supervisor.on_stopped = self._on_stopped
        self.supervisor.on_started = self._on_started
        self.index = sidecar_index.IndexAdapter(self, self._catalog_cache)
        self.folder_watch = folder_watch.FolderWatch(self)
        self._mcp_health_owner: Optional[str] = None
        self.mcp_health: Optional[HostMcpHealth] = None
        self.feed_fanout = feed_fanout.FeedFanout(
            lambda pid, family, seq, payload: self.supervisor.deliver_event(pid, family, seq, payload),
            self._feed_subscribers,
        )


    def _catalog_cache(self) -> Any:
        return getattr(getattr(getattr(getattr(self.app, "state", None), "services", None), "catalog", None), "index_cache", None)

    def on_loop(self, fn: Callable[..., Any], *args: Any) -> None:
        try:
            running: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            fn(*args)
        else:
            self.loop.call_soon_threadsafe(fn, *args)

    def _key(self, plugin_id: str) -> str:
        try:
            return self.host.install_key(plugin_id)
        except (KeyError, OSError, ValueError):
            return plugin_id

    def _record_activity(self, entry: Dict[str, Any]) -> None:
        try:
            running = asyncio.get_running_loop() is self.loop
        except RuntimeError:
            running = False
        plugin = str(entry.get("plugin", ""))
        self._activity.record(self._key(plugin), method=str(entry.get("method", "")), permission=str(entry.get("permission", "")),
                              target=str(entry.get("detail", "")), status=str(entry.get("outcome", "")), hot=running)

    def _alert_writer(self) -> Callable[..., Any]:
        if self._raise_alert is not None:
            return self._raise_alert
        from src.core.app_alerts.service import raise_alert  # noqa: PLC0415

        return raise_alert

    def _supervisor_alert(self, plugin_id: str, key: str, reason: str) -> None:
        self._alert_writer()(f"cplug.{plugin_id}.{key}", source=f"cplug.{plugin_id}", severity=ALERT_SEVERITY.get(key, "warn"),
                             title_key=f"{TITLE_PREFIX}{key}.title", params={"plugin": plugin_id, "reason": reason})
        self._publish_cplugs_later()

    def _publish_cplugs_later(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self.host.publish, CPLUGS_TOPIC)
        except RuntimeError:
            pass

    def resolve_alerts(self, plugin_id: str) -> None:
        if self._resolve_alert is None:
            from src.core.app_alerts.service import resolve  # noqa: PLC0415

            self._resolve_alert = resolve
        for key in ALERT_SEVERITY:
            self._resolve_alert(f"cplug.{plugin_id}.{key}")

    def _plugin_alert(self, plugin_id: str, key: str, severity: str, title: str, _extra: Mapping[str, Any]) -> None:
        self._alert_writer()(key, source=f"cplug.{plugin_id}", severity=severity, title_key=f"{TITLE_PREFIX}plugin_alert.title",
                             params={"plugin": plugin_id, "title": title})

    def _services(self) -> HostServices:
        toasters: Dict[str, Callable[..., Any]] = {}

        def toast(plugin_id: str, ref: str, title: str) -> None:
            fn = toasters.setdefault(plugin_id, capabilities.toaster(plugin_id, self.app.state))
            self.on_loop(fn, ref, title)

        def coalesce(topic: str, scope: str, interval: float, detail: Optional[str] = None) -> None:
            self.on_loop(self.host.publish_coalesced, topic, scope, interval, detail)

        publish_topic = sidecar_topics.make_publisher(self._key, coalesce)

        def invalidate_ui(plugin_id: str, surface: Optional[str]) -> None:
            if plugin_id == getattr(self, "_mcp_health_owner", None) and surface in (None, "status_source") and self.mcp_health is not None:
                self.on_loop(lambda: asyncio.create_task(self.mcp_health.refresh()) if self.mcp_health else None)
            key = self._key(plugin_id)
            self.on_loop(self.host.publish_coalesced, f"cplug_ui:{key}", key, UI_INVALIDATE_INTERVAL)

        async def list_sessions() -> List[Dict[str, Any]]:
            infos = await capabilities.local_infos_from_app(self.app.state)()
            return [i.model_dump(mode="json") for i in infos]

        async def get_session(ref: str) -> Optional[Dict[str, Any]]:
            for row in await list_sessions():
                inner = row.get("session") or {}
                if ref in (inner.get("id"), row.get("tmux_session"), row.get("session_uuid")):
                    return row
            return None

        def live_port() -> HostMcpHealth:
            if self.mcp_health is None:
                raise guards.Refused("unavailable", "mcp health is off")
            return self.mcp_health

        async def process_snapshot() -> Dict[str, Any]:
            return await live_port().process_snapshot()

        async def mcp_config(ref: Optional[str]) -> Dict[str, Any]:
            return await live_port().mcp_config(ref)

        async def mcp_links(ref: Optional[str]) -> Dict[str, Any]:
            return await live_port().mcp_links(ref)

        def register_stop_cleanup(fn: Callable[[str], None]) -> None:
            cleanups = getattr(self, "_stop_cleanups", None)
            if isinstance(cleanups, list):
                cleanups.append(fn)

        return HostServices(activity=self._record_activity, list_sessions=list_sessions, get_session=get_session, toast=toast,
                            alert=self._plugin_alert, publish_topic=publish_topic, invalidate_ui=invalidate_ui,
                            process_snapshot=process_snapshot, mcp_config=mcp_config, mcp_links=mcp_links,
                            create_session=self.session_create.create,
                            **sidecar_services.build_services(
                                host=self.host,
                                app=getattr(self, "app", None),
                                state_dir=lambda: getattr(self, "state_dir", self.host.state_dir),
                                supervisor_getter=lambda: getattr(self, "supervisor", None),
                                bus=getattr(self, "plugin_bus", None),
                                coalesce=coalesce,
                                on_plugin_stopped_register=register_stop_cleanup,
                            ))


    async def _render_mcp_status(self) -> Optional[Dict[str, Any]]:
        from src.plugins.host import sidecar_ui, ui_doc  # noqa: PLC0415

        owner = self._mcp_health_owner
        if not owner:
            return None
        d = sidecar_registry.find(owner)
        proc = await self.supervisor.ensure(owner)
        if d is None or proc is None or bool(getattr(proc, "ended", None)):
            return None
        try:
            return ui_doc.validate(await sidecar_ui._render(proc, "status_source", {}), routes=d.manifest.routes,
                                   tools=[t.get("name") for t in d.manifest.tools if isinstance(t, dict)])
        except ui_doc.UiDocError as exc:
            raise RuntimeError(exc.code) from exc

    async def _send_timer_tick(self, plugin_id: str, name: str, scheduled_for: int) -> None:
        proc = self.supervisor.process(plugin_id)
        if proc is None or proc.ended is not None:
            return
        await proc.request("timer.tick", {"name": name, "scheduled_for": scheduled_for}, timeout=REQUEST_TIMEOUT)

    def _all_definitions(self) -> List[Any]:
        from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

        listed_fn = getattr(self.host, "listed", None)
        base = list(listed_fn()) if callable(listed_fn) else list(host_runtime.listed())
        seen = {d.id for d in base if getattr(d, "id", None)}
        registry = sidecar_registry.current()
        if registry is not None:
            for defn in registry.listed():
                if getattr(defn, "id", None) and defn.id not in seen:
                    base.append(defn)
                    seen.add(defn.id)
        return base

    async def _on_started(self, spec: Any) -> None:
        if spec.timers:
            self.timer_scheduler.arm(spec.ctx.plugin_id, spec.timers)
        from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

        d = sidecar_registry.find(spec.ctx.plugin_id) or host_runtime.find(spec.ctx.plugin_id)
        if not isinstance(d, sidecar_registry.SidecarDefinition):
            return
        plugin_channels.sync_plugin(
            self.host,
            d,
            safe_mode_active=any(self.safe_mode().values()),
            supervisor=self.supervisor,
            tier0_registry=self.tier0_channels,
        )
        ui_slots.registry_for(self.state_dir).sync(
            self._all_definitions(),
            host=self.host,
            safe_mode_active=any(self.safe_mode().values()),
            supervisor=self.supervisor,
        )

    def _on_stopped(self, plugin_id: str) -> Any:
        self.timer_scheduler.cancel_for(plugin_id)
        plugin_channels.unregister_plugin(plugin_id, host=self.host, tier0_registry=self.tier0_channels)
        reg = ui_slots.registry_for(self.state_dir)
        reg.clear_plugin(plugin_id, host=self.host)
        reg.sync(
            self._all_definitions(),
            host=self.host,
            safe_mode_active=any(self.safe_mode().values()),
            supervisor=self.supervisor,
        )
        key = self._key(plugin_id)
        for cleanup in getattr(self, "_stop_cleanups", ()):
            cleanup(key)
        return self.mcp_health_switched(plugin_id, False)

    async def send_channel(self, plugin_id: str, channel: str, context: Mapping[str, Any]) -> Any:
        from src.plugins.host import fetch_proxy, risk, runtime as host_runtime, state as owner_state  # noqa: PLC0415
        from src.plugins.runtime.supervisor import TIER0_STATE  # noqa: PLC0415

        if any(self.safe_mode().values()) or not self.host.enabled(plugin_id):
            raise guards.Refused("disabled", "plugin_disabled")
        if self.supervisor.state(plugin_id) != TIER0_STATE:
            raise guards.Refused("disabled", self.supervisor.state(plugin_id))
        found = self.tier0_channels.get(plugin_id, channel)
        d = found[0] if found is not None else (sidecar_registry.find(plugin_id) or host_runtime.find(plugin_id))
        if isinstance(d, sidecar_registry.SidecarDefinition):
            st = owner_state.get(self.state_dir, d.manifest)
            if risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest):
                raise guards.Refused("permission_denied", "needs_approval")
        limiter = getattr(self, "_tier0_limiter", None)
        if limiter is None:
            limiter = self._tier0_limiter = fetch_proxy.RateLimiter()
        return await self.tier0_channels.send(
            plugin_id,
            channel,
            context,
            host=self.host,
            state_dir=self.state_dir,
            limiter=limiter,
        )

    async def run_macro(
        self,
        plugin_id: str,
        macro_id: str,
        *,
        session_ref: Optional[str] = None,
        owner_token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from src.plugins.host import risk, runtime as host_runtime, state as owner_state  # noqa: PLC0415
        from src.plugins.runtime.supervisor import TIER0_STATE  # noqa: PLC0415

        if any(self.safe_mode().values()) or not self.host.enabled(plugin_id):
            raise guards.Refused("disabled", "plugin_disabled")
        if self.supervisor.state(plugin_id) != TIER0_STATE:
            raise guards.Refused("disabled", self.supervisor.state(plugin_id))
        d = sidecar_registry.find(plugin_id) or host_runtime.find(plugin_id)
        if not isinstance(d, sidecar_registry.SidecarDefinition):
            raise KeyError(f"plugin {plugin_id} not found")
        st = owner_state.get(self.state_dir, d.manifest)
        if risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest):
            raise guards.Refused("permission_denied", "needs_approval")
        spec = self.host.sidecar_spec(d)
        return await tier0_channels.execute_macro(
            d,
            macro_id,
            dispatcher=self.dispatcher,
            ctx=spec.ctx,
            owner_token=owner_token,
            session_ref=session_ref,
        )

    def _feed_subscribers(self, family: str) -> List[str]:
        if any(self.safe_mode().values()):
            return []
        registry = sidecar_registry.current()
        return feed_fanout.feed_subscribers_for(self.host, registry.listed() if registry is not None else [], family)

    def refresh_feed(self) -> None:
        self.feed_fanout.refresh()

    async def mcp_health_switched(
        self,
        plugin_id: Optional[str],
        enabled: bool,
        *,
        definition: Optional[Any] = None,
    ) -> None:
        if enabled:
            if not plugin_id:
                return
            if definition is None:
                from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

                definition = sidecar_registry.find(plugin_id) or host_runtime.find(plugin_id)
            if definition is None or not _provides_mcp_health(definition):
                return
            if self.mcp_health is None:
                owner = plugin_id
                self._mcp_health_owner = owner
                self.mcp_health = HostMcpHealth(
                    lambda family, seq, payload: self.supervisor.deliver_event(owner, family, seq, payload),
                    self._render_mcp_status,
                )
                self.mcp_health.start()
        elif self.mcp_health is not None and (plugin_id is None or plugin_id == self._mcp_health_owner):
            port, self.mcp_health, self._mcp_health_owner = self.mcp_health, None, None
            await port.stop()


    def safe_mode(self) -> Dict[str, bool]:
        return {"env": self._env_safe(), "owner": self.route_safe, "off": not owner_switch.read(self.state_dir)}

    def status(self) -> Dict[str, Any]:
        why = self.safe_mode()
        return {"enabled": not why["off"], "safe_mode": {"env": why["env"], "owner": why["owner"], "active": why["env"] or why["owner"]},
                "sandbox": self.sandbox_probe}

    async def activate_enabled(self) -> None:
        if any(self.safe_mode().values()):
            return
        registry = sidecar_registry.current()
        wanted = [d for d in (registry.listed() if registry is not None else []) if self.host.enabled(d.id)]
        if wanted:
            if any(getattr(getattr(d, "manifest", None), "tier", None) == "catalog" for d in wanted):
                await self.index.ensure()
            for d in wanted:
                try:
                    await self.supervisor.activate(self.host.sidecar_spec(d))
                    await self.mcp_health_switched(d.id, True)
                except (sandbox.SandboxUnavailable, OSError, ValueError, KeyError) as exc:
                    logger.warning("cplug_activate_failed", cplug=d.id, error_type=type(exc).__name__)
        plugin_channels.sync_all(
            self.host,
            self._all_definitions(),
            safe_mode_active=any(self.safe_mode().values()),
            supervisor=self.supervisor,
            tier0_registry=self.tier0_channels,
        )
        self.refresh_feed()

    async def _apply(self) -> None:
        why = self.safe_mode()
        if any(why.values()):
            await self.supervisor.enter_safe_mode()
            if self._mcp_health_owner is not None or self.mcp_health is not None:
                await self.mcp_health_switched(self._mcp_health_owner, False)
            registry = sidecar_registry.current()
            for d in (registry.listed() if registry is not None else ()):
                plugin_channels.unregister_plugin(d.id, host=self.host, tier0_registry=self.tier0_channels, publish=False)
            ui_slots.registry_for(self.state_dir).sync(
                self._all_definitions(),
                host=self.host,
                safe_mode_active=True,
                supervisor=self.supervisor,
            )
        else:
            self.supervisor.set_safe_mode(False)
        self.refresh_feed()

    async def set_switch(self, on: bool) -> bool:
        if not owner_switch.write(self.state_dir, on):
            return False
        if not on:
            from src.plugins.host import dev_lease  # noqa: PLC0415

            dev_lease.store_for(self.state_dir).clear_all()
        if on:
            await self.check_sandbox()
        await self._apply()
        await self.activate_enabled()
        self.host.publish(CPLUGS_TOPIC)
        return True

    async def set_safe_mode(self, on: bool) -> bool:
        if not on and self._env_safe():
            return False
        self.route_safe = on
        if on:
            from src.plugins.host import dev_lease  # noqa: PLC0415

            dev_lease.store_for(self.state_dir).clear_all()
        await self._apply()
        await self.activate_enabled()
        self.host.publish(CPLUGS_TOPIC)
        return True

    async def check_sandbox(self) -> Dict[str, Any]:
        result = await asyncio.to_thread(sandbox.probe)
        detail = result.detail or ("" if result.ok else "the sandbox did not behave")
        self.sandbox_probe = {"ok": result.ok, "detail": detail}
        if not result.ok:
            self._alert_writer()(SANDBOX_ALERT_KEY, source="cplug", severity="warn", title_key=f"{TITLE_PREFIX}sandbox.title",
                                 detail_key=f"{TITLE_PREFIX}sandbox.detail", params={"reason": detail})
        return self.sandbox_probe

    def _ledger_rows(self) -> List[Any]:
        path = db_path_for(self.state_dir)
        if not path.exists():
            return []
        conn = connect(path, create=False)
        try:
            return list(InstallLedger(conn).list())
        finally:
            conn.close()

    def installed_rows(self) -> List[Any]:
        return self._ledger_rows()

    def removed_notice(self, plugin_id: str, *, data_folder: str, sideload: bool) -> None:
        detail = "detail_sideload" if sideload else "detail_catalog"
        self._alert_writer()(f"cplug.{plugin_id}.removed", source=f"cplug.{plugin_id}", severity=ALERT_SEVERITY["removed"],
                             title_key=f"{TITLE_PREFIX}removed.title", detail_key=f"{TITLE_PREFIX}removed.{detail}",
                             params={"plugin": plugin_id, "folder": data_folder}, sticky=True, auto_resolve=False)

    def load_registry(self) -> int:
        registry = sidecar_registry.SidecarRegistry(self.state_dir, self._ledger_rows)
        count = registry.reload()
        sidecar_registry.install(registry)
        for defn in registry.listed():
            self.inspector.set_aliases(defn.id, defn.item_id, defn.install_key)
        plugin_ai.register_features(registry.listed())
        plugin_channels.sync_all(
            self.host,
            self._all_definitions(),
            safe_mode_active=any(self.safe_mode().values()),
            supervisor=self.supervisor,
            tier0_registry=self.tier0_channels,
        )
        self._aim_folder_watch()
        return count

    def reload_one(self, plugin_id: str, *, item_id: Optional[str] = None, immediate_ui: bool = False) -> Optional[Any]:
        registry = sidecar_registry.current()
        if registry is None or registry.state_dir != self.state_dir:
            self.load_registry()
            registry = sidecar_registry.current()
        if registry is None:
            return None
        target_item = item_id or f"local/{plugin_id}"
        defn = registry.reload_one(target_item)
        if defn is not None:
            self.inspector.set_aliases(defn.id, defn.item_id, defn.install_key)
            plugin_channels.sync_plugin(
                self.host,
                defn,
                safe_mode_active=any(self.safe_mode().values()),
                supervisor=self.supervisor,
                tier0_registry=self.tier0_channels,
            )
        else:
            plugin_channels.unregister_plugin(plugin_id, host=self.host, tier0_registry=self.tier0_channels)
        ui_slots.registry_for(self.state_dir).sync(
            self._all_definitions(),
            host=self.host,
            safe_mode_active=any(self.safe_mode().values()),
            supervisor=self.supervisor,
        )
        plugin_ai.register_features(registry.listed())
        for listener in list(sidecar_registry._install_listeners):
            listener()
        if immediate_ui:
            key = self._key(plugin_id)
            self.on_loop(self.host.publish, CPLUGS_TOPIC)
            self.on_loop(self.host.publish, f"cplug_ui:{key}")
        return defn

    def _aim_folder_watch(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self.folder_watch.refresh)
        except RuntimeError:
            logger.debug("cplug_folder_watch_not_aimed", reason="loop_closed")

    async def start(self) -> None:
        try:
            await asyncio.to_thread(self.load_registry)
        except (OSError, sqlite3.Error) as exc:
            logger.warning("cplug_sidecar_registry_failed", error_type=type(exc).__name__)
        try:
            reaped = await asyncio.to_thread(self.children.reap)
        except OSError as exc:
            logger.warning("cplug_orphan_reap_failed", error_type=type(exc).__name__)
        else:
            if reaped:
                logger.info("cplug_orphans_reaped", outcomes=reaped)
        await asyncio.to_thread(self.socket_manager.sweep_stale, self.state_dir)
        await self._apply()
        await prune_gone.prune_pass(self)
        await self.index.sync()
        await self.activate_enabled()
        self.plugin_bus.start()
        from src.plugins.host import sideload_routes  # noqa: PLC0415

        sideload_routes.arm_expiry(self.app, self)
        if isinstance(self.host, Host):
            from src.core.plugin_health.boot import run_boot_report  # noqa: PLC0415

            await run_boot_report(self.host, self)
        self.folder_watch.start()

    async def stop(self) -> None:
        await self.folder_watch.stop()
        await self.plugin_bus.stop()
        await self.feed_fanout.stop()
        await self.timer_scheduler.stop_all()
        if self._mcp_health_owner is not None or self.mcp_health is not None:
            await self.mcp_health_switched(self._mcp_health_owner, False)
        await self.supervisor.shutdown()
        registry = sidecar_registry.current()
        for d in (registry.listed() if registry is not None else ()):
            plugin_channels.unregister_plugin(d.id, host=self.host, tier0_registry=self.tier0_channels, publish=False)
        await self.socket_manager.stop_all()


async def boot(host: Any, app: Any, loop: Optional[asyncio.AbstractEventLoop] = None) -> SidecarRuntime:
    runtime = SidecarRuntime(host, app, loop or asyncio.get_running_loop())
    await runtime.start()
    return runtime
