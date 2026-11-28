
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Set
from urllib.parse import urlparse

import structlog

from src.core.agent_manifests import engine as harness_engine
from src.core.notifications import kind_specs
from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.kinds import registry as sender_registry
from src.core.resource_push import topics
from src.plugins.host import (
    activity_log,
    egress_log,
    fetch_proxy,
    inspector_telemetry,
    risk,
    secret_store,
    sidecar_registry,
    state as owner_state,
    tier0_channels,
    ui_slots,
)
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import guards
from src.plugins.runtime.process import REQUEST_TIMEOUT, ProcessEnded

logger = structlog.get_logger()

_SYNC_LOCK = threading.RLock()
_REGISTERED_KINDS_BY_PLUGIN: Dict[str, Set[str]] = {}
_BAD_SUPERVISOR_STATES = frozenset(
    {
        "disabled",
        "disabled (safe mode)",
        "paused",
        "killed",
        "index_expired",
        "revoked",
        "crash_loop",
        "integrity",
        "needs_approval",
        "safe_mode",
    }
)


def channel_kind_id(plugin_id: str, channel_name: str) -> str:
    return f"plugin:{plugin_id}:{channel_name}"


def _host_rules_from_channel(cfg: Mapping[str, Any]) -> kind_specs.HostRules:
    url = str(cfg.get("url") or "").strip()
    if not url:
        return kind_specs.HostRules(any_host=False)
    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None
    if not host:
        return kind_specs.HostRules(any_host=False)
    return kind_specs.HostRules(exact_hosts=(host.lower(),))


def _safe_mode_active(host: Any, safe_mode_active: Optional[bool]) -> bool:
    if safe_mode_active is not None:
        return bool(safe_mode_active)
    live = host.sidecar_runtime() if callable(getattr(host, "sidecar_runtime", None)) else None
    if live is not None and callable(getattr(live, "safe_mode", None)):
        return any(live.safe_mode().values())
    return False


def _supervisor_of(host: Any, supervisor: Any) -> Any:
    if supervisor is not None:
        return supervisor
    live = host.sidecar_runtime() if callable(getattr(host, "sidecar_runtime", None)) else None
    return getattr(live, "supervisor", None) if live is not None else None


def effective_state_allows(
    host: Any,
    d: Any,
    *,
    safe_mode_active: Optional[bool] = None,
    supervisor: Any = None,
) -> bool:
    m = d.manifest
    st = owner_state.get(host.state_dir, m)
    if not st.enabled:
        return False
    if risk.consent_owed(m.tier, m.code_digest, st.digest):
        return False
    unavailable = getattr(host, "unavailable", None)
    if isinstance(unavailable, Mapping) and d.id in unavailable:
        return False
    if isinstance(d, SidecarDefinition):
        if _safe_mode_active(host, safe_mode_active):
            return False
        sup = _supervisor_of(host, supervisor)
        if sup is not None:
            if hasattr(sup, "is_paused") and sup.is_paused(d.id):
                return False
            if sup.state(d.id) in _BAD_SUPERVISOR_STATES:
                return False
    return True


def _install_key(host: Any, plugin_id: str) -> str:
    fn = getattr(host, "install_key", None)
    if callable(fn):
        try:
            return str(fn(plugin_id))
        except (OSError, KeyError, ValueError):
            pass
    return plugin_id


def _audit_channel(
    host: Any,
    plugin_id: str,
    channel_name: str,
    *,
    status: str,
    allowed: bool,
    detail: str = "",
) -> None:
    key = _install_key(host, plugin_id)
    activity_log.ActivityLog(host.state_dir).record(
        key,
        method="channel.send",
        permission=f"channel:{channel_name}",
        target=channel_name,
        status=status,
    )
    telem = inspector_telemetry.telemetry_for(host.state_dir)
    telem.record_capability(
        plugin_id,
        permission=f"channel:{channel_name}",
        allowed=allowed,
        reason=detail,
        caller=f"channel:{channel_name}",
    )


def _failure_from_status(status: int) -> FailureClass:
    if status in (401, 403):
        return FailureClass.AUTH
    if status in (404, 410):
        return FailureClass.GONE
    if status == 429:
        return FailureClass.RATE_LIMITED
    if status >= 500:
        return FailureClass.SERVER
    return FailureClass.INVALID


_INVALID_REFUSAL_CODES = frozenset(
    {"bad_url", "bad_header", "body_not_allowed", "request_too_large", "response_too_large"}
)
_NETWORK_REFUSAL_CODES = frozenset({"upstream_error", "dns_failed"})


def _failure_from_refused(exc: Any) -> FailureClass:
    code = str(getattr(exc, "code", "") or "")
    if code == "rate_limited":
        return FailureClass.RATE_LIMITED
    if code == "timeout":
        return FailureClass.TIMEOUT
    if code in _NETWORK_REFUSAL_CODES:
        return FailureClass.NETWORK
    if code == "secret_missing":
        return FailureClass.SECRET_MISSING
    if code in _INVALID_REFUSAL_CODES:
        return FailureClass.INVALID
    return FailureClass.BLOCKED


class PluginChannelSender:

    def __init__(self, host: Any, plugin_id: str, channel_name: str, config_def: Mapping[str, Any]) -> None:
        self._host = host
        self._plugin_id = plugin_id
        self._channel_name = channel_name
        self._config_def = dict(config_def)
        self._limiter = fetch_proxy.RateLimiter()

    def _find_definition(self) -> Any:
        from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

        return sidecar_registry.find(self._plugin_id) or host_runtime.find(self._plugin_id)

    async def send(
        self,
        event: NotifyEvent,
        config: Mapping[str, Any],
        secrets: Mapping[str, Any],
    ) -> DeliveryResult:
        del secrets
        t0 = time.monotonic()
        d = self._find_definition()
        if d is None or not effective_state_allows(self._host, d):
            _audit_channel(self._host, self._plugin_id, self._channel_name, status="blocked", allowed=False, detail="plugin_disabled")
            return DeliveryResult(ok=False, failure=FailureClass.BLOCKED, detail="plugin_disabled")

        channels = getattr(d.manifest, "channels", None) or {}
        cfg = dict(channels.get(self._channel_name) or self._config_def)
        if not cfg:
            _audit_channel(self._host, self._plugin_id, self._channel_name, status="missing", allowed=False, detail="channel_missing")
            return DeliveryResult(ok=False, failure=FailureClass.INVALID, detail="channel_missing")

        has_url = bool(cfg.get("url"))
        is_runnable = isinstance(d, SidecarDefinition) and bool(getattr(d.manifest, "run_cmd", ())) and not getattr(d.manifest, "tier0", False)

        if has_url and not is_runnable:
            return await self._send_declarative(d, cfg, event, config, t0)
        if is_runnable:
            return await self._send_rpc(d, event, config, t0)
        return await self._send_declarative(d, cfg, event, config, t0)

    async def _send_declarative(
        self,
        d: Any,
        cfg: Mapping[str, Any],
        event: NotifyEvent,
        config: Mapping[str, Any],
        t0: float,
    ) -> DeliveryResult:
        if not cfg.get("url"):
            _audit_channel(self._host, self._plugin_id, self._channel_name, status="invalid", allowed=False, detail="missing_url")
            return DeliveryResult(ok=False, failure=FailureClass.INVALID, detail="missing_url")
        context: Dict[str, Any] = {
            "title": event.title,
            "body": event.details or event.title,
            "severity": event.severity,
            "project": event.project,
            "session": event.session_ref or event.session_id or "",
            "kind": event.kind,
            "type_id": event.type_id,
            "event_id": event.instance_key,
        }
        for k, v in config.items():
            if isinstance(v, (str, int, float, bool)) and k not in context:
                context[k] = v
        body_text = tier0_channels.render_template(str(cfg.get("body_template", "")), context)
        body_bytes = body_text.encode("utf-8") if body_text else None
        fetch_for = getattr(self._host, "fetch_for", None)
        proxy = fetch_for(self._plugin_id) if callable(fetch_for) else None
        if proxy is None:
            proxy = fetch_proxy.PluginFetch(
                d.manifest,
                _install_key(self._host, self._plugin_id),
                lambda: self._host._live_grants(d.manifest),
                fetch_proxy.secret_store.SecretStore(self._host.state_dir)
                if hasattr(fetch_proxy, "secret_store")
                else _secret_store(self._host.state_dir),
                egress_log.EgressLog(self._host.state_dir),
                self._limiter,
            )
        try:
            resp = await proxy.fetch(
                str(cfg.get("method", "POST")),
                str(cfg["url"]),
                headers=dict(cfg.get("headers") or {}),
                body=body_bytes,
            )
        except (fetch_proxy.FetchRefused, guards.Refused) as exc:
            _audit_channel(self._host, self._plugin_id, self._channel_name, status=exc.code, allowed=False, detail=exc.code)
            return DeliveryResult(ok=False, failure=_failure_from_refused(exc), detail=exc.code)
        except secret_store.SecretError as exc:
            _audit_channel(self._host, self._plugin_id, self._channel_name, status=exc.code, allowed=False, detail=exc.code)
            return DeliveryResult(ok=False, failure=FailureClass.KEYCHAIN_LOCKED, detail=exc.code)
        except TimeoutError:
            _audit_channel(self._host, self._plugin_id, self._channel_name, status="timeout", allowed=False, detail="timeout")
            return DeliveryResult(ok=False, failure=FailureClass.TIMEOUT, detail="timeout")
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_channel_send_failed", cplug=self._plugin_id, channel=self._channel_name, error_type=type(exc).__name__)
            _audit_channel(self._host, self._plugin_id, self._channel_name, status="error", allowed=False, detail=type(exc).__name__)
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail=type(exc).__name__)

        ok = 200 <= resp.status < 300
        _audit_channel(
            self._host,
            self._plugin_id,
            self._channel_name,
            status="ok" if ok else f"http_{resp.status}",
            allowed=ok,
            detail="" if ok else f"status_{resp.status}",
        )
        if ok:
            return DeliveryResult(ok=True, status_code=resp.status, detail=f"http {resp.status} ({int((time.monotonic() - t0) * 1000)}ms)")
        return DeliveryResult(ok=False, failure=_failure_from_status(resp.status), status_code=resp.status, detail=f"http {resp.status}")

    async def _send_rpc(
        self,
        d: SidecarDefinition,
        event: NotifyEvent,
        config: Mapping[str, Any],
        t0: float,
    ) -> DeliveryResult:
        live = self._host.sidecar_runtime() if callable(getattr(self._host, "sidecar_runtime", None)) else None
        sup = getattr(live, "supervisor", None) if live is not None else None
        if sup is None:
            _audit_channel(self._host, self._plugin_id, self._channel_name, status="unavailable", allowed=False, detail="runtime_unavailable")
            return DeliveryResult(ok=False, failure=FailureClass.BLOCKED, detail="runtime_unavailable")
        try:
            proc = await sup.ensure(d.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_channel_ensure_failed", cplug=d.id, channel=self._channel_name, error_type=type(exc).__name__)
            _audit_channel(self._host, d.id, self._channel_name, status="error", allowed=False, detail=type(exc).__name__)
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail=type(exc).__name__)
        if proc is None or bool(getattr(proc, "ended", None)):
            _audit_channel(self._host, d.id, self._channel_name, status="unavailable", allowed=False, detail="not_running")
            return DeliveryResult(ok=False, failure=FailureClass.BLOCKED, detail="not_running")
        payload = {
            "channel": self._channel_name,
            "event": {
                "type_id": event.type_id,
                "kind": event.kind,
                "title": event.title,
                "body": event.details or "",
                "severity": event.severity,
                "project": event.project,
                "session": event.session_ref or event.session_id or "",
                "ts": event.ts,
            },
            "config": dict(config),
        }
        try:
            res = await proc.request("channel.send", payload, timeout=REQUEST_TIMEOUT)
        except TimeoutError:
            _audit_channel(self._host, d.id, self._channel_name, status="timeout", allowed=False, detail="timeout")
            return DeliveryResult(ok=False, failure=FailureClass.TIMEOUT, detail="timeout")
        except (ProcessEnded, OSError, guards.Refused) as exc:
            _audit_channel(self._host, d.id, self._channel_name, status="error", allowed=False, detail=type(exc).__name__)
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001
            _audit_channel(self._host, d.id, self._channel_name, status="error", allowed=False, detail=type(exc).__name__)
            return DeliveryResult(ok=False, failure=FailureClass.NETWORK, detail=type(exc).__name__)

        if isinstance(res, Mapping):
            ok = bool(res.get("ok", True))
            status_code = res.get("status_code") if isinstance(res.get("status_code"), int) else None
            detail = str(res.get("detail") or "")
            raw_fail = res.get("failure")
            failure = None
            if not ok:
                try:
                    failure = FailureClass(str(raw_fail)) if raw_fail else FailureClass.SERVER
                except ValueError:
                    failure = FailureClass.SERVER
            _audit_channel(self._host, d.id, self._channel_name, status="ok" if ok else "failed", allowed=ok, detail=detail)
            return DeliveryResult(ok=ok, failure=failure, status_code=status_code, detail=detail or f"{int((time.monotonic() - t0) * 1000)}ms")
        _audit_channel(self._host, d.id, self._channel_name, status="ok", allowed=True)
        return DeliveryResult(ok=True, detail=f"{int((time.monotonic() - t0) * 1000)}ms")


def _secret_store(state_dir: Path) -> Any:
    from src.plugins.host import secret_store  # noqa: PLC0415

    return secret_store.SecretStore(state_dir)


def _code_root_for(d: Any) -> Optional[Path]:
    root = getattr(d, "code_root", None)
    if isinstance(root, Path):
        return root
    folder = getattr(d, "folder", None)
    if isinstance(folder, Path):
        return folder
    candidate = Path(__file__).resolve().parents[1] / d.id
    return candidate if candidate.is_dir() else None


def _sync_harnesses(host: Any, d: Any, active: bool) -> None:
    harnesses = getattr(d.manifest, "harnesses", ()) or ()
    if not active or not harnesses:
        harness_engine.unregister_plugin_manifests(d.id)
        return
    root = _code_root_for(d)
    if root is None:
        harness_engine.unregister_plugin_manifests(d.id)
        return
    resolved_root = root.resolve()
    parsed = []
    try:
        for rel in harnesses:
            hpath = root / rel
            if not hpath.is_file() or hpath.is_symlink():
                continue
            if not hpath.resolve().is_relative_to(resolved_root):
                continue
            m = harness_engine.parse_manifest(hpath.read_text(encoding="utf-8"))
            if m is not None:
                parsed.append(m)
        if parsed:
            harness_engine.register_plugin_manifests(d.id, parsed)
        else:
            harness_engine.unregister_plugin_manifests(d.id)
    except (
        OSError,
        UnicodeDecodeError,
        harness_engine.RuleFileError,
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        RecursionError,
        OverflowError,
    ) as exc:
        logger.warning("cplug_harness_register_failed", cplug=d.id, error_type=type(exc).__name__)
        harness_engine.unregister_plugin_manifests(d.id)


def _sync_channels_for_plugin(
    host: Any,
    d: Any,
    active: bool,
    tier0_registry: Optional[tier0_channels.Tier0ChannelRegistry] = None,
) -> bool:
    channels = getattr(d.manifest, "channels", None) or {}
    new_ids: Set[str] = set()
    if active and isinstance(channels, Mapping) and channels:
        if tier0_registry is not None and isinstance(d, SidecarDefinition):
            tier0_registry.register(d)
        for ch_name, cfg in channels.items():
            if not isinstance(cfg, Mapping):
                continue
            kid = channel_kind_id(d.id, str(ch_name))
            spec = kind_specs.KindSpec(
                id=kid,
                label_key=f"cplug.{d.id}.channel.{ch_name}",
                hosts=_host_rules_from_channel(cfg),
                public_fields=(),
                secret_fields=(),
                allow_private=False,
                sms_like=False,
                details_allowed=True,
                virtual=False,
                label=str(cfg.get("label") or ch_name),
                plugin_id=d.id,
            )
            kind_specs.register_kind(spec)
            sender_registry.register(kid, PluginChannelSender(host, d.id, str(ch_name), cfg))
            new_ids.add(kid)
    else:
        if tier0_registry is not None:
            tier0_registry.unregister(d.id)

    with _SYNC_LOCK:
        old_ids = set(_REGISTERED_KINDS_BY_PLUGIN.get(d.id, ()))
        for stale in old_ids - new_ids:
            kind_specs.unregister_kind(stale)
            sender_registry.unregister(stale)
        if new_ids:
            _REGISTERED_KINDS_BY_PLUGIN[d.id] = new_ids
        else:
            _REGISTERED_KINDS_BY_PLUGIN.pop(d.id, None)
    return old_ids != new_ids


def unregister_plugin(
    plugin_id: str,
    *,
    host: Any = None,
    tier0_registry: Optional[tier0_channels.Tier0ChannelRegistry] = None,
    publish: bool = True,
) -> None:
    harness_engine.unregister_plugin_manifests(plugin_id)
    if tier0_registry is not None:
        tier0_registry.unregister(plugin_id)
    removed_kinds = kind_specs.unregister_plugin_kinds(plugin_id)
    removed_senders = sender_registry.unregister_prefix(f"plugin:{plugin_id}:")
    with _SYNC_LOCK:
        had = _REGISTERED_KINDS_BY_PLUGIN.pop(plugin_id, None)
    if publish and (removed_kinds or removed_senders or had):
        pub = getattr(host, "publish", None) if host is not None else None
        if callable(pub):
            pub(topics.NOTIFICATION_SETTINGS)


def sync_plugin(
    host: Any,
    d: Any,
    *,
    safe_mode_active: Optional[bool] = None,
    supervisor: Any = None,
    tier0_registry: Optional[tier0_channels.Tier0ChannelRegistry] = None,
    publish: bool = True,
) -> None:
    active = effective_state_allows(host, d, safe_mode_active=safe_mode_active, supervisor=supervisor)
    _sync_harnesses(host, d, active)
    changed = _sync_channels_for_plugin(host, d, active, tier0_registry=tier0_registry)
    if changed and publish:
        pub = getattr(host, "publish", None)
        if callable(pub):
            pub(topics.NOTIFICATION_SETTINGS)


def sync_all(
    host: Any,
    definitions: Optional[Iterable[Any]] = None,
    *,
    safe_mode_active: Optional[bool] = None,
    supervisor: Any = None,
    tier0_registry: Optional[tier0_channels.Tier0ChannelRegistry] = None,
    publish: bool = True,
) -> None:
    from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

    defs = list(definitions) if definitions is not None else list(host_runtime.listed())
    seen_ids = {d.id for d in defs}
    any_channel_change = False
    for d in defs:
        active = effective_state_allows(host, d, safe_mode_active=safe_mode_active, supervisor=supervisor)
        _sync_harnesses(host, d, active)
        if _sync_channels_for_plugin(host, d, active, tier0_registry=tier0_registry):
            any_channel_change = True

    with _SYNC_LOCK:
        gone_ids = [pid for pid in list(_REGISTERED_KINDS_BY_PLUGIN) if pid not in seen_ids]
    for pid in gone_ids:
        unregister_plugin(pid, host=host, tier0_registry=tier0_registry, publish=False)
        any_channel_change = True

    ui_slots.registry_for(host.state_dir).sync(
        defs,
        host=host,
        safe_mode_active=_safe_mode_active(host, safe_mode_active),
        supervisor=_supervisor_of(host, supervisor),
    )

    if any_channel_change and publish:
        pub = getattr(host, "publish", None)
        if callable(pub):
            pub(topics.NOTIFICATION_SETTINGS)
