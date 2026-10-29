
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

import structlog
from fastapi import HTTPException, Request

from src.cplugs.host import activity_log, activity_reader, ai_budget, audit, capabilities, risk, egress_log, fetch_proxy, plugin_ai, secret_store, session_actions, state as owner_state, system_lifecycle
from src.cplugs.host import default_roots, identity, sidecar_registry, sidecar_spec
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.host.legacy_move import move_legacy_state
from src.cplugs.sdk.ai_features import feature_id, permission_name
from src.cplugs.sdk.context import CplugContext
from src.cplugs.sdk.definition import GATES, CplugDefinition
from src.cplugs.sdk.manifest import TIERS
from src.core.deepsearch import fallback_hook
from src.cplugs.sdk import settings_aliases, sidecar
from src.cplugs.sdk.routing import router_prefix
from src.cplugs.sdk.storage import CoreStorageSpec, CplugSchemaError, CplugStorage
from src.cplugs.host import developer_mode
from src.core.catalog import first_party_listing

logger = structlog.get_logger()

CPLUGS_TOPIC = "cplugs"
HOOK_TIMEOUT_S = 5.0
_UNAUDITED = frozenset({"work"})
_AUDIT_PERMISSION: Dict[str, Any] = {
    "projects": "sessions.read", "activity": "activity.read",
    "swarm": "swarm", "work": "work", "toast": "notify", "toast_dismiss": "notify", "alert": "notify", "alert_resolve": "notify", "ai": "ai_features",
    "http": "network_hosts",
}

_definitions: Optional[Tuple[CplugDefinition, ...]] = None
_host: Optional["Host"] = None


class RegistryError(Exception):
    pass


def check_definitions(defs: Tuple[CplugDefinition, ...]) -> None:
    seen: Dict[str, CplugDefinition] = {}
    legacy_owner: Dict[str, str] = {}
    tool_owner: Dict[str, str] = {}
    for d in defs:
        m = d.manifest
        if m.id in seen:
            raise RegistryError(f"two plugins use the id {m.id}")
        seen[m.id] = d
        for tool in m.surfaces.mcp_tools:
            if tool in tool_owner:
                raise RegistryError(f"{m.id}: tool {tool} is already declared by {tool_owner[tool]}")
            tool_owner[tool] = m.id
        for old in m.mcp_tool_aliases:
            if old in tool_owner:
                raise RegistryError(f"{m.id}: retired tool name {old} is already declared by {tool_owner[old]}")
            tool_owner[old] = m.id
        for old in m.legacy_ids:
            if old in legacy_owner:
                raise RegistryError(f"{m.id}: retired plugin id {old} is already used")
            legacy_owner[old] = m.id
        s = m.surfaces
        if bool(d.router) != s.routes:
            raise RegistryError(f"{m.id}: surfaces.routes is {s.routes} but the definition {'has' if d.router else 'has no'} router")
        if d.router is not None and d.router.prefix != router_prefix(m.id, third_party=m.tier not in TIERS):
            raise RegistryError(f"{m.id}: the router must come from cplug_router('{m.id}') with the layout the host picks for tier {m.tier}")
        if set(d.tools) != set(s.mcp_tools):
            raise RegistryError(f"{m.id}: tools {sorted(d.tools)} differ from surfaces.mcp_tools {sorted(s.mcp_tools)}")
        for name, spec in d.tools.items():
            if spec.gate not in GATES:
                raise RegistryError(f"{m.id}: tool {name} gate {spec.gate!r} is not one of {GATES}")
        if bool(d.storage) != s.storage:
            raise RegistryError(f"{m.id}: surfaces.storage is {s.storage} but the definition {'has' if d.storage else 'has no'} storage")
        if s.feed:
            raise RegistryError(f"{m.id}: feed plugins arrive with docs/cplugs.md section 8 slice 4")
    for old, owner in legacy_owner.items():
        if old in seen:
            raise RegistryError(f"{owner}: retired plugin id {old} is also a shipped plugin")
    for d in defs:
        unknown = [r for r in d.manifest.requires if r not in seen]
        if unknown:
            raise RegistryError(f"{d.id}: requires {unknown}, which this build does not ship")


def definitions() -> Tuple[CplugDefinition, ...]:
    global _definitions
    if _definitions is None:
        from src.cplugs.registry import CPLUGS  # noqa: PLC0415

        check_definitions(tuple(CPLUGS))
        sidecar.audit_ship_list((d.manifest for d in CPLUGS), Path(__file__).resolve().parents[1])
        plugin_ai.register_features(CPLUGS)
        _definitions = tuple(CPLUGS)
    return _definitions


def hidden(d: CplugDefinition) -> bool:
    return d.manifest.tier == "dev" and not developer_mode.is_on()


def listed() -> Tuple[Any, ...]:
    return tuple(d for d in definitions() if not hidden(d)) + sidecar_registry.listed()


def find(cplug_id: str) -> Optional[Any]:
    return next((d for d in definitions() if d.id == cplug_id), None) or sidecar_registry.find(cplug_id)


def legacy_target(cplug_id: str) -> Optional[CplugDefinition]:
    return next((d for d in definitions() if cplug_id in d.manifest.legacy_ids), None)


def topic_families() -> Tuple[str, ...]:
    return (CPLUGS_TOPIC,) + tuple(f"cplug.{d.id}.{n}" for d in definitions() for n in d.manifest.surfaces.topics)


def settings_defaults(schema: Mapping[str, Any]) -> Dict[str, Any]:
    fields = schema.get("fields") if isinstance(schema, Mapping) else None
    return {k: f.get("default") for k, f in (fields or {}).items() if isinstance(f, Mapping)}


_RATE = fetch_proxy.RateLimiter()


def _publish(topic: str) -> None:
    from src.core import resource_push  # noqa: PLC0415

    resource_push.notify(topic)


def _publish_coalesced(topic: str, key: str, min_interval: float, detail: Optional[str] = None) -> None:
    from src.core import resource_push  # noqa: PLC0415

    resource_push.notify_coalesced(topic, key, min_interval, detail)


def _push_frame(frame: Dict[str, Any]) -> bool:
    from src.core import resource_push  # noqa: PLC0415

    return resource_push.publish_frame(frame)


def _follow_family(family: str, listener: Callable[[List[str]], None]) -> Callable[[], None]:
    from src.core import resource_push  # noqa: PLC0415

    return resource_push.add_family_listener(family, listener)


def install_key_for(state_dir: Path, cplug_id: str) -> str:
    compiled = any(d.id == cplug_id for d in definitions())
    return secret_store.network_key(cplug_id, None if compiled else state_dir)


class Host:

    def __init__(self, state_dir: Path, app: Any = None, publish: Callable[[str], None] = _publish,
                 publish_coalesced: Callable[..., None] = _publish_coalesced) -> None:
        self.state_dir = Path(state_dir)
        self.app = app
        self.publish = publish
        self.publish_coalesced = publish_coalesced
        self.unavailable: Dict[str, str] = {}
        self._started: set = set()
        self.ai_gateway: Optional[Callable[[], Any]] = None

    def state(self, cplug_id: str) -> owner_state.CplugState:
        d = find(cplug_id)
        if d is None:
            raise KeyError(cplug_id)
        return owner_state.get(self.state_dir, d.manifest)

    def enabled(self, cplug_id: str) -> bool:
        d = find(cplug_id)
        return d is not None and owner_state.get(self.state_dir, d.manifest).enabled

    def granted(self, cplug_id: str, permission: str) -> bool:
        d = find(cplug_id)
        return d is not None and permission in self._live_grants(d.manifest)

    def folder(self, cplug_id: str) -> Path:
        d = find(cplug_id)
        if isinstance(d, SidecarDefinition):
            return d.folder
        if d is None:
            record = identity.lookup(self.state_dir, cplug_id)
            if record is not None:
                return identity.data_dir(self.state_dir, record.uuid)
        return self.state_dir / owner_state.STATE_DIR_NAME / cplug_id

    def sidecar_runtime(self) -> Optional[Any]:
        return getattr(getattr(self.app, "state", None), "sidecar_runtime", None)

    def install_key(self, cplug_id: str) -> str:
        return install_key_for(self.state_dir, cplug_id)

    def storage(self, cplug_id: str) -> CplugStorage:
        d = find(cplug_id)
        if d is not None and isinstance(d.storage, CoreStorageSpec):
            return d.storage.bind(self.folder(cplug_id), self.state_dir)
        return CplugStorage(self.folder(cplug_id), d.storage if d else None, self.state_dir)

    def notify(self, cplug_id: str, name: str, key: Optional[str] = None) -> None:
        family = self.family(cplug_id, name)
        self.publish(family if key is None else f"{family}:{key}")

    @staticmethod
    def family(cplug_id: str, name: str) -> str:
        d = find(cplug_id)
        if d is None or name not in d.manifest.surfaces.topics:
            raise ValueError(f"plugin {cplug_id} declares no topic {name}")
        return f"cplug.{cplug_id}.{name}"

    def push_data(self, cplug_id: str, name: str, data: Dict[str, Any]) -> bool:
        from src.models.websocket import WSMessageType  # noqa: PLC0415

        return _push_frame({"type": WSMessageType.CPLUG_DATA.value, "topic": self.family(cplug_id, name), "data": data})

    def follow(self, cplug_id: str, name: str, listener: Callable[[List[str]], None]) -> Callable[[], None]:
        return _follow_family(self.family(cplug_id, name), listener)

    def _live_grants(self, manifest: Any) -> FrozenSet[str]:
        st = owner_state.get(self.state_dir, manifest)
        return self._effective_grants(manifest, st) if st.enabled else frozenset()

    def _grants_now(self, manifest: Any) -> FrozenSet[str]:
        return self._effective_grants(manifest, owner_state.get(self.state_dir, manifest))

    @staticmethod
    def _effective_grants(manifest: Any, st: owner_state.CplugState) -> FrozenSet[str]:
        if risk.consent_owed(manifest.tier, manifest.code_digest, st.digest):
            return frozenset()
        return frozenset(st.grants)

    def context(self, cplug_id: str, *, request: Optional[Request] = None,
                infos: Optional[capabilities.Infos] = None, app_state: Any = None, background: bool = False,
                at_boot: bool = False) -> CplugContext:
        d = find(cplug_id)
        if d is None:
            raise KeyError(cplug_id)
        st = owner_state.get(self.state_dir, d.manifest)
        live = lambda: self._grants_now(d.manifest)  # noqa: E731
        grants = live()
        outside = risk.needs_consent(d.manifest.tier)
        if request is not None:
            app_state = request.app.state
        elif app_state is None:
            app_state = getattr(self.app, "state", None)
        if background and request is None and self.app is not None:
            request = session_actions.AppRequest(self.app)
        caps: Dict[str, Any] = {}
        reader = infos or capabilities.local_infos_from_app(app_state)
        if "sessions.read" in grants:
            if outside:
                caps["sessions"] = capabilities.RestrictedSessions(
                    reader, request, "sessions.message" in grants, may_control="sessions.control" in grants)
            else:
                caps["sessions"] = capabilities.Sessions(reader, request, "sessions.message" in grants,
                                                         may_resume="sessions.create" in grants, app_state=app_state)
            caps["projects"] = capabilities.Projects(restricted=outside)
        if "activity.read" in grants:
            caps["activity"] = activity_reader.ActivityReader(self.state_dir)
        if "swarm" in grants:
            caps["swarm"] = capabilities.swarm_capability(self.state_dir, reader, app_state)
        if "work" in grants:
            caps["work"] = capabilities.work_capability(self.state_dir)
        if "notify" in grants:
            caps["toast"] = (capabilities.toaster(cplug_id, app_state, f"{cplug_id}: ") if outside
                             else capabilities.toaster(cplug_id, app_state))
            caps["toast_dismiss"] = capabilities.toast_dismisser(cplug_id, app_state)
            caps["alert"] = capabilities.alerter(cplug_id, outside)
            caps["alert_resolve"] = capabilities.alert_resolver(cplug_id, outside)
        granted_ai = {feature_id(d.id, n): f for n, f in d.manifest.ai_features.items()
                      if permission_name(d.id, n) in grants}
        if granted_ai:
            caps["ai"] = plugin_ai.PluginAi(cplug_id, granted_ai, ai_budget.AiBudget(self.state_dir), self.ai_gateway)
        net = d.manifest.network
        key = self.install_key(cplug_id)
        if any(e.permission in grants for e in (*net.network_hosts, *net.lan_hosts)):
            caps["http"] = fetch_proxy.PluginFetch(d.manifest, key,
                                                   lambda: self._live_grants(d.manifest), secret_store.SecretStore(self.state_dir),
                                                   egress_log.EgressLog(self.state_dir), _RATE)
        log = activity_log.ActivityLog(self.state_dir)
        permissions = {**_AUDIT_PERMISSION, "sessions": audit.sessions_permission_for(outside)}
        caps = {name: cap if name in _UNAUDITED else audit.audited(cap, log, key, name, permissions[name], live) for name, cap in caps.items()}
        defaults = settings_defaults(d.manifest.settings_schema)
        aliases = d.manifest.settings_aliases
        settings_aliases.declare(aliases)
        settings = settings_aliases.merged(defaults, st.settings, aliases)
        return CplugContext(cplug_id, storage=self.storage(cplug_id), settings=settings,
                            settings_source=lambda: settings_aliases.merged(defaults, owner_state.get(self.state_dir, d.manifest).settings, aliases),
                            settings_adopter=lambda source_id, keys: self.adopt_settings(d, source_id, keys),
                            enabled_source=lambda: self.enabled(cplug_id),
                            notify=lambda name, key=None: self.notify(cplug_id, name, key),
                            push=lambda name, data: self.push_data(cplug_id, name, data),
                            follow=lambda name, listener: self.follow(cplug_id, name, listener),
                            log=structlog.get_logger().bind(cplug=cplug_id), grants=grants, capabilities=caps, at_boot=at_boot,
                            grants_source=live)

    def adopt_settings(self, d: CplugDefinition, source_id: str, keys: Tuple[str, ...]) -> Dict[str, Any]:
        source = find(source_id)
        if source is None or source_id not in d.manifest.requires:
            raise ValueError(f"{d.id} may adopt settings only from a plugin it requires, not {source_id!r}")
        saved = owner_state.get(self.state_dir, source.manifest).settings
        moved: Dict[str, Any] = {}

        def mutate(st: owner_state.CplugState) -> owner_state.CplugState:
            moved.clear()
            moved.update({k: saved[k] for k in keys if k in saved and k not in st.settings})
            return replace(st, settings={**st.settings, **moved})

        if any(k in saved and k not in owner_state.get(self.state_dir, d.manifest).settings for k in keys):
            owner_state.update(self.state_dir, d.manifest, None, mutate)
        return dict(moved)

    async def _hook(self, d: CplugDefinition, which: str, *, at_boot: bool = False) -> None:
        system = system_lifecycle.HOOKS.get(d.id)
        if which == "start":
            default_roots.fill(self.state_dir, d.manifest)
        hook = {"start": d.on_start, "stop": d.on_stop, "settings": d.on_settings}[which]
        if hook is None and (system is None or which == "settings"):
            return
        ctx = self.context(d.id, background=which != "stop", at_boot=at_boot) if hook is not None else None
        try:
            call = hook(ctx) if hook is not None else system[0 if which == "start" else 1](self.app)
            await asyncio.wait_for(call, timeout=HOOK_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            logger.error("cplug_hook_failed", cplug=d.id, hook=which, error_type=type(exc).__name__, error=str(exc)[:300], exc_info=True)
            if which == "start":
                reason = f": {str(exc)[:200]}" if isinstance(exc, CplugSchemaError) else ""
                self.unavailable[d.id] = f"start hook failed: {type(exc).__name__}{reason}"

    async def start(self) -> None:
        try:
            for d in definitions():
                if self.enabled(d.id) and d.id not in self._started:
                    self._started.add(d.id)
                    await self._hook(d, "start", at_boot=True)
        finally:
            fallback_hook.end_boot()
        logger.info("cplug_host_started", cplugs=[d.id for d in definitions()], enabled=sorted(self._started))

    async def stop(self) -> None:
        for d in definitions():
            if d.id in self._started:
                self._started.discard(d.id)
                await self._hook(d, "stop")

    async def switched(self, cplug_id: str, enabled: bool) -> None:
        d = find(cplug_id)
        if isinstance(d, SidecarDefinition):
            await self._switch_sidecar(d, enabled)
            return
        if d is None:
            return
        if d.manifest.surfaces.tabs:
            self.publish("browser_pages")
        if enabled and cplug_id not in self._started:
            self.unavailable.pop(cplug_id, None)
            self._started.add(cplug_id)
            await self._hook(d, "start")
        elif not enabled and cplug_id in self._started:
            self._started.discard(cplug_id)
            await self._hook(d, "stop")

    async def _switch_sidecar(self, d: SidecarDefinition, enabled: bool) -> None:
        live = self.sidecar_runtime()
        if live is None:
            return
        if enabled:
            await live.index.ensure()
            await live.supervisor.activate(self.sidecar_spec(d))
            await live.mcp_health_switched(d.id, not any(live.safe_mode().values()))
        else:
            await live.supervisor.disable(d.id)
            await live.mcp_health_switched(d.id, False)
            await asyncio.to_thread(live.supervisor.cancel_effects, d.id, "disabled")
            await asyncio.to_thread(live.resolve_alerts, d.id)

    async def restart_sidecar(self, d: SidecarDefinition) -> Optional[str]:
        live = self.sidecar_runtime()
        if live is None:
            return None
        await live.index.ensure()
        state = await live.supervisor.restart(self.sidecar_spec(d))
        await live.mcp_health_switched(d.id, not any(live.safe_mode().values()))
        return state

    def sidecar_spec(self, d: SidecarDefinition) -> Any:
        st = owner_state.get(self.state_dir, d.manifest)
        consented = bool(st.digest) and st.digest == d.manifest.code_digest
        owed = risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest)
        return sidecar_spec.build_spec(d, self._effective_grants(d.manifest, st), st.settings, consented, first_party_listing.pinned_key_id() or "",
                                       consent_owed=owed)

    async def settings_saved(self, cplug_id: str) -> None:
        d = find(cplug_id)
        if d is not None and d.on_settings is not None and cplug_id in self._started:
            await self._hook(d, "settings")


def install(app: Any = None, state_dir: Optional[Path] = None) -> Host:
    global _host
    if state_dir is None:
        from src.config import settings  # noqa: PLC0415

        state_dir = Path(settings.get_state_dir())
    move_legacy_state(state_dir)
    host = Host(state_dir, app)
    if app is not None:
        app.state.cplugs_host = host
    _host = host
    return host


def current() -> Host:
    return _host if _host is not None else install()


def host_for(app: Any) -> Host:
    host = getattr(getattr(app, "state", None), "cplugs_host", None)
    return host if isinstance(host, Host) else current()


def require_enabled(cplug_id: str) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        host = host_for(request.app)
        if not host.enabled(cplug_id):
            raise HTTPException(status_code=409, detail={"code": "cplug_disabled", "detail": f"the {cplug_id} plugin is off"})
        if cplug_id in host.unavailable:
            raise HTTPException(status_code=503, detail={"code": "cplug_unavailable", "detail": host.unavailable[cplug_id]})

    return dependency
