
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.db import connect, db_path_for
from src.core.skills.ledger import InstallLedger
from src.cplugs.host import activity_log, capabilities, dependencies, owner_switch, sidecar_index, sidecar_registry
from src.cplugs.host.mcp_health_port import PLUGIN_ID as MCP_HEALTH_ID, HostMcpHealth
from src.cplugs.host.runtime import CPLUGS_TOPIC
from src.cplugs.runtime import guards, sandbox
from src.cplugs.runtime.children import ChildLedger
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.runtime.supervisor import Supervisor, safe_mode_from_env

logger = structlog.get_logger()

ALERT_SEVERITY = {"crash_loop": "error", "revoked": "error", "integrity": "error", "index_expired": "warn", "safe_mode": "warn"}
TITLE_PREFIX = "app_alert.cplug_runtime."
SANDBOX_ALERT_KEY = "cplug.sandbox"
UI_INVALIDATE_INTERVAL = 0.5


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
        self.dispatcher = HostDispatcher(self._services(), self.tokens)
        self.supervisor = Supervisor(self.state_dir, app_version if app_version is not None else (dependencies.app_version() or "0"),
                                     self.dispatcher, self._supervisor_alert, self.effects.cancel, self._record_activity,
                                     safe_mode=True, children=self.children)
        self.supervisor.on_stopped = lambda plugin_id: self.mcp_health_switched(plugin_id, False)
        self.index = sidecar_index.IndexAdapter(self, self._catalog_cache)
        self.mcp_health: Optional[HostMcpHealth] = None


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
        self._activity.record(self._key(plugin), method=str(entry.get("method", "")), permission="", target=str(entry.get("detail", "")),
                              status=str(entry.get("outcome", "")), hot=running)

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

        def publish_topic(topic: str, _key: Optional[str]) -> None:
            self.on_loop(self.host.publish, f"cplug_topic:{self._key(topic.split('.')[1])}")

        def invalidate_ui(plugin_id: str, surface: Optional[str]) -> None:
            if plugin_id == MCP_HEALTH_ID and surface in (None, "status_source") and self.mcp_health is not None:
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

        return HostServices(activity=self._record_activity, list_sessions=list_sessions, get_session=get_session, toast=toast,
                            alert=self._plugin_alert, publish_topic=publish_topic, invalidate_ui=invalidate_ui,
                            process_snapshot=process_snapshot, mcp_config=mcp_config, mcp_links=mcp_links)


    async def _render_mcp_status(self) -> Optional[Dict[str, Any]]:
        """The mcphealth sidecar's validated ``status_source`` document, or None when it is not installed. Raises RuntimeError on a failed render."""
        from src.cplugs.host import sidecar_ui, ui_doc  # noqa: PLC0415

        d = sidecar_registry.find(MCP_HEALTH_ID)
        proc = await self.supervisor.ensure(MCP_HEALTH_ID)
        if d is None or proc is None:
            return None
        try:
            return ui_doc.validate(await sidecar_ui._render(proc, "status_source", {}), routes=d.manifest.routes,
                                   tools=[t.get("name") for t in d.manifest.tools if isinstance(t, dict)])
        except ui_doc.UiDocError as exc:
            raise RuntimeError(exc.code) from exc

    async def mcp_health_switched(self, plugin_id: str, enabled: bool) -> None:
        if plugin_id != MCP_HEALTH_ID:
            return
        if enabled and self.mcp_health is None:
            self.mcp_health = HostMcpHealth(lambda family, seq, payload: self.supervisor.deliver_event(MCP_HEALTH_ID, family, seq, payload),
                                            self._render_mcp_status)
            self.mcp_health.start()
        elif not enabled and self.mcp_health is not None:
            port, self.mcp_health = self.mcp_health, None
            await port.stop()


    def safe_mode(self) -> Dict[str, bool]:
        return {"env": self._env_safe(), "owner": self.route_safe, "off": not owner_switch.read(self.state_dir)}

    def status(self) -> Dict[str, Any]:
        """What the plugins page shows. Output: {enabled, safe_mode: {env, owner, active}, sandbox: {ok, detail} | None}."""
        why = self.safe_mode()
        return {"enabled": not why["off"], "safe_mode": {"env": why["env"], "owner": why["owner"], "active": why["env"] or why["owner"]},
                "sandbox": self.sandbox_probe}

    async def activate_enabled(self) -> None:
        if any(self.safe_mode().values()):
            return
        registry = sidecar_registry.current()
        wanted = [d for d in (registry.listed() if registry is not None else []) if self.host.enabled(d.id)]
        if not wanted:
            return
        await self.index.ensure()
        for d in wanted:
            try:
                await self.supervisor.activate(self.host.sidecar_spec(d))
                await self.mcp_health_switched(d.id, True)
            except (sandbox.SandboxUnavailable, OSError, ValueError, KeyError) as exc:
                logger.warning("cplug_activate_failed", cplug=d.id, error_type=type(exc).__name__)

    async def _apply(self) -> None:
        why = self.safe_mode()
        if any(why.values()):
            await self.supervisor.enter_safe_mode()
            await self.mcp_health_switched(MCP_HEALTH_ID, False)
        else:
            self.supervisor.set_safe_mode(False)

    async def set_switch(self, on: bool) -> bool:
        """Store and apply the master switch; turning on probes the sandbox. Output: False when the file could not be written."""
        if not owner_switch.write(self.state_dir, on):
            return False
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
        """Every install-ledger row, read on a connection of this thread. Blocking. Output: list; empty when the database does not exist yet."""
        path = db_path_for(self.state_dir)
        if not path.exists():
            return []
        conn = connect(path, create=False)
        try:
            return list(InstallLedger(conn).list())
        finally:
            conn.close()

    def load_registry(self) -> int:
        registry = sidecar_registry.SidecarRegistry(self.state_dir, self._ledger_rows)
        count = registry.reload()
        sidecar_registry.install(registry)
        return count

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
        await self._apply()
        await self.index.sync()
        await self.activate_enabled()
        from src.cplugs.host import sideload_routes  # noqa: PLC0415

        sideload_routes.arm_expiry(self.app, self)

    async def stop(self) -> None:
        await self.mcp_health_switched(MCP_HEALTH_ID, False)
        await self.supervisor.shutdown()


async def boot(host: Any, app: Any, loop: Optional[asyncio.AbstractEventLoop] = None) -> SidecarRuntime:
    runtime = SidecarRuntime(host, app, loop or asyncio.get_running_loop())
    await runtime.start()
    return runtime
