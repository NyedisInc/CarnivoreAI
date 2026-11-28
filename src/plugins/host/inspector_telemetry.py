
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence

from src.core.resource_push.topics import CPLUG_INSPECTOR
from src.plugins.host import absent_surfaces, dev_lease, dev_stream, identity, secret_store
from src.plugins.runtime import fsguard, log_redaction, watchdog

MAX_TRACE_ENTRIES = 200
MAX_CAPABILITY_ENTRIES = 200
MAX_LOG_LINES = 120
_USERINFO_RE = re.compile(r"(?<=://)[^/@\s]+@")
_QUERY_FRAG_RE = re.compile(r"[?#][\s\S]*$")


def _clean_text(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


def _sanitize_target(value: Any, limit: int = 120) -> str:
    if value is None:
        return ""
    stripped = _USERINFO_RE.sub("", str(value))
    stripped = _QUERY_FRAG_RE.sub("", stripped)
    redacted = log_redaction.redact_text(stripped)
    return _clean_text(redacted, limit)


def _sanitize_message(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    stripped = _USERINFO_RE.sub("", str(value))
    redacted = log_redaction.redact_text(stripped)
    return _clean_text(redacted, limit)


def _sanitize_payload(raw: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "..."
    if isinstance(raw, Mapping):
        return {str(k): _sanitize_payload(v, depth + 1) for k, v in list(raw.items())[:24]}
    if isinstance(raw, (list, tuple)):
        return [_sanitize_payload(v, depth + 1) for v in list(raw)[:24]]
    if isinstance(raw, str):
        return log_redaction.redact_text(_USERINFO_RE.sub("", raw))
    return raw


def summarize_target(method: str, params: Any) -> str:
    if not isinstance(params, Mapping):
        return ""
    if method == "http.fetch":
        url = params.get("url")
        if isinstance(url, str):
            return _sanitize_target(url.split("?", 1)[0], 120)
    for key in ("service", "event", "topic", "slot", "surface", "ref", "key", "project", "feature", "name", "folder"):
        val = params.get(key)
        if isinstance(val, str) and val:
            if key == "service" and isinstance(params.get("method"), str):
                return _sanitize_target(f"{val}.{params['method']}", 120)
            return _sanitize_target(val, 120)
    return ""


class InspectorTelemetry:

    def __init__(self, state_dir: Path, *, publish: Optional[Callable[[str], None]] = None,
                 on_loop: Optional[Callable[..., None]] = None) -> None:
        self.state_dir = Path(os.path.realpath(state_dir))
        self._publish = publish
        self._on_loop = on_loop
        self._lock = threading.Lock()
        self._rpc_traces: Dict[str, Deque[Dict[str, Any]]] = {}
        self._cap_checks: Dict[str, Deque[Dict[str, Any]]] = {}
        self._aliases: Dict[str, Sequence[str]] = {}

    def bind_publisher(self, publish: Optional[Callable[[str], None]], on_loop: Optional[Callable[..., None]] = None) -> None:
        with self._lock:
            self._publish = publish
            self._on_loop = on_loop

    def set_aliases(self, plugin_id: str, *aliases: str) -> None:
        cleaned = tuple(dict.fromkeys(a for a in (plugin_id, *aliases) if a))
        with self._lock:
            for item in cleaned:
                self._aliases[item] = cleaned

    def notify(self, plugin_id: str, *extra_keys: str) -> None:
        with self._lock:
            publish = self._publish
            on_loop = self._on_loop
            known = self._aliases.get(plugin_id, (plugin_id,))
        if publish is None:
            return
        keys = tuple(dict.fromkeys(k for k in (plugin_id, *known, *extra_keys) if k))
        for key in keys:
            topic = f"{CPLUG_INSPECTOR}:{key}"
            try:
                if on_loop is not None:
                    on_loop(publish, topic)
                else:
                    publish(topic)
            except RuntimeError:
                pass

    def record_event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("kind")
        plugin_id = str(event.get("plugin_id") or "")
        if not plugin_id:
            return
        if kind == "rpc":
            self.record_rpc(
                plugin_id,
                source=str(event.get("source") or "rpc"),
                method=str(event.get("method") or ""),
                target=str(event.get("target") or ""),
                latency_ms=float(event.get("latency_ms") or 0.0),
                ok=bool(event.get("ok", True)),
                error_code=str(event.get("error_code") or ""),
                error_message=str(event.get("error_message") or ""),
            )
        elif kind == "capability":
            self.record_capability(
                plugin_id,
                permission=str(event.get("permission") or ""),
                allowed=bool(event.get("allowed", False)),
                reason=str(event.get("reason") or ""),
                caller=str(event.get("caller") or ""),
            )

    def record_rpc(self, plugin_id: str, *, source: str, method: str, target: str = "",
                   latency_ms: float = 0.0, ok: bool = True, error_code: str = "",
                   error_message: str = "") -> None:
        entry = {
            "ts": round(time.time(), 3),
            "source": source if source in ("rpc", "cli_sock") else "rpc",
            "method": _clean_text(method, 80),
            "target": _sanitize_target(target, 120),
            "latency_ms": round(float(latency_ms), 2),
            "ok": bool(ok),
            "error_code": _clean_text(error_code, 64),
            "error_message": _sanitize_message(error_message, 160),
        }
        with self._lock:
            buf = self._rpc_traces.setdefault(plugin_id, deque(maxlen=MAX_TRACE_ENTRIES))
            buf.append(entry)
        self.notify(plugin_id)

    def record_capability(self, plugin_id: str, *, permission: str, allowed: bool,
                          reason: str = "", caller: str = "") -> None:
        entry = {
            "ts": round(time.time(), 3),
            "permission": _clean_text(permission, 80),
            "allowed": bool(allowed),
            "reason": _sanitize_message(reason, 64),
            "caller": _sanitize_message(caller, 80),
        }
        with self._lock:
            buf = self._cap_checks.setdefault(plugin_id, deque(maxlen=MAX_CAPABILITY_ENTRIES))
            buf.append(entry)
        self.notify(plugin_id)

    def rpc_trace(self, plugin_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        cap = max(1, min(int(limit), MAX_TRACE_ENTRIES))
        with self._lock:
            buf = self._rpc_traces.get(plugin_id)
            return list(buf)[-cap:] if buf else []

    def capability_checks(self, plugin_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        cap = max(1, min(int(limit), MAX_CAPABILITY_ENTRIES))
        with self._lock:
            buf = self._cap_checks.get(plugin_id)
            return list(buf)[-cap:] if buf else []

    def clear_plugin(self, plugin_id: str) -> None:
        with self._lock:
            self._rpc_traces.pop(plugin_id, None)
            self._cap_checks.pop(plugin_id, None)
            self._aliases.pop(plugin_id, None)


_STORES: Dict[Path, InspectorTelemetry] = {}
_STORES_LOCK = threading.Lock()


def telemetry_for(state_dir: Path) -> InspectorTelemetry:
    key = Path(os.path.realpath(state_dir))
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            store = InspectorTelemetry(key)
            _STORES[key] = store
        return store


def lease_summary(state_dir: Path, plugin_id: str) -> Optional[Dict[str, Any]]:
    store = dev_lease.store_for(state_dir)
    lease = store.get(plugin_id)
    if lease is None:
        return None
    remaining = max(0.0, round(lease.expires_at - store._clock(), 1))
    return {
        "active": True,
        "source_realpath": lease.source_realpath,
        "baseline_sha": lease.baseline_sha,
        "ttl_remaining_seconds": remaining,
    }


def _logs_tail(state_dir: Path, plugin_id: str, proc: Any, limit: int = MAX_LOG_LINES) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if proc is not None and hasattr(proc, "stderr"):
        raw_stderr = getattr(proc, "stderr", None)
        stderr_lines: List[str] = []
        if isinstance(raw_stderr, (bytes, bytearray)):
            stderr_lines = bytes(raw_stderr).decode("utf-8", errors="replace").splitlines()[-limit:]
        elif isinstance(raw_stderr, str):
            stderr_lines = raw_stderr.splitlines()[-limit:]
        elif raw_stderr:
            for item in list(raw_stderr)[-limit:]:
                if isinstance(item, (bytes, bytearray)):
                    stderr_lines.append(bytes(item).decode("utf-8", errors="replace"))
                else:
                    stderr_lines.append(str(item))
        for line in stderr_lines:
            entries.append({"source": "stderr", "line": _sanitize_message(line, limit=500)})
    stream = dev_stream.stream_for(state_dir)
    for ev in stream.recent(plugin_id)[-limit:]:
        if not isinstance(ev, Mapping):
            continue
        source = ev.get("kind") or ev.get("type")
        if source in ("stderr", "reload_error", "ui_error", "permission_widened", "reloaded"):
            raw_payload = ev.get("payload")
            if raw_payload is None:
                raw_payload = ev.get("data")
            sanitized = _sanitize_payload(raw_payload or {})
            entries.append({
                "seq": ev.get("seq"),
                "ts": round(float(ev.get("ts") or 0.0), 3),
                "source": source,
                "payload": sanitized if isinstance(sanitized, dict) else {"value": sanitized},
            })
    return entries[-limit:]


def _sample_watchdog(supervisor: Any, state_dir: Path, plugin_id: str, data_dir: Optional[Path], proc: Any) -> Dict[str, Any]:
    rss_bytes = 0
    cpu_seconds = 0.0
    uptime_seconds = 0.0
    pid = None
    if proc is not None and not getattr(proc, "ended", None):
        pid = getattr(proc, "pid", None)
        started_at = float(getattr(proc, "started_at", 0.0) or 0.0)
        if started_at > 0.0:
            uptime_seconds = max(0.0, round(time.monotonic() - started_at, 2))
        if isinstance(pid, int) and pid > 0:
            usage = watchdog.usage_of(pid)
            if usage is not None:
                rss_bytes = int(usage.rss)
                cpu_seconds = round(float(usage.cpu), 3)
    files_dir = data_dir / "files" if data_dir is not None else identity.data_dir(state_dir, plugin_id) / "files"
    disk_bytes, disk_files = fsguard.tree_usage(files_dir) if files_dir.exists() else (0, 0)
    strikes_ledger = getattr(supervisor, "_strikes", {}).get(plugin_id) if supervisor is not None else None
    strikes = len(getattr(strikes_ledger, "_times", ())) if strikes_ledger is not None else 0
    restart_count = supervisor.restart_count(plugin_id) if supervisor is not None and hasattr(supervisor, "restart_count") else 0
    state = supervisor.state(plugin_id) if supervisor is not None and hasattr(supervisor, "state") else "unknown"
    cpu_percent = round((cpu_seconds / uptime_seconds) * 100.0, 2) if uptime_seconds > 0.5 else 0.0
    return {
        "memory_limit_bytes": watchdog.MEMORY_LIMIT_BYTES,
        "rss_bytes": rss_bytes,
        "cpu_seconds": cpu_seconds,
        "cpu_percent": cpu_percent,
        "disk_bytes": int(disk_bytes),
        "disk_quota_bytes": watchdog.DISK_QUOTA_BYTES,
        "disk_files": int(disk_files),
        "disk_quota_files": watchdog.DISK_QUOTA_FILES,
        "restart_count": int(restart_count),
        "strikes": int(strikes),
        "crash_loop_paused": state == "crash_loop",
        "uptime_seconds": uptime_seconds,
        "pid": pid,
    }


def _surfaces_summary(defn: Any) -> Dict[str, Any]:
    if defn is None or getattr(defn, "manifest", None) is None:
        return {
            "widget": False,
            "panel": False,
            "bar": False,
            "settings": False,
            "views": [],
            "tools": [],
            "routes": [],
            "absent_surfaces": [],
            "timers": [],
        }
    m = defn.manifest
    surfaces = set(getattr(m, "ui_surfaces", ()) or ())
    ui_meta = getattr(m, "ui_meta", None)
    has_widget = (
        "widget" in surfaces
        or (isinstance(ui_meta, Mapping) and bool(ui_meta.get("widget")))
        or bool(getattr(getattr(m, "surfaces", None), "widgets", ()))
    )
    views = [v.get("name") for v in (getattr(m, "views", ()) or ()) if isinstance(v, Mapping) and v.get("name")]
    raw_tools = getattr(m, "tools", ()) or ()
    tools = [t.get("name") for t in raw_tools if isinstance(t, Mapping) and t.get("name")]
    if not tools and getattr(getattr(m, "surfaces", None), "mcp_tools", ()):
        tools = [str(t) for t in m.surfaces.mcp_tools]
    raw_routes = getattr(m, "routes", ())
    routes = sorted(str(r) for r in raw_routes) if isinstance(raw_routes, (list, tuple, set, frozenset)) else []
    timers = sorted(str(k) for k in (getattr(m, "timers", None) or {}).keys())
    absent = absent_surfaces.listed(str(getattr(m, "id", "")), str(getattr(m, "version", "")))
    return {
        "widget": has_widget,
        "panel": "panel" in surfaces,
        "bar": "bar" in surfaces,
        "settings": "settings" in surfaces or bool(getattr(m, "settings_schema", None)),
        "views": views,
        "tools": tools,
        "routes": routes,
        "absent_surfaces": absent,
        "timers": timers,
    }


def _secrets_status(state_dir: Path, install_key: str, defn: Any) -> Dict[str, Dict[str, bool]]:
    manifest = getattr(defn, "manifest", None)
    secrets = getattr(getattr(manifest, "network", None), "secrets", ()) if manifest is not None else ()
    if not secrets:
        return {}
    if not install_key:
        return {s.name: {"present": False, "needs_reentry": False} for s in secrets}
    store = secret_store.SecretStore(state_dir)
    out: Dict[str, Dict[str, bool]] = {}
    for s in secrets:
        try:
            st = store.status(install_key, manifest, s.name)
            out[s.name] = {"present": bool(st.get("secret_present")), "needs_reentry": bool(st.get("needs_reentry"))}
        except secret_store.SecretError:
            out[s.name] = {"present": False, "needs_reentry": False}
    return out


def build_snapshot_blocking(
    state_dir: Path,
    supervisor: Any,
    plugin_id: str,
    *,
    canonical_id: str,
    install_key: str,
    kind: str,
    trust_tier: str,
    trust_badge: str,
    unverified: bool,
    defn: Any = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    telemetry = telemetry_for(state_dir)
    telemetry.set_aliases(plugin_id, canonical_id, install_key)
    proc = supervisor.process(plugin_id) if supervisor is not None and hasattr(supervisor, "process") else None
    paused = supervisor.is_paused(plugin_id) if supervisor is not None and hasattr(supervisor, "is_paused") else False
    state = supervisor.state(plugin_id) if supervisor is not None and hasattr(supervisor, "state") else "unknown"
    return {
        "cplug_id": canonical_id,
        "plugin_id": plugin_id,
        "install_key": install_key,
        "kind": kind,
        "trust_tier": trust_tier,
        "trust_badge": trust_badge,
        "unverified": bool(unverified),
        "state": state,
        "paused": bool(paused),
        "watchdog": _sample_watchdog(supervisor, state_dir, plugin_id, data_dir, proc),
        "surfaces": _surfaces_summary(defn),
        "dev_lease": lease_summary(state_dir, plugin_id),
        "secrets_status": _secrets_status(state_dir, install_key, defn),
        "rpc_trace": telemetry.rpc_trace(plugin_id),
        "capability_checks": telemetry.capability_checks(plugin_id),
        "logs_tail": _logs_tail(state_dir, plugin_id, proc),
    }


def watchdog_row_summary(state_dir: Path, supervisor: Any, plugin_id: str, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    proc = supervisor.process(plugin_id) if supervisor is not None and hasattr(supervisor, "process") else None
    w = _sample_watchdog(supervisor, state_dir, plugin_id, data_dir, proc)
    telemetry = telemetry_for(state_dir)
    traces = telemetry.rpc_trace(plugin_id, limit=1)
    last_call: Optional[str] = None
    if traces:
        entry = traces[-1]
        method = str(entry.get("method") or "").strip()
        target = str(entry.get("target") or "").strip()
        last_call = f"{method} {target}".strip() if target else (method or None)
    last_event: Optional[str] = None
    recent_events = dev_stream.stream_for(state_dir).recent(plugin_id)
    if recent_events:
        ev = recent_events[-1]
        if isinstance(ev, Mapping):
            ev_type = str(ev.get("type") or ev.get("kind") or "").strip()
            if ev_type:
                last_event = ev_type
    if last_event is None:
        caps = telemetry.capability_checks(plugin_id, limit=1)
        if caps:
            cap = caps[-1]
            perm = str(cap.get("permission") or "").strip()
            allowed = "allowed" if cap.get("allowed") else "denied"
            if perm:
                last_event = f"{perm} ({allowed})"
    return {
        "memory_limit_bytes": w["memory_limit_bytes"],
        "rss_bytes": w["rss_bytes"],
        "cpu_percent": w["cpu_percent"],
        "restart_count": w["restart_count"],
        "strikes": w["strikes"],
        "crash_loop_paused": w["crash_loop_paused"],
        "last_call": last_call,
        "last_event": last_event,
    }
