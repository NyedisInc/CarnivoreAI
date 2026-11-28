
from __future__ import annotations

import asyncio
import contextvars
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, FrozenSet, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import structlog

from src.plugins.runtime import create_params, fsguard, git_ops, guards, frames, log_redaction
from src.plugins.sdk.ai_features import AI_CAPABILITIES
from src.plugins.runtime.owner_tokens import OwnerTokens, TokenRefused
from src.plugins.runtime.storage import HostStorage, StorageRefused

logger = structlog.get_logger()

FAMILY_PER_SECOND = 20
TOAST_PER_HOUR = 6
NOISY_WINDOW_SECONDS = 60.0
MAX_OUTPUT_LINES = 500
MAX_BUS_PAYLOAD_BYTES = 64 * 1024
AI_TOP_LEVEL_KEYS = frozenset({"feature", "capability", "input"})
CONTROL_ACTIONS = frozenset({"restart", "stop", "sleep", "wake"})
_SERVICE_REF_RE = re.compile(r"^[a-z][a-z0-9_.:@-]{0,63}$")
_METHOD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,63}$")
_RESERVED_EVENT_PREFIXES = ("session.", "git.", "approval.", "task.", "feed.", "webhook.", "mcp.", "cplug.", "cplugs.", "system.", "core.")
_RESERVED_EVENT_ROOTS = frozenset({"session", "git", "approval", "task", "feed", "webhook", "mcp", "cplug", "cplugs", "system", "core"})
CODES = {"permission_denied": frames.PERMISSION_DENIED, "not_granted": frames.NOT_GRANTED, "dialog_open": frames.DIALOG_OPEN,
         "rate_limited": frames.RATE_LIMITED, "too_large": frames.TOO_LARGE, "timeout": frames.TIMEOUT,
         "disabled": frames.DISABLED, "service_unavailable": frames.DISABLED, "invalid_params": frames.INVALID_PARAMS,
         "integrity": frames.PERMISSION_DENIED, "unavailable": frames.METHOD_NOT_FOUND, "not_found": frames.INVALID_PARAMS,
         "internal_error": frames.INTERNAL_ERROR}

Async = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class PluginContext:

    plugin_id: str
    install_key: str
    data_dir: Path
    granted: FrozenSet[str]
    manifest_tools: Tuple[Mapping[str, Any], ...] = ()
    topics: FrozenSet[str] = frozenset()
    picked_folders: Tuple[Path, ...] = ()
    tier: str = "catalog"
    services_consumes: Tuple[str, ...] = ()
    events_emit: Tuple[str, ...] = ()

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


@dataclass
class HostServices:

    activity: Callable[[Dict[str, Any]], None]
    list_sessions: Optional[Async] = None
    get_session: Optional[Async] = None
    session_output: Optional[Async] = None
    permission_mode: Optional[Async] = None
    paste_line: Optional[Async] = None
    create_session: Optional[Async] = None
    control_session: Optional[Async] = None
    list_projects: Optional[Async] = None
    project_path: Optional[Callable[[int], Optional[Path]]] = None
    ledger: Optional[Async] = None
    http_fetch: Optional[Async] = None
    ai_for: Optional[Callable[[PluginContext], Any]] = None
    toast: Optional[Callable[[str, str, str], None]] = None
    alert: Optional[Callable[[str, str, str, str, Mapping[str, Any]], None]] = None
    publish_topic: Optional[Callable[[str, Optional[str]], None]] = None
    invalidate_ui: Optional[Callable[[str, Optional[str]], None]] = None
    ui_slot_publish: Optional[Async] = None
    process_snapshot: Optional[Async] = None
    mcp_config: Optional[Async] = None
    mcp_links: Optional[Async] = None
    flow_run: Optional[Async] = None
    flow_feed: Optional[Async] = None
    flow_tasks: Optional[Async] = None
    flow_run_part: Optional[Async] = None
    service_call: Optional[Async] = None
    events_emit: Optional[Async] = None


class _Window:

    def __init__(self, limit: int, seconds: float, clock: Callable[[], float]) -> None:
        self._limit, self._seconds, self._clock = limit, seconds, clock
        self._hits: Deque[float] = deque()

    def allow(self) -> bool:
        now = self._clock()
        while self._hits and now - self._hits[0] >= self._seconds:
            self._hits.popleft()
        if len(self._hits) >= self._limit:
            return False
        self._hits.append(now)
        return True


_RPC_CALLER: contextvars.ContextVar[str] = contextvars.ContextVar("cplug_rpc_caller", default="rpc")
_BUS_CALL_TOKEN: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("cplug_bus_call_token", default=None)


def _trace_target(method: str, params: Any) -> str:
    if not isinstance(params, Mapping):
        return ""
    if method == "http.fetch":
        url = params.get("url")
        if isinstance(url, str):
            return url.split("?", 1)[0][:120]
    for key in ("service", "event", "topic", "slot", "surface", "ref", "key", "project", "feature", "name", "folder"):
        val = params.get(key)
        if isinstance(val, str) and val:
            if key == "service" and isinstance(params.get("method"), str):
                return f"{val}.{params['method']}"[:120]
            return val[:120]
    return ""


def _bus_permission(method: str, params: Any) -> str:
    if not isinstance(params, Mapping):
        return ""
    if method == "service.call" and isinstance(params.get("service"), str):
        return f"services:{params['service']}"[:160]
    if method == "events.emit" and isinstance(params.get("event"), str):
        return f"events:{params['event']}"[:160]
    if method == "ui.slot.publish" and isinstance(params.get("slot"), str):
        return f"ui.slot:{params['slot']}"[:160]
    return ""


class HostDispatcher:

    def __init__(self, services: HostServices, tokens: OwnerTokens, clock: Callable[[], float] = time.monotonic,
                 home: Optional[Path] = None, trace_sink: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._svc = services
        self._tokens = tokens
        self._clock = clock
        self._home = home or Path.home()
        self._trace_sink = trace_sink
        self._windows: Dict[Tuple[str, str], _Window] = {}
        self._toast: Dict[str, _Window] = {}
        self._storage: Dict[str, HostStorage] = {}
        self._noisy: Dict[Tuple[str, str], Tuple[Optional[float], int]] = {}

    def set_trace_sink(self, trace_sink: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        self._trace_sink = trace_sink

    def _emit_trace(self, payload: Dict[str, Any]) -> None:
        if self._trace_sink is None:
            return
        try:
            self._trace_sink(payload)
        except Exception:  # noqa: BLE001
            pass

    def _record_cap(self, ctx: PluginContext, permission: str, allowed: bool, reason: str = "") -> None:
        self._emit_trace({
            "kind": "capability",
            "plugin_id": ctx.plugin_id,
            "permission": permission,
            "allowed": allowed,
            "reason": reason,
            "caller": _RPC_CALLER.get(),
        })


    def _window(self, ctx: PluginContext, family: str) -> _Window:
        return self._windows.setdefault((ctx.plugin_id, family), _Window(FAMILY_PER_SECOND, 1.0, self._clock))

    def _need(self, ctx: PluginContext, permission: str) -> None:
        if permission not in ctx.granted:
            self._record_cap(ctx, permission, False, "not_granted")
            raise guards.Refused("not_granted", permission, {"permission": permission})
        self._record_cap(ctx, permission, True, "granted")

    def _service(self, name: str) -> Async:
        found = getattr(self._svc, name)
        if found is None:
            raise guards.Refused("unavailable", name)
        return found

    def record(self, ctx: PluginContext, method: str, outcome: str, detail: str = "", *, permission: str = "") -> None:
        try:
            row: Dict[str, Any] = {"plugin": ctx.plugin_id, "method": method, "outcome": outcome, "detail": detail[:200]}
            if permission:
                row["permission"] = permission[:300]
            self._svc.activity(row)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.warning("cplug_activity_unwritten", cplug=ctx.plugin_id, error_type=type(exc).__name__)

    def _record_throttled(self, ctx: PluginContext, method: str, outcome: str) -> None:
        now, key = self._clock(), (ctx.plugin_id, outcome)
        start, count = self._noisy.get(key, (None, 0))
        if start is None or now - start >= NOISY_WINDOW_SECONDS:
            self._noisy[key] = (now, 0)
            self.record(ctx, method, outcome, f"repeats={count}" if count else "")
        else:
            self._noisy[key] = (start, count + 1)

    async def handle(self, ctx: PluginContext, method: str, params: Any, *, source: str = "rpc") -> Any:
        started = time.perf_counter()
        target = _trace_target(method, params)
        perm = _bus_permission(method, params)
        caller_token = _RPC_CALLER.set(f"{source}:{method}")
        try:
            handler = self._table().get(method)
            if handler is None:
                self._record_throttled(ctx, method, "unknown_method")
                self._emit_trace({
                    "kind": "rpc", "plugin_id": ctx.plugin_id, "source": source, "method": method,
                    "target": target, "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    "ok": False, "error_code": "unavailable", "error_message": "method not found",
                })
                raise guards.Refused("unavailable", "method not found")
            try:
                if not isinstance(params, dict):
                    raise guards.Refused("invalid_params", "params must be an object")
                if not self._window(ctx, method.split(".")[0]).allow():
                    raise guards.Refused("rate_limited", method)
                result = await handler(ctx, params)
            except guards.Refused as exc:
                if exc.code == "rate_limited":
                    self._record_throttled(ctx, method, exc.code)
                else:
                    self.record(ctx, method, exc.code, str(exc), permission=perm)
                self._emit_trace({
                    "kind": "rpc", "plugin_id": ctx.plugin_id, "source": source, "method": method,
                    "target": target, "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    "ok": False, "error_code": exc.code, "error_message": str(exc)[:160],
                })
                raise
            except StorageRefused as exc:
                self.record(ctx, method, exc.code, str(exc), permission=perm)
                self._emit_trace({
                    "kind": "rpc", "plugin_id": ctx.plugin_id, "source": source, "method": method,
                    "target": target, "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    "ok": False, "error_code": exc.code, "error_message": str(exc)[:160],
                })
                raise guards.Refused(exc.code, str(exc)) from exc
            detail = target if method in ("service.call", "events.emit") else ""
            self.record(ctx, method, "ok", detail, permission=perm)
            self._emit_trace({
                "kind": "rpc", "plugin_id": ctx.plugin_id, "source": source, "method": method,
                "target": target, "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                "ok": True, "error_code": "", "error_message": "",
            })
            return result
        finally:
            _RPC_CALLER.reset(caller_token)

    def _table(self) -> Dict[str, Callable[[PluginContext, Dict[str, Any]], Awaitable[Any]]]:
        return {
            "sessions.list": self._sessions_list, "sessions.get": self._sessions_get, "sessions.output": self._sessions_output,
            "sessions.permission_mode": self._sessions_permission_mode,
            "sessions.message": self._sessions_message, "sessions.create": self._sessions_create,
            "sessions.control": self._sessions_control, "notify.toast": self._notify_toast, "notify.alert": self._notify_alert,
            "storage.get": self._storage_get, "storage.put": self._storage_put, "storage.delete": self._storage_delete,
            "storage.list": self._storage_list, "topic.publish": self._topic_publish, "ui.invalidate": self._ui_invalidate,
            "ui.slot.publish": self._ui_slot_publish,
            "http.fetch": self._http_fetch, "ai.call": self._ai_call, "ledger.read": self._ledger_read,
            "projects.list": self._projects_list, "projects.git": self._projects_git,
            "projects.snapshot": self._projects_snapshot, "exports.write": self._exports_write, "log": self._log,
            "process.snapshot": self._process_snapshot, "mcp.config": self._mcp_config, "mcp.links": self._mcp_links,
            "flow.run": self._flow_run, "flow.run_part": self._flow_run_part, "flow.feed": self._flow_feed, "flow.tasks": self._flow_tasks,
            "service.call": self._service_call, "events.emit": self._events_emit,
        }


    async def _sessions_list(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.read")
        rows = await self._service("list_sessions")()
        return {"sessions": [guards.project_session_row(r) for r in rows if not guards.is_remote_row(r)]}

    async def _sessions_get(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.read")
        ref = guards.refuse_remote(params.get("ref"))
        row = await self._service("get_session")(ref)
        if row is not None and guards.is_remote_row(row):
            raise guards.Refused("permission_denied", "remote_ref", {"reason": "remote_ref"})
        return {"session": None if row is None else guards.project_session_row(row)}

    async def _sessions_output(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.output")
        ref = guards.refuse_remote(params.get("ref"))
        lines = params.get("lines", 100)
        if not isinstance(lines, int) or isinstance(lines, bool) or not 1 <= lines <= MAX_OUTPUT_LINES:
            raise guards.Refused("invalid_params", f"lines must be 1 to {MAX_OUTPUT_LINES}")
        return {"lines": [guards.strip_invisible(str(x)) for x in await self._service("session_output")(ref, lines)]}

    async def _sessions_permission_mode(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.read")
        ref = guards.refuse_remote(params.get("ref"))
        return {"mode": await self._service("permission_mode")(ref)}

    async def _sessions_message(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.message")
        ref = guards.refuse_remote(params.get("ref"))
        try:
            self._tokens.redeem(ctx.install_key, params.get("owner_token"), ref)
        except TokenRefused as exc:
            raise guards.Refused("permission_denied", "owner_token", {"reason": f"owner_token_{exc.code}"}) from exc
        line = guards.refuse_control_line(params.get("line"))
        row = await self._service("get_session")(ref)
        if row is None:
            raise guards.Refused("invalid_params", "no such session")
        if guards.is_remote_row(row):
            raise guards.Refused("permission_denied", "remote_ref", {"reason": "remote_ref"})
        mode = await self._service("permission_mode")(ref)
        guards.refuse_bypass_session(row.get("launched_with"), row.get("agent_wrapper_label"), mode)
        return dict(await self._service("paste_line")(ref, line))

    async def _sessions_create(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.create")
        project, prompt, family = create_params.checked(ctx.tier, params)
        return dict(await self._service("create_session")(ctx.plugin_id, project, prompt, family))

    async def _sessions_control(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.control")
        ref = guards.refuse_remote(params.get("ref"))
        action = params.get("action")
        if action not in CONTROL_ACTIONS:
            raise guards.Refused("invalid_params", "action is restart, stop, sleep or wake")
        return dict(await self._service("control_session")(ctx.plugin_id, ref, action))


    async def _notify_toast(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "notify")
        ref = guards.refuse_remote(params.get("ref"))
        title = guards.toast_title(params.get("title"))
        if not self._toast.setdefault(ctx.plugin_id, _Window(TOAST_PER_HOUR, 3600.0, self._clock)).allow():
            raise guards.Refused("rate_limited", "toasts", {"limit": f"{TOAST_PER_HOUR} an hour"})
        self._service("toast")(ctx.plugin_id, ref, title)
        return {}

    async def _notify_alert(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "notify")
        key = guards.alert_key(ctx.plugin_id, params.get("key"))
        severity, title = params.get("severity"), params.get("title")
        if severity not in guards.SEVERITIES or not isinstance(title, str) or not title.strip():
            raise guards.Refused("invalid_params", "severity and title")
        extra = params.get("params", {})
        if not isinstance(extra, dict) or len(str(extra)) > 1000:
            raise guards.Refused("invalid_params", "params")
        self._service("alert")(ctx.plugin_id, key, severity, guards.toast_title(title), extra)
        return {}

    async def _topic_publish(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        name, key = params.get("name"), params.get("key")
        if not isinstance(name, str) or name not in ctx.topics or not (key is None or isinstance(key, str)):
            raise guards.Refused("permission_denied", "undeclared topic", {"reason": "topic_not_declared"})
        self._service("publish_topic")(f"cplug.{ctx.plugin_id}.{name}", key)
        return {}

    async def _ui_invalidate(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        surface = params.get("surface")
        if surface is not None and not isinstance(surface, str):
            raise guards.Refused("invalid_params", "surface")
        self._service("invalidate_ui")(ctx.plugin_id, surface)
        return {}

    async def _ui_slot_publish(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        slot = params.get("slot")
        items = params.get("items")
        if not isinstance(slot, str) or not 1 <= len(slot.strip()) <= 80 or not isinstance(items, list):
            raise guards.Refused("invalid_params", "slot and items list are required")
        return dict(await self._service("ui_slot_publish")(ctx, slot.strip(), items))


    def storage(self, ctx: PluginContext) -> HostStorage:
        if ctx.install_key not in self._storage:
            self._storage[ctx.install_key] = HostStorage(ctx.data_dir)
        return self._storage[ctx.install_key]

    async def _storage_get(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"value": await asyncio.to_thread(self.storage(ctx).get, params.get("key"))}

    async def _storage_put(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.to_thread(self.storage(ctx).put, params.get("key"), params.get("value"))
        return {}

    async def _storage_delete(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.to_thread(self.storage(ctx).delete, params.get("key"))
        return {}

    async def _storage_list(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"keys": await asyncio.to_thread(self.storage(ctx).list, params.get("prefix", ""))}


    async def _http_fetch(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url")
        parts = urlsplit(url) if isinstance(url, str) else None
        host = (parts.hostname or "") if parts else ""
        if parts is None or parts.scheme not in ("https", "http") or not host:
            raise guards.Refused("invalid_params", "url")
        if f"network_hosts:{host}" not in ctx.granted and not any(g.startswith("lan_hosts:") for g in ctx.granted):
            self._record_cap(ctx, f"network_hosts:{host}", False, "not_granted")
            raise guards.Refused("not_granted", f"network_hosts:{host}", {"permission": f"network_hosts:{host}"})
        self._record_cap(ctx, f"network_hosts:{host}", True, "granted")
        return dict(await self._service("http_fetch")(ctx, params))

    async def _ai_call(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        extra = sorted(str(k) for k in params if k not in AI_TOP_LEVEL_KEYS)
        if extra:
            raise guards.Refused("permission_denied", "option_not_allowed", {"reason": "option_not_allowed", "keys": extra})
        feature = params.get("feature")
        if not isinstance(feature, str) or f"ai_features:{feature}" not in ctx.granted:
            self._record_cap(ctx, f"ai_features:{feature}", False, "not_granted")
            raise guards.Refused("not_granted", "ai feature", {"permission": f"ai_features:{feature}"})
        self._record_cap(ctx, f"ai_features:{feature}", True, "granted")
        if params.get("capability") not in AI_CAPABILITIES or not isinstance(params.get("input", {}), dict):
            raise guards.Refused("permission_denied", "capability_not_allowed", {"reason": "capability_not_allowed"})
        from src.plugins.host.plugin_ai import AiRefused  # noqa: PLC0415

        ai = self._service("ai_for")(ctx)
        try:
            return dict(await ai.call(feature, params.get("capability"), params.get("input", {})))
        except AiRefused as exc:
            raise guards.Refused("permission_denied", exc.code, {"reason": exc.code}) from exc

    async def _ledger_read(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "ledger.read")
        return dict(await self._service("ledger")())

    async def _process_snapshot(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "mcp.health.read")
        return dict(await self._service("process_snapshot")())

    async def _mcp_session(self, ctx: PluginContext, params: Dict[str, Any], service: str) -> Dict[str, Any]:
        self._need(ctx, "mcp.health.read")
        ref = params.get("session")
        if ref is not None and (not isinstance(ref, str) or len(ref) > 200):
            raise guards.Refused("invalid_params", "session must be text")
        return dict(await self._service(service)(ref))

    async def _mcp_config(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._mcp_session(ctx, params, "mcp_config")

    async def _mcp_links(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._mcp_session(ctx, params, "mcp_links")

    async def _flow_run(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "flow.read")
        return dict(await self._service("flow_run")(ctx.install_key, params))

    async def _flow_run_part(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "flow.read")
        return dict(await self._service("flow_run_part")(ctx.install_key, params))

    async def _flow_tasks(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "flow.read")
        return dict(await self._service("flow_tasks")(ctx.install_key, params))

    async def _flow_feed(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "flow.read")
        if params.get("topic") not in ctx.topics:
            raise guards.Refused("permission_denied", "undeclared topic", {"reason": "topic_not_declared"})
        return dict(await self._service("flow_feed")(ctx.install_key, params))

    async def _projects_list(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "sessions.read")
        return {"projects": [{"id": p["id"], "name": p["name"]} for p in await self._service("list_projects")()]}

    def _repo(self, project: object) -> Path:
        found = self._service("project_path")(project) if isinstance(project, int) and not isinstance(project, bool) else None
        if found is None:
            raise guards.Refused("invalid_params", "no such project")
        return Path(found)

    async def _projects_git(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "projects.git.read")
        repo = self._repo(params.get("project"))
        try:
            return await asyncio.to_thread(git_ops.read, repo, params.get("op"))
        except git_ops.GitUnavailable as exc:
            raise guards.Refused("unavailable", str(exc)) from exc
        except git_ops.GitRefused as exc:
            raise guards.Refused("invalid_params", str(exc)) from exc

    async def _projects_snapshot(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "projects.git.snapshot")
        repo = self._repo(params.get("project"))
        try:
            return {"ref": await asyncio.to_thread(git_ops.snapshot, repo, params.get("turn"))}
        except git_ops.GitUnavailable as exc:
            raise guards.Refused("unavailable", str(exc)) from exc
        except git_ops.GitRefused as exc:
            raise guards.Refused("invalid_params", str(exc)) from exc

    async def _exports_write(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        self._need(ctx, "exports.write")
        data = params.get("bytes")
        if not isinstance(data, str):
            raise guards.Refused("invalid_params", "bytes must be base64 text")
        import base64  # noqa: PLC0415
        import binascii  # noqa: PLC0415

        try:
            raw = base64.b64decode(data, validate=True)
            folder = fsguard.check_export_folder(params.get("folder"), self._home, ctx.picked_folders)
            name = fsguard.check_export_name(params.get("name"))
            written = await asyncio.to_thread(fsguard.write_export, folder, name, raw)
        except (binascii.Error, ValueError) as exc:
            raise guards.Refused("invalid_params", "bytes") from exc
        except fsguard.UnsafePath as exc:
            raise guards.Refused("permission_denied", exc.code, {"reason": exc.code}) from exc
        except FileExistsError as exc:
            raise guards.Refused("invalid_params", "name already exists") from exc
        return {"path": str(written)}

    async def _log(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        level = params.get("level") if params.get("level") in ("debug", "info", "warning", "error") else "info"
        event, safe = log_redaction.redact_log_params(params)
        getattr(logger.bind(cplug=ctx.plugin_id), level)(f"cplug_{event}", fields=safe)
        return {}

    async def _service_call(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        service = params.get("service")
        method = params.get("method")
        args = params.get("args", {})
        raw_tok = params.get("_bus_token")
        if raw_tok is not None and (not isinstance(raw_tok, str) or not 1 <= len(raw_tok) <= 128):
            raise guards.Refused("invalid_params", "invalid_bus_token")
        if (
            not isinstance(service, str)
            or not _SERVICE_REF_RE.match(service)
            or not isinstance(method, str)
            or not _METHOD_NAME_RE.match(method)
            or not isinstance(args, dict)
        ):
            raise guards.Refused("invalid_params", "service, method, and args object are required")
        try:
            encoded = json.dumps(args, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise guards.Refused("invalid_params", f"service args must be strict JSON ({type(exc).__name__})") from exc
        if len(encoded) > MAX_BUS_PAYLOAD_BYTES:
            raise guards.Refused("too_large", "service_args_too_large")
        if service not in ctx.services_consumes or f"services:{service}" not in ctx.granted:
            self._record_cap(ctx, f"services:{service}", False, "not_granted")
            raise guards.Refused("not_granted", f"services:{service}", {"permission": f"services:{service}"})
        self._record_cap(ctx, f"services:{service}", True, "granted")
        bus_tok = _BUS_CALL_TOKEN.set(raw_tok)
        try:
            return dict(await self._service("service_call")(ctx, service, method, args))
        finally:
            _BUS_CALL_TOKEN.reset(bus_tok)

    async def _events_emit(self, ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        event = params.get("event")
        payload = params.get("payload", {})
        if not isinstance(event, str) or not _EVENT_NAME_RE.match(event) or not isinstance(payload, dict):
            raise guards.Refused("invalid_params", "event and payload object are required")
        if event.startswith(_RESERVED_EVENT_PREFIXES) or event in _RESERVED_EVENT_ROOTS:
            self._record_cap(ctx, f"events:{event}", False, "reserved_event_namespace")
            raise guards.Refused("permission_denied", "reserved_event_namespace", {"event": event})
        if ":" in event and event.partition(":")[0] != ctx.plugin_id:
            self._record_cap(ctx, f"events:{event}", False, "foreign_event_namespace")
            raise guards.Refused("permission_denied", "foreign_event_namespace", {"event": event})
        try:
            encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise guards.Refused("invalid_params", f"event payload must be strict JSON ({type(exc).__name__})") from exc
        if len(encoded) > MAX_BUS_PAYLOAD_BYTES:
            raise guards.Refused("too_large", "event_payload_too_large")
        if event not in ctx.events_emit or f"events:{event}" not in ctx.granted:
            self._record_cap(ctx, f"events:{event}", False, "not_granted")
            raise guards.Refused("not_granted", f"events:{event}", {"permission": f"events:{event}"})
        self._record_cap(ctx, f"events:{event}", True, "granted")
        return dict(await self._service("events_emit")(ctx, event, payload))

    def reply(self, request_id: int, outcome: Any) -> bytes:
        if isinstance(outcome, guards.Refused):
            return frames.error_reply(request_id, CODES.get(outcome.code, frames.INTERNAL_ERROR), outcome.code, outcome.data)
        try:
            return frames.result_reply(request_id, outcome)
        except frames.FrameViolation:
            return frames.error_reply(request_id, frames.TOO_LARGE, "too_large")
