
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.flow_data import live
from src.plugins.host import ai_budget, capabilities, egress_log, fetch_proxy, flow_port, plugin_ai, plugin_bus, secret_store, sidecar_registry, sidecar_topics, ui_slots
from src.plugins.runtime import dispatch, guards
from src.plugins.runtime.dispatch import PluginContext
from src.plugins.sdk.ai_features import feature_id, permission_name

logger = structlog.get_logger()

_STOP_ACTION = "plugin_session_stop"
_STOP_CALLER_PREFIX = "cplug:"
_STOP_WAIT_SECONDS = 120.0
_STOP_SETTLE_SECONDS = 5.0
_STOP_WITHDRAWN = "the plugin stopped"


def _find_local_info(infos: List[Any], ref: str) -> Any:
    for info in infos:
        inner = getattr(info, "session", None)
        sid = getattr(inner, "id", None)
        tmux = getattr(info, "tmux_session", None)
        suuid = getattr(info, "session_uuid", None)
        if ref in (sid, tmux, suuid):
            return info
    return None


def _require_local_info(infos: List[Any], ref: str) -> Any:
    info = _find_local_info(infos, ref)
    if info is None:
        raise guards.Refused("not_found", "no such session")
    inner = getattr(info, "session", None)
    sid = str(getattr(inner, "id", "") or "")
    host_key = getattr(info, "host_key", None)
    if sid.startswith("remote:") or (host_key is not None and host_key != "local"):
        raise guards.Refused("permission_denied", "remote_ref", {"reason": "remote_ref"})
    return info


def _map_fetch_error(exc: fetch_proxy.FetchRefused) -> guards.Refused:
    code = exc.code
    if code == "rate_limited":
        return guards.Refused("rate_limited", code, {"reason": code})
    if code == "timeout":
        return guards.Refused("timeout", code, {"reason": code})
    if code in ("request_too_large", "response_too_large"):
        return guards.Refused("too_large", code, {"reason": code})
    if code in ("bad_url", "bad_header", "body_not_allowed"):
        return guards.Refused("invalid_params", code, {"reason": code})
    if code in ("upstream_error", "dns_failed", "peers_unknown"):
        return guards.Refused("unavailable", code, {"reason": code})
    return guards.Refused("permission_denied", code, {"reason": code})


def build_services(
    *,
    host: Any,
    app: Any,
    state_dir: Callable[[], Path],
    supervisor_getter: Callable[[], Any],
    rate_limiter: Optional[fetch_proxy.RateLimiter] = None,
    bus: Optional[Any] = None,
    coalesce: Optional[Callable[..., None]] = None,
    on_plugin_stopped_register: Optional[Callable[[Callable[[str], None]], None]] = None,
) -> Dict[str, Any]:
    limiter = rate_limiter or fetch_proxy.RateLimiter()
    active_bus = bus or plugin_bus.PluginBus(
        host=host,
        state_dir=state_dir,
        supervisor_getter=supervisor_getter,
        safe_mode_getter=lambda: getattr(getattr(host, "sidecar_runtime", lambda: None)(), "safe_mode", lambda: {"env": False, "owner": False, "off": False})(),
        on_loop=lambda fn, *a: fn(*a),
    )

    def _feed_topic(install_key: str, topic: str) -> None:
        wire = sidecar_topics.wire_topic(install_key, topic, None)
        if coalesce is not None:
            coalesce(wire, wire, sidecar_topics.FEED_FOLD_S, None)
        else:
            host.publish_coalesced(wire, wire, sidecar_topics.FEED_FOLD_S, None)

    flow = flow_port.FlowPort(state_dir, on_topic=_feed_topic)

    def _on_plugin_stopped(install_key: str) -> None:
        flow.cache.forget(install_key)
        live.drop_owners(f"{install_key}:")

    if on_plugin_stopped_register is not None:
        on_plugin_stopped_register(_on_plugin_stopped)

    def _lookup_def(plugin_id: str) -> Any:
        from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

        return sidecar_registry.find(plugin_id) or host_runtime.find(plugin_id)

    async def http_fetch(ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        d = _lookup_def(ctx.plugin_id)
        if d is None:
            raise guards.Refused("unavailable", "plugin_not_found")
        method = params.get("method", "GET")
        url = params.get("url", "")
        headers = params.get("headers")
        raw_body = params.get("body")
        body: Optional[bytes]
        if raw_body is None:
            body = None
        elif isinstance(raw_body, str):
            body = raw_body.encode("utf-8")
        elif isinstance(raw_body, (bytes, bytearray)):
            body = bytes(raw_body)
        else:
            raise guards.Refused("invalid_params", "body")
        if headers is not None and not isinstance(headers, dict):
            raise guards.Refused("invalid_params", "headers")
        sdir = state_dir()
        proxy = fetch_proxy.PluginFetch(
            d.manifest,
            ctx.install_key,
            lambda: host._live_grants(d.manifest),
            secret_store.SecretStore(sdir),
            egress_log.EgressLog(sdir),
            limiter,
        )
        try:
            resp = await proxy.fetch(method, url, headers=headers, body=body)
        except fetch_proxy.FetchRefused as exc:
            raise _map_fetch_error(exc) from exc
        return {
            "status": resp.status,
            "headers": dict(resp.headers),
            "body": resp.body.decode("utf-8", errors="replace"),
            "truncated": resp.truncated,
        }

    def ai_for(ctx: PluginContext) -> plugin_ai.PluginAi:
        d = _lookup_def(ctx.plugin_id)
        if d is None:
            raise guards.Refused("unavailable", "plugin_not_found")
        granted_ai = {
            feature_id(d.id, n): f
            for n, f in (getattr(d.manifest, "ai_features", None) or {}).items()
            if permission_name(d.id, n) in ctx.granted
        }
        return plugin_ai.PluginAi(d.id, granted_ai, ai_budget.AiBudget(state_dir()), getattr(host, "ai_gateway", None))

    async def session_output(ref: str, lines: int) -> List[str]:
        from src.core.mcp import tools as mcp_tools  # noqa: PLC0415

        app_state = getattr(app, "state", None)
        sm = getattr(app_state, "session_manager", None)
        if sm is None:
            raise guards.Refused("unavailable", "session_manager")
        infos = await capabilities.local_infos_from_app(app_state)()
        info = _require_local_info(infos, ref)
        try:
            raw = await asyncio.to_thread(
                sm.capture_scrollback,
                lines=lines + mcp_tools.REDACT_MARGIN_LINES,
                session_id=info.session.id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("cplug_session_output_failed", session_id=info.session.id, error_type=type(exc).__name__)
            raise guards.Refused("unavailable", "session_output_unavailable") from exc
        if raw is None:
            raw_bytes = b""
        elif isinstance(raw, (bytes, bytearray)):
            raw_bytes = bytes(raw)
        else:
            raw_bytes = str(raw).encode("utf-8", "replace")
        cleaned = mcp_tools.clean_output(raw_bytes, lines)
        return cleaned.splitlines()[-lines:]

    async def permission_mode(ref: str) -> Optional[str]:
        from src.core.mcp import tools as mcp_tools  # noqa: PLC0415
        from src.core.pack.jobs import agent_facts  # noqa: PLC0415

        app_state = getattr(app, "state", None)
        sm = getattr(app_state, "session_manager", None)
        if sm is None:
            return None
        try:
            infos = await capabilities.local_infos_from_app(app_state)()
        except Exception as exc:  # noqa: BLE001
            logger.error("cplug_permission_mode_list_failed", error_type=type(exc).__name__)
            return None
        info = _find_local_info(infos, ref)
        if info is None:
            return None
        host_key = getattr(info, "host_key", None)
        if host_key is not None and host_key != "local":
            return None
        family = getattr(info, "agent_family", None) or "claude"
        if family == "claude":
            try:
                mode, _ = await asyncio.to_thread(agent_facts._transcript_facts, sm, info, family)
                if isinstance(mode, str) and mode.strip():
                    return mode.strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cplug_permission_mode_transcript_failed", session_id=info.session.id, error_type=type(exc).__name__)
        try:
            raw = await asyncio.to_thread(sm.capture_scrollback, lines=12, session_id=info.session.id)
            text = mcp_tools.strip_ansi(raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_permission_mode_capture_failed", session_id=info.session.id, error_type=type(exc).__name__)
            return None
        tail = "\n".join([line for line in text.splitlines() if line.strip()][-6:])
        low = tail.lower()
        if "bypass permissions" in low or "skip permissions" in low or "dangerously" in low:
            return "bypass"
        if "accept edits" in low:
            return "acceptEdits"
        if "plan mode" in low:
            return "plan"
        if "dontask" in low or "don't ask" in low:
            return "dontAsk"
        return None

    async def paste_line(ref: str, line: str) -> Dict[str, Any]:
        from src.core.sessions.guarded_paste import PasteFailed, PasteRefused, PasteSessionNotFound, paste_through_gates  # noqa: PLC0415

        app_state = getattr(app, "state", None)
        infos = await capabilities.local_infos_from_app(app_state)()
        info = _require_local_info(infos, ref)
        try:
            await paste_through_gates(app_state, info.session.id, line)
        except PasteSessionNotFound as exc:
            raise guards.Refused("not_found", "no such session") from exc
        except PasteRefused as exc:
            if exc.code == "pane_dialog_open":
                raise guards.Refused("dialog_open", exc.code, {"reason": exc.code}) from exc
            raise guards.Refused("permission_denied", exc.code, {"reason": exc.code}) from exc
        except PasteFailed as exc:
            logger.error("cplug_paste_line_failed", session_id=info.session.id, error_type=type(exc).__name__)
            raise guards.Refused("unavailable", exc.code, {"reason": exc.code}) from exc
        return {"delivered": True}

    async def _stop_via_inbox(plugin_id: str, app_state: Any, info: Any) -> Dict[str, Any]:
        from src.core import session_change_notice  # noqa: PLC0415
        from src.core.mcp import pending  # noqa: PLC0415
        from src.core.session_ops import close_record  # noqa: PLC0415

        store = pending.get_store()
        session_id = info.session.id
        tmux_name = getattr(info, "tmux_session", "") or session_id
        caller = f"{_STOP_CALLER_PREFIX}{plugin_id}"

        async def execute() -> Dict[str, Any]:
            sup = supervisor_getter()
            proc = sup.process(plugin_id) if sup is not None else None
            d_live = _lookup_def(plugin_id)
            live_grants = host._live_grants(d_live.manifest) if d_live is not None else frozenset()
            has_proc = proc is not None and proc.ended is None and "sessions.control" in proc.spec.ctx.granted
            has_live = sup is not None and sup.available(plugin_id) and "sessions.control" in live_grants
            if not (has_proc or has_live):
                raise pending.ActionRefused("the plugin is no longer running with sessions.control")
            sm = getattr(app_state, "session_manager", None)
            if sm is None:
                raise pending.ActionRefused("session manager unavailable")
            registry = getattr(getattr(app_state, "services", None), "registry", None)
            backend = registry.get_backend(session_id) if callable(getattr(registry, "get_backend", None)) else None
            socket = getattr(backend, "socket_name", None) if backend else None
            epoch = await close_record.instance_epoch(backend) if tmux_name else None
            await close_record.stop_and_record(
                lambda: sm.destroy_session(session_id=session_id),
                socket=socket,
                name=tmux_name,
                epoch=epoch,
                host="local",
            )
            session_change_notice.publish(app_state, session_change_notice.build_structural_notice("destroyed"))
            return {"ok": True}

        try:
            item = store.create(
                caller_session_id=caller,
                caller_tmux=caller,
                target_session_id=session_id,
                target_tmux=tmux_name,
                action=_STOP_ACTION,
                args_summary=f"plugin {plugin_id} asks to stop session {tmux_name}",
                execute=execute,
                args={"plugin": plugin_id, "session_id": session_id, "tmux_session": tmux_name},
                dedupe_key=secrets.token_hex(8),
                beast_eligible=False,
            )
        except pending.PayloadTooLargeError as exc:
            raise guards.Refused("too_large", str(exc), {"reason": "card_too_large"}) from exc
        except pending.PendingLimitError as exc:
            raise guards.Refused("rate_limited", str(exc), {"reason": "too_many_waiting"}) from exc

        try:
            status = await pending.wait_for(item, _STOP_WAIT_SECONDS)
            if status == pending.PENDING:
                status = "timeout" if store.withdraw(item.id, "the plugin stopped waiting for your answer") else item.status
            if status != "timeout" and not pending.finished(item):
                status = await pending.wait_for(item, _STOP_SETTLE_SECONDS)
        finally:
            if item.status == pending.PENDING:
                store.withdraw(item.id, _STOP_WITHDRAWN)

        if status == pending.APPROVED:
            if not pending.finished(item):
                raise guards.Refused("timeout", "session stop did not finish in time", {"reason": "settle_timeout"})
            if isinstance(item.result, dict) and item.result.get("isError"):
                raise guards.Refused("unavailable", "session stop failed", {"reason": "stop_failed"})
            return {"ok": True}
        if status == "timeout":
            raise guards.Refused("timeout", "the owner did not answer in time", {"reason": "owner_timeout"})
        if status == pending.REFUSED:
            raise guards.Refused("permission_denied", "refused when the owner approved", {"reason": "refused_at_approve"})
        raise guards.Refused("permission_denied", "the owner denied this request", {"reason": "owner_denied"})

    async def control_session(plugin_id: str, ref: str, action: str) -> Dict[str, Any]:
        app_state = getattr(app, "state", None)
        if action not in dispatch.CONTROL_ACTIONS:
            raise guards.Refused("invalid_params", "action is restart, stop, sleep or wake")
        infos = await capabilities.local_infos_from_app(app_state)()
        info = _find_local_info(infos, ref)
        if info is not None:
            inner = getattr(info, "session", None)
            sid = str(getattr(inner, "id", "") or "")
            host_key = getattr(info, "host_key", None)
            if sid.startswith("remote:") or (host_key is not None and host_key != "local"):
                raise guards.Refused("permission_denied", "remote_ref", {"reason": "remote_ref"})
        if action == "stop":
            if info is None:
                raise guards.Refused("not_found", "no such session")
            return await _stop_via_inbox(plugin_id, app_state, info)
        if action == "sleep":
            if info is None:
                raise guards.Refused("not_found", "no such session")
            from src.core.session_ops.sleep import SleepError, sleep_session  # noqa: PLC0415

            target_uuid = getattr(info, "session_uuid", None) or info.session.id
            try:
                outcome = await sleep_session(app_state, target_uuid)
            except SleepError as exc:
                logger.error("cplug_control_sleep_failed", session_uuid=target_uuid, error_type=type(exc).__name__)
                raise guards.Refused("permission_denied", str(exc)) from exc
            if outcome.status != "asleep":
                raise guards.Refused("permission_denied", outcome.detail or outcome.status)
            return {"ok": True}
        if action == "wake":
            from src.api.session_sleep_routes import wake_by_uuid  # noqa: PLC0415

            target_uuid = getattr(info, "session_uuid", None) if info is not None else ref
            target_uuid = target_uuid or ref
            try:
                await wake_by_uuid(app_state, target_uuid)
            except HTTPException as exc:
                logger.error("cplug_control_wake_failed", session_uuid=target_uuid, error_type=type(exc).__name__)
                code = "not_found" if exc.status_code == 404 else "permission_denied"
                raise guards.Refused(code, str(exc.detail)) from exc
            return {"ok": True}
        from src.core.session_ops.restart import (  # noqa: PLC0415
            AlreadyRunning,
            NoDatastore,
            RestartError,
            RestartSourceNotFound,
            restart_stopped_session,
        )

        target_uuid = getattr(info, "session_uuid", None) if info is not None else ref
        target_uuid = target_uuid or ref
        try:
            await restart_stopped_session(app_state, target_uuid)
        except (NoDatastore, RestartSourceNotFound) as exc:
            raise guards.Refused("not_found", str(exc)) from exc
        except AlreadyRunning as exc:
            raise guards.Refused("permission_denied", "cannot restart a live session", {"reason": "already_running"}) from exc
        except RestartError as exc:
            logger.error("cplug_control_restart_failed", session_uuid=target_uuid, error_type=type(exc).__name__)
            raise guards.Refused("permission_denied", str(exc)) from exc
        return {"ok": True}

    async def list_projects() -> List[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(lambda: capabilities.Projects(restricted=True).list(strict=True))
        except OSError as exc:
            logger.error("cplug_list_projects_failed", error_type=type(exc).__name__)
            raise guards.Refused("unavailable", "projects_unreadable") from exc

    def project_path(project_id: int) -> Optional[Path]:
        try:
            row = capabilities.Projects(restricted=False).get(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("cplug_project_path_failed", project_id=project_id, error_type=type(exc).__name__)
            return None
        raw = row.get("path") if isinstance(row, dict) else None
        return Path(raw) if isinstance(raw, str) and raw else None

    async def ledger() -> Dict[str, Any]:
        from src.api.provider_ledger_routes import get_provider_ledger  # noqa: PLC0415
        from src.core.mcp.read_tools import scrub  # noqa: PLC0415
        from src.core.provider_ledger import pace  # noqa: PLC0415

        try:
            snap = await get_provider_ledger()
        except Exception as exc:  # noqa: BLE001
            logger.error("cplug_ledger_failed", error_type=type(exc).__name__)
            raise guards.Refused("unavailable", "ledger_unavailable") from exc
        now = datetime.now(timezone.utc)
        accounts = []
        for a in getattr(snap, "accounts", ()):
            windows = []
            for w in getattr(a, "windows", ()):
                length = pace.window_length_seconds(w.kind, w.label, w.window_seconds)
                elapsed = pace.elapsed_pct(length, w.resets_at, now)
                windows.append({
                    "kind": w.kind,
                    "label": w.label,
                    "used_pct": w.used_pct,
                    "elapsed_pct": elapsed,
                    "pace": pace.pace_state(w.used_pct, elapsed),
                    "resets_at": w.resets_at,
                })
            accounts.append({
                "id": a.id,
                "name": a.name,
                "provider": a.provider,
                "plan": a.plan,
                "credential_state": a.credential_state,
                "error": a.error,
                "fetched_at": a.fetched_at,
                "windows": windows,
            })
        return scrub({"accounts": accounts})

    async def ui_slot_publish(ctx: PluginContext, slot: str, items: List[Any]) -> Dict[str, Any]:
        from src.plugins.host import runtime as host_runtime  # noqa: PLC0415

        listed_fn = getattr(host, "listed", None)
        definitions = list(listed_fn()) if callable(listed_fn) else list(host_runtime.listed())
        seen = {d.id for d in definitions if getattr(d, "id", None)}
        reg = sidecar_registry.current()
        if reg is not None:
            for d in reg.listed():
                if getattr(d, "id", None) and d.id not in seen:
                    definitions.append(d)
                    seen.add(d.id)
        rt = getattr(host, "sidecar_runtime", lambda: None)()
        safe_mode_active = any(rt.safe_mode().values()) if rt is not None and callable(getattr(rt, "safe_mode", None)) else False
        try:
            published = ui_slots.registry_for(state_dir()).publish(
                ctx.plugin_id,
                slot,
                items,
                host=host,
                definitions=definitions,
                safe_mode_active=safe_mode_active,
                supervisor=supervisor_getter(),
            )
        except ui_slots.UiSlotError as exc:
            if exc.status == 403:
                raise guards.Refused("not_granted", exc.code, {"permission": f"ui.slot:{slot}"}) from exc
            if exc.status == 429:
                raise guards.Refused("rate_limited", exc.code) from exc
            if exc.status == 409:
                raise guards.Refused("disabled", exc.code) from exc
            raise guards.Refused("invalid_params", exc.code) from exc
        return {"slot": ui_slots.canonical_slot(slot), "items": published}

    return {
        "http_fetch": http_fetch,
        "ai_for": ai_for,
        "session_output": session_output,
        "permission_mode": permission_mode,
        "paste_line": paste_line,
        "control_session": control_session,
        "list_projects": list_projects,
        "project_path": project_path,
        "ledger": ledger,
        "service_call": active_bus.call_service,
        "events_emit": active_bus.emit_plugin_event,
        "ui_slot_publish": ui_slot_publish,
        "flow_run": flow.run,
        "flow_run_part": flow.part,
        "flow_feed": flow.feed,
        "flow_tasks": flow.tasks,
    }
