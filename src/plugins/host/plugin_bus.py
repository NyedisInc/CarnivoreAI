
from __future__ import annotations

import asyncio
import contextvars
import json
import re
import secrets
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.session_change_notice import STATUS_NOTICE_KEYS
from src.models.websocket import WSMessageType
from src.plugins.host import risk, sidecar_registry, state as owner_state
from src.plugins.runtime import frames, guards, sandbox
from src.plugins.runtime.dispatch import _BUS_CALL_TOKEN, PluginContext, _Window
from src.plugins.runtime.process import ProcessEnded, REQUEST_TIMEOUT
from src.plugins.sdk.schema_check import SchemaError, SchemaSet

logger = structlog.get_logger()

MAX_SERVICE_RESULT_BYTES = 256 * 1024
MAX_BUS_CALL_DEPTH = 4
PROVIDER_CALLS_PER_SECOND = 60
_LIVE_STATES = frozenset({"running", "idle"})
_BUS_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar("cplug_bus_depth", default=0)


class PluginBus:

    def __init__(
        self,
        *,
        host: Any,
        state_dir: Callable[[], Path],
        supervisor_getter: Callable[[], Any],
        safe_mode_getter: Callable[[], Mapping[str, bool]],
        on_loop: Callable[..., None],
        definitions_getter: Optional[Callable[[], Sequence[Any]]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._host = host
        self._state_dir = state_dir
        self._supervisor_getter = supervisor_getter
        self._safe_mode_getter = safe_mode_getter
        self._on_loop = on_loop
        self._definitions_getter = definitions_getter
        self._clock = clock
        self._provider_windows: Dict[str, _Window] = {}
        self._inflight_calls: Dict[str, Tuple[str, int]] = {}
        self._inflight_by_provider: Dict[str, Dict[str, int]] = {}
        self._seq: Dict[Tuple[str, str], int] = {}
        self._removers: List[Callable[[], None]] = []
        self._tasks: Set[asyncio.Task[Any]] = set()
        self._pending_store: Optional[Any] = None
        self._pending_cb: Optional[Callable[[], None]] = None
        self._pending_seen: Dict[str, str] = {}
        self._started = False
        self._stopped = False

    def _definitions(self) -> Sequence[Any]:
        if self._definitions_getter is not None:
            return self._definitions_getter()
        reg = sidecar_registry.current()
        return reg.listed() if reg is not None else ()

    def _is_enabled(self, d: Any) -> bool:
        if sidecar_registry.find(d.id) is not None and callable(getattr(self._host, "enabled", None)):
            return bool(self._host.enabled(d.id))
        if type(self._host).__name__ != "Host" and callable(getattr(self._host, "enabled", None)):
            return bool(self._host.enabled(d.id))
        return owner_state.get(self._state_dir(), d.manifest).enabled

    def _live_grants(self, manifest: Any) -> frozenset[str]:
        if callable(getattr(self._host, "_live_grants", None)):
            if sidecar_registry.find(manifest.id) is not None or type(self._host).__name__ != "Host":
                return frozenset(self._host._live_grants(manifest))
        st = owner_state.get(self._state_dir(), manifest)
        if not st.enabled or risk.consent_owed(manifest.tier, manifest.code_digest, st.digest):
            return frozenset()
        return frozenset(st.grants)

    def _inflight_depth_for(self, plugin_id: str) -> int:
        entries = self._inflight_by_provider.get(plugin_id)
        return max(entries.values()) if entries else 0

    def _next_seq(self, source_id: str, event: str) -> int:
        key = (source_id, event)
        nxt = self._seq.get(key, 0) + 1
        self._seq[key] = nxt
        return nxt

    def _find_provider(self, service: str, method: str) -> Tuple[Any, Mapping[str, Any]]:
        candidates: List[Tuple[Any, Mapping[str, Any]]] = []
        for d in self._definitions():
            provides = getattr(d.manifest, "services_provides", ()) or ()
            for entry in provides:
                if isinstance(entry, Mapping) and entry.get("name") == service:
                    candidates.append((d, entry))
        if not candidates:
            raise guards.Refused("service_unavailable", "no_provider", {"service": service, "reason": "no_provider"})
        enabled = [(d, entry) for d, entry in candidates if self._is_enabled(d)]
        if not enabled:
            raise guards.Refused("service_unavailable", "provider_disabled", {"service": service, "reason": "provider_disabled"})
        for d, entry in enabled:
            methods = entry.get("methods") or ()
            if method in methods:
                return d, entry
        raise guards.Refused("invalid_params", "method_not_declared", {"service": service, "method": method})

    async def call_service(self, ctx: PluginContext, service: str, method: str, args: Dict[str, Any]) -> Dict[str, Any]:
        inbound_token = _BUS_CALL_TOKEN.get()
        if inbound_token is not None:
            entry_tok = self._inflight_calls.get(inbound_token)
            if entry_tok is None or entry_tok[0] != ctx.plugin_id:
                raise guards.Refused("permission_denied", "invalid_bus_token", {"service": service})
            caller_depth = entry_tok[1]
        elif _BUS_DEPTH.get() > 0:
            caller_depth = _BUS_DEPTH.get()
        else:
            caller_depth = self._inflight_depth_for(ctx.plugin_id)
        if caller_depth >= MAX_BUS_CALL_DEPTH:
            raise guards.Refused("rate_limited", "bus_depth_exceeded", {"service": service, "depth": caller_depth})

        defn, entry = self._find_provider(service, method)
        schemas = entry.get("schemas")
        if isinstance(schemas, Mapping) and method in schemas and isinstance(schemas[method], Mapping):
            try:
                schema_set = SchemaSet({"args": dict(schemas[method])})
                schema_problems = schema_set.check_schemas(allow_external_refs=False)
                if schema_problems:
                    raise SchemaError("; ".join(schema_problems[:3]))
                errors = schema_set.validate("args", args)
            except (SchemaError, KeyError, TypeError, ValueError, re.error, RecursionError) as exc:
                raise guards.Refused(
                    "invalid_params",
                    "invalid_service_schema",
                    {"service": service, "method": method, "reason": "invalid_service_schema"},
                ) from exc
            if errors:
                raise guards.Refused(
                    "invalid_params",
                    "schema_validation_failed",
                    {"service": service, "method": method, "errors": errors[:5]},
                )

        if any(self._safe_mode_getter().values()):
            raise guards.Refused("service_unavailable", "safe_mode", {"service": service, "reason": "safe_mode"})
        if getattr(defn.manifest, "tier0", False):
            raise guards.Refused("service_unavailable", "tier0_provider", {"service": service, "reason": "tier0_provider"})

        st = owner_state.get(self._state_dir(), defn.manifest)
        if risk.consent_owed(defn.manifest.tier, defn.manifest.code_digest, st.digest):
            raise guards.Refused(
                "service_unavailable",
                "provider_needs_approval",
                {"service": service, "provider": defn.id, "reason": "provider_needs_approval"},
            )

        sup = self._supervisor_getter()
        if sup is None:
            raise guards.Refused("service_unavailable", "supervisor_unavailable", {"service": service, "reason": "supervisor_unavailable"})
        if sup.is_paused(defn.id):
            raise guards.Refused("service_unavailable", "provider_paused", {"service": service, "provider": defn.id, "reason": "provider_paused"})
        pstate = sup.state(defn.id)
        if pstate == "backing_off":
            raise guards.Refused("service_unavailable", "provider_restarting", {"service": service, "provider": defn.id, "reason": "provider_restarting"})
        if pstate not in _LIVE_STATES:
            raise guards.Refused("service_unavailable", f"provider_{pstate}", {"service": service, "provider": defn.id, "reason": f"provider_{pstate}"})

        try:
            proc = await sup.ensure(defn.id)
        except sandbox.SandboxUnavailable as exc:
            raise guards.Refused("service_unavailable", "sandbox_unavailable", {"service": service, "provider": defn.id, "reason": "sandbox_unavailable"}) from exc
        if proc is None or proc.ended:
            raise guards.Refused("service_unavailable", "provider_stopped", {"service": service, "provider": defn.id, "reason": "provider_stopped"})

        win = self._provider_windows.setdefault(defn.id, _Window(PROVIDER_CALLS_PER_SECOND, 1.0, self._clock))
        if not win.allow():
            raise guards.Refused("rate_limited", "provider_rate_limited", {"service": service, "provider": defn.id})

        next_depth = caller_depth + 1
        call_token = secrets.token_urlsafe(16)
        depth_token = _BUS_DEPTH.set(next_depth)
        bus_tok_reset = _BUS_CALL_TOKEN.set(None)
        self._inflight_calls[call_token] = (defn.id, next_depth)
        by_provider = self._inflight_by_provider.setdefault(defn.id, {})
        by_provider[call_token] = next_depth
        try:
            res = await proc.request(
                "service.call",
                {"service": service, "method": method, "args": args, "_bus_token": call_token},
                timeout=REQUEST_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            raise guards.Refused("timeout", "service_timeout", {"service": service, "method": method}) from exc
        except ProcessEnded as exc:
            msg_low = (getattr(exc, "message", "") or "").strip().lower()
            is_method_missing = (
                not msg_low
                or msg_low in ("method_not_found", "method not found", "provider_method_missing")
                or msg_low.startswith(("unknown service method:", "unknown method:", "method not found:"))
            )
            if exc.reason == "plugin_error" and exc.code == frames.METHOD_NOT_FOUND and is_method_missing:
                raise guards.Refused(
                    "service_unavailable",
                    "provider_method_missing",
                    {"service": service, "method": method, "provider": defn.id, "reason": "provider_method_missing"},
                ) from exc
            if exc.reason == "plugin_error":
                raise guards.Refused("unavailable", "provider_error", {"service": service, "method": method}) from exc
            raise guards.Refused(
                "service_unavailable",
                "provider_stopped",
                {"service": service, "provider": defn.id, "reason": exc.reason},
            ) from exc
        except frames.FrameViolation as exc:
            raise guards.Refused("unavailable", "provider_protocol_error", {"service": service}) from exc
        finally:
            self._inflight_calls.pop(call_token, None)
            prov_map = self._inflight_by_provider.get(defn.id)
            if prov_map is not None:
                prov_map.pop(call_token, None)
                if not prov_map:
                    self._inflight_by_provider.pop(defn.id, None)
            _BUS_CALL_TOKEN.reset(bus_tok_reset)
            _BUS_DEPTH.reset(depth_token)

        if not isinstance(res, Mapping):
            raise guards.Refused("unavailable", "invalid_provider_response", {"service": service, "method": method})
        try:
            encoded = json.dumps(dict(res), allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise guards.Refused("unavailable", "invalid_provider_response", {"service": service, "method": method}) from exc
        if len(encoded) > MAX_SERVICE_RESULT_BYTES:
            raise guards.Refused("too_large", "service_result_too_large", {"service": service, "method": method})

        logger.info("cplug_service_call", caller=ctx.plugin_id, provider=defn.id, service=service, method=method)
        return dict(res)

    async def _deliver_bus_event(self, source_id: str, event: str, payload: Dict[str, Any]) -> int:
        if self._stopped or any(self._safe_mode_getter().values()):
            return 0
        sup = self._supervisor_getter()
        if sup is None:
            return 0
        seq = self._next_seq(source_id, event)
        delivered = 0
        envelope = {"event": event, "source": source_id, "data": payload}
        for d in self._definitions():
            if not self._is_enabled(d) or getattr(d.manifest, "tier0", False):
                continue
            subs = getattr(d.manifest, "subscriptions", ()) or ()
            if event not in subs:
                continue
            st = owner_state.get(self._state_dir(), d.manifest)
            if risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest):
                continue
            if f"events:{event}" not in self._live_grants(d.manifest):
                continue
            if sup.is_paused(d.id) or sup.state(d.id) not in _LIVE_STATES:
                continue
            try:
                ok = await sup.deliver_event(d.id, event, seq, envelope)
            except (ProcessEnded, asyncio.TimeoutError, sandbox.SandboxUnavailable, OSError) as exc:
                logger.warning("cplug_bus_event_deliver_failed", cplug=d.id, event=event, error_type=type(exc).__name__)
                continue
            if ok:
                delivered += 1
        return delivered

    async def emit_plugin_event(self, ctx: PluginContext, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        delivered = await self._deliver_bus_event(ctx.plugin_id, event, payload)
        return {"event": event, "delivered": delivered}

    async def emit_core_event(self, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        delivered = await self._deliver_bus_event("core", event, payload)
        return {"event": event, "delivered": delivered}

    def _spawn_emit_task(self, event: str, payload: Dict[str, Any]) -> None:
        if self._stopped:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.emit_core_event(event, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _schedule_core_event(self, event: str, payload: Dict[str, Any]) -> None:
        if self._stopped:
            return
        try:
            self._on_loop(self._spawn_emit_task, event, payload)
        except RuntimeError:
            return

    async def _on_session_event(self, ev: Any) -> None:
        if self._stopped:
            return
        kind = getattr(ev, "kind", "")
        data: Dict[str, Any] = {
            "tmux_name": getattr(ev, "tmux_name", ""),
            "reason": getattr(ev, "reason", ""),
            "session_row_id": getattr(ev, "session_row_id", None),
            "session_uuid": getattr(ev, "session_uuid", None),
            "ts": getattr(ev, "ts", 0.0),
        }
        if kind == "started":
            data.update({
                "display_name": getattr(ev, "display_name", ""),
                "project": getattr(ev, "project", ""),
                "agent_family": getattr(ev, "agent_family", ""),
                "agent_type": getattr(ev, "agent_type", ""),
            })
            await self.emit_core_event("session.started", data)
        elif kind == "renamed":
            data["old_name"] = getattr(ev, "old_name", "")
            await self.emit_core_event("session.renamed", data)
        elif kind == "ended":
            await self.emit_core_event("session.ended", data)
            if data["reason"] == "stopped":
                await self.emit_core_event("session.died", data)

    def _on_notice_frame(self, frame: Dict[str, Any]) -> None:
        if self._stopped or not isinstance(frame, dict):
            return
        ftype = frame.get("type")
        if ftype == WSMessageType.SESSION_STATUS_CHANGED:
            data = {
                k: frame[k]
                for k in STATUS_NOTICE_KEYS
                if k in frame and frame[k] is not None
            }
            self._schedule_core_event("session.status_changed", data)
            status = frame.get("activity_status")
            if status == "idle":
                self._schedule_core_event("session.idle", data)
            elif status == "dead":
                self._schedule_core_event("session.died", data)
        elif ftype == WSMessageType.SESSIONS_CHANGED:
            reason = str(frame.get("reason") or "")
            data = {k: frame[k] for k in ("session_id", "tmux_session", "reason") if k in frame and frame[k] is not None}
            if reason == "slept":
                self._schedule_core_event("session.slept", data)
            elif reason == "created":
                self._schedule_core_event("session.created", data)
            elif reason == "destroyed":
                self._schedule_core_event("session.destroyed", data)
            elif reason:
                self._schedule_core_event("session.changed", data)

    def _snapshot_pending(self, store: Any) -> List[Dict[str, Any]]:
        pending_rows = store.list() if callable(getattr(store, "list", None)) else []
        decided_rows = store.decided() if callable(getattr(store, "decided", None)) else []
        return [r for r in (*pending_rows, *decided_rows) if isinstance(r, Mapping) and "id" in r]

    def _on_pending_changed(self) -> None:
        if self._stopped or self._pending_store is None:
            return
        rows = self._snapshot_pending(self._pending_store)
        live_ids: Set[str] = set()
        for row in rows:
            aid = str(row["id"])
            live_ids.add(aid)
            status = str(row.get("status") or "")
            if self._pending_seen.get(aid) == status:
                continue
            self._pending_seen[aid] = status
            ev_map = {
                "pending": "approval.requested",
                "approved": "approval.approved",
                "denied": "approval.denied",
                "refused": "approval.refused",
                "withdrawn": "approval.withdrawn",
            }
            ev_name = ev_map.get(status)
            if ev_name is None:
                continue
            payload = {
                "id": aid,
                "status": status,
                "action": str(row.get("action") or ""),
                "target_session_id": str(row.get("target_session_id") or ""),
                "caller_session_id": str(row.get("caller_session_id") or ""),
            }
            self._schedule_core_event(ev_name, payload)
        self._pending_seen = {k: v for k, v in self._pending_seen.items() if k in live_ids}

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stopped = False

        from src.core import resource_push, session_change_notice  # noqa: PLC0415
        from src.core.mcp import pending  # noqa: PLC0415
        from src.core.resource_push import topics  # noqa: PLC0415
        from src.core.sessions import session_events  # noqa: PLC0415

        self._removers.append(session_events.subscribe(self._on_session_event))

        session_change_notice.add_frame_listener(self._on_notice_frame)
        self._removers.append(lambda: session_change_notice.remove_frame_listener(self._on_notice_frame))

        store = pending.get_store()
        self._pending_store = store
        self._pending_seen = {str(r["id"]): str(r.get("status") or "") for r in self._snapshot_pending(store)}
        self._pending_cb = self._on_pending_changed
        store.subscribe(self._pending_cb)

        def _drop_pending() -> None:
            subs = getattr(store, "_subscribers", None)
            if isinstance(subs, list) and self._pending_cb in subs:
                subs.remove(self._pending_cb)

        self._removers.append(_drop_pending)

        self._removers.append(
            resource_push.add_family_listener(
                topics.GIT_STATUS,
                lambda named: self._schedule_core_event("git.status_changed", {"topics": list(named)}),
            )
        )
        self._removers.append(
            resource_push.add_family_listener(
                topics.CHECKPOINTS,
                lambda named: self._schedule_core_event("git.checkpoint", {"topics": list(named)}),
            )
        )
        for task_family in ("cplug.huddle.list", "cplug.taskmanager.list"):
            self._removers.append(
                resource_push.add_family_listener(
                    task_family,
                    lambda named, fam=task_family: self._schedule_core_event("task.updated", {"family": fam, "topics": list(named)}),
                )
            )

    async def stop(self) -> None:
        self._stopped = True
        self._started = False
        removers = list(self._removers)
        self._removers.clear()
        for remove in removers:
            try:
                remove()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cplug_bus_listener_remove_failed", error_type=type(exc).__name__)
        self._pending_store = None
        self._pending_cb = None
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
