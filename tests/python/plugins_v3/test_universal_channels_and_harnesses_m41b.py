
from __future__ import annotations

import asyncio
import json
import shutil
import socket
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import notification_types_routes
from src.api.auth import require_auth
from src.core.agent_manifests import engine as harness_engine
from src.core.notifications import kind_specs
from src.core.notifications.contracts import FailureClass
from src.core.notifications.engine import NotifyEngine
from src.core.notifications.kinds import registry as sender_registry
from src.core.notifications.routing_view import DestinationView
from src.core.resource_push import topics
from src.plugins.host import (
    activity_log,
    fetch_proxy,
    inspector_telemetry,
    netguard,
    owner_switch,
    plugin_channels,
    routes as host_routes,
    runtime as host_runtime,
    secret_store,
    sidecar_boot,
    sidecar_registry,
    state as owner_state,
    ui_slots,
)
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import guards
from src.plugins.runtime.supervisor import Supervisor
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.manifest import load_manifest

DARWIN_SANDBOX = sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def _write_v2_plugin(
    folder: Path,
    plugin_id: str,
    *,
    tier: str = "catalog",
    run_cmd: List[str] | None = None,
    with_channel: bool = True,
    with_harness: bool = True,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    raw: Dict[str, Any] = {
        "schema": 2,
        "id": plugin_id,
        "name": f"Plugin {plugin_id}",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Channels and harnesses test plugin",
        "author": "Tester",
    }
    if tier == "builtin":
        raw["tier"] = "builtin"
    if run_cmd:
        raw["run"] = {"cmd": run_cmd, "mode": "rpc"}
    if with_channel:
        raw["permissions"] = {
            "network": [{"host": "hooks.example.com", "methods": ["POST"], "paths": ["/alert"], "reason": "Send webhook alerts"}]
        }
        raw["channels"] = {
            "alerts": {
                "label": f"{plugin_id} Alerts",
                "url": "https://hooks.example.com/alert",
                "method": "POST",
                "body_template": {"title": "{{title}}", "severity": "{{severity}}"},
            }
        }
    else:
        raw["permissions"] = {"app": []}
    if with_harness:
        raw["harnesses"] = ["custom_agent.toml"]
        (folder / "custom_agent.toml").write_text(
            f'id = "agent_{plugin_id}"\nnames = ["agent_{plugin_id}"]\n',
            encoding="utf-8",
        )
    (folder / "carnivore.json").write_text(json.dumps(raw), encoding="utf-8")


def _cleanup_plugin(plugin_id: str) -> None:
    plugin_channels.unregister_plugin(plugin_id, publish=False)


@pytest.mark.asyncio
async def test_universal_channels_tier0_idle_sidecar_and_builtin_notify_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    owner_switch.write(state_dir, True)
    published: List[str] = []
    host = host_runtime.Host(state_dir, publish=published.append)

    t0_dir = tmp_path / "tier0_ch"
    _write_v2_plugin(t0_dir, "chzero", with_harness=False)
    m_t0 = load_sidecar_manifest(t0_dir, "chzero")
    d_t0 = SidecarDefinition(manifest=m_t0, item_id="acme/chzero", install_key="inst-chzero", code_root=t0_dir, folder=tmp_path / "d_t0")
    owner_state.update(state_dir, m_t0, None, lambda st: replace(st, enabled=True, grants=tuple(m_t0.permissions), digest=m_t0.code_digest))

    idle_dir = tmp_path / "idle_ch"
    _write_v2_plugin(idle_dir, "chidle", run_cmd=["python3", "main.py"], with_harness=False)
    (idle_dir / "main.py").write_text("# stub\n", encoding="utf-8")
    m_idle = load_sidecar_manifest(idle_dir, "chidle")
    d_idle = SidecarDefinition(manifest=m_idle, item_id="acme/chidle", install_key="inst-chidle", code_root=idle_dir, folder=tmp_path / "d_idle")
    owner_state.update(state_dir, m_idle, None, lambda st: replace(st, enabled=True, grants=tuple(m_idle.permissions), digest=m_idle.code_digest))

    bi_dir = tmp_path / "builtin_ch"
    _write_v2_plugin(bi_dir, "chbuilt", tier="builtin", with_harness=False)
    (bi_dir / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    m_bi = load_manifest(str(bi_dir / "__init__.py"))
    d_bi = CplugDefinition(manifest=m_bi, code_root=bi_dir)
    owner_state.update(state_dir, m_bi, None, lambda st: replace(st, enabled=True, grants=tuple(m_bi.permissions)))

    by_id = {"chzero": d_t0, "chidle": d_idle, "chbuilt": d_bi}
    fake_reg = SimpleNamespace(listed=lambda: [d_t0, d_idle], find=lambda pid: by_id.get(pid))
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: d_t0 if pid == "chzero" else (d_idle if pid == "chidle" else None))
    monkeypatch.setattr(host_runtime, "find", lambda pid: by_id.get(pid))
    monkeypatch.setattr(host_runtime, "listed", lambda: (d_bi, d_t0, d_idle))

    try:
        plugin_channels.sync_all(host, [d_t0, d_idle, d_bi])
        assert topics.NOTIFICATION_SETTINGS in published

        app = FastAPI()
        app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
        app.include_router(notification_types_routes.router, prefix="/api/v1")
        kinds_by_id = {k["id"]: k for k in TestClient(app).get("/api/v1/notifications/types").json()["kinds"]}
        for pid in ("chzero", "chidle", "chbuilt"):
            kid = f"plugin:{pid}:alerts"
            assert kid in kinds_by_id
            assert kinds_by_id[kid]["plugin_id"] == pid
            assert kinds_by_id[kid]["label"] == f"{pid} Alerts"

        sent_http: List[Dict[str, Any]] = []

        class _FakeProxy:
            async def fetch(self, method: str, url: str, *, headers=None, body=None):
                sent_http.append({"method": method, "url": url, "body": body})
                return fetch_proxy.FetchResponse(status=200, headers={}, body="ok")

        host.fetch_for = lambda _pid: _FakeProxy()

        rpc_calls: List[tuple[str, Dict[str, Any]]] = []

        class _FakeProc:
            async def request(self, method: str, params: Dict[str, Any], timeout: float = 5.0):
                rpc_calls.append((method, params))
                return {"ok": True, "status_code": 202, "detail": "delivered via rpc"}

        class _FakeSup:
            def state(self, _pid: str) -> str:
                return "idle"

            def is_paused(self, _pid: str) -> bool:
                return False

            async def ensure(self, _pid: str):
                return _FakeProc()

        host.sidecar_runtime = lambda: SimpleNamespace(supervisor=_FakeSup(), safe_mode=lambda: {"env": False, "owner": False, "off": False})

        dest_t0 = DestinationView(id="d_000000000001", kind="plugin:chzero:alerts", name="T0", enabled=True, scope="global", config={}, details=True)
        dest_idle = DestinationView(id="d_000000000002", kind="plugin:chidle:alerts", name="Idle", enabled=True, scope="global", config={}, details=True)
        dest_bi = DestinationView(id="d_000000000003", kind="plugin:chbuilt:alerts", name="BI", enabled=True, scope="global", config={}, details=True)
        dests = [dest_t0, dest_idle, dest_bi]

        fake_view = SimpleNamespace(destinations=lambda: dests)
        monkeypatch.setattr("src.core.notifications.engine.current_view", lambda: fake_view)

        async def _secrets(_id: str) -> Dict[str, str]:
            return {}

        engine = NotifyEngine(
            sender_lookup=sender_registry.sender_for,
            secrets_lookup=_secrets,
            is_muted=lambda _s, _t: False,
        )
        out_t0 = await engine.send_test("d_000000000001")
        out_bi = await engine.send_test("d_000000000003")
        out_idle = await engine.send_test("d_000000000002")

        assert out_t0.result is not None and out_t0.result.ok is True
        assert out_bi.result is not None and out_bi.result.ok is True
        assert out_idle.result is not None and out_idle.result.ok is True
        assert len(sent_http) == 2
        assert rpc_calls[0][0] == "channel.send"
        assert rpc_calls[0][1]["channel"] == "alerts"

        owner_state.update(state_dir, m_t0, None, lambda st: replace(st, enabled=False))
        blocked = await sender_registry.sender_for("plugin:chzero:alerts").send(
            plugin_channels.NotifyEvent(type_id="test", kind="test", title="Hi", ts=1.0), {}, {}
        )
        assert blocked.ok is False
        assert blocked.failure == FailureClass.BLOCKED

        plugin_channels.sync_all(host, [d_t0, d_idle, d_bi])
        assert kind_specs.get_kind("plugin:chzero:alerts") is None
        assert sender_registry.sender_for("plugin:chzero:alerts") is None
    finally:
        for pid in ("chzero", "chidle", "chbuilt"):
            _cleanup_plugin(pid)


def test_universal_harnesses_tier0_idle_sidecar_builtin_and_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    owner_switch.write(state_dir, True)
    host = host_runtime.Host(state_dir, publish=lambda _t: None)

    t0_dir = tmp_path / "h_t0"
    _write_v2_plugin(t0_dir, "hzero", with_channel=False)
    m_t0 = load_sidecar_manifest(t0_dir, "hzero")
    d_t0 = SidecarDefinition(manifest=m_t0, item_id="acme/hzero", install_key="inst-hzero", code_root=t0_dir, folder=tmp_path / "dh0")
    owner_state.update(state_dir, m_t0, None, lambda st: replace(st, enabled=True, grants=(), digest=m_t0.code_digest))

    idle_dir = tmp_path / "h_idle"
    _write_v2_plugin(idle_dir, "hidle", run_cmd=["python3", "main.py"], with_channel=False)
    (idle_dir / "main.py").write_text("# stub\n", encoding="utf-8")
    m_idle = load_sidecar_manifest(idle_dir, "hidle")
    d_idle = SidecarDefinition(manifest=m_idle, item_id="acme/hidle", install_key="inst-hidle", code_root=idle_dir, folder=tmp_path / "dh1")
    owner_state.update(state_dir, m_idle, None, lambda st: replace(st, enabled=True, grants=(), digest=m_idle.code_digest))

    bi_dir = tmp_path / "h_built"
    _write_v2_plugin(bi_dir, "hbuilt", tier="builtin", with_channel=False)
    (bi_dir / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    m_bi = load_manifest(str(bi_dir / "__init__.py"))
    d_bi = CplugDefinition(manifest=m_bi, code_root=bi_dir)
    owner_state.update(state_dir, m_bi, None, lambda st: replace(st, enabled=True))

    sup = Supervisor(state_dir, "1.0.0", lambda *_a: None, lambda *_a: None, lambda *_a: None, lambda *_a: None, safe_mode=False)
    sup._state["hidle"] = "idle"

    try:
        plugin_channels.sync_all(host, [d_t0, d_idle, d_bi], safe_mode_active=False, supervisor=sup)
        ids = {m.id for m in harness_engine.manifests()}
        assert {"agent_hzero", "agent_hidle", "agent_hbuilt"} <= ids

        plugin_channels.sync_all(host, [d_t0, d_idle, d_bi], safe_mode_active=True, supervisor=sup)
        ids_safe = {m.id for m in harness_engine.manifests()}
        assert "agent_hzero" not in ids_safe
        assert "agent_hidle" not in ids_safe
        assert "agent_hbuilt" in ids_safe

        sup._paused.add("hidle")
        plugin_channels.sync_all(host, [d_t0, d_idle, d_bi], safe_mode_active=False, supervisor=sup)
        ids_paused = {m.id for m in harness_engine.manifests()}
        assert "agent_hzero" in ids_paused
        assert "agent_hidle" not in ids_paused

        owner_state.update(state_dir, m_bi, None, lambda st: replace(st, enabled=False))
        plugin_channels.sync_plugin(host, d_bi, safe_mode_active=False, supervisor=sup)
        assert "agent_hbuilt" not in {m.id for m in harness_engine.manifests()}
    finally:
        for pid in ("hzero", "hidle", "hbuilt"):
            _cleanup_plugin(pid)


@pytest.mark.asyncio
async def test_declarative_channel_real_plugin_fetch_refusals_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    owner_switch.write(state_dir, True)
    host = host_runtime.Host(state_dir, publish=lambda _t: None)

    plug_dir = tmp_path / "ssrf_plug"
    _write_v2_plugin(plug_dir, "ssrfplug", with_harness=False)
    m = load_sidecar_manifest(plug_dir, "ssrfplug")
    defn = SidecarDefinition(
        manifest=m,
        item_id="acme/ssrfplug",
        install_key="inst-ssrfplug",
        code_root=plug_dir,
        folder=tmp_path / "d_ssrf",
    )
    owner_state.update(state_dir, m, None, lambda st: replace(st, enabled=True, grants=(), digest=m.code_digest))

    fake_reg = SimpleNamespace(listed=lambda: [defn], find=lambda pid: defn if pid == "ssrfplug" else None)
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: defn if pid == "ssrfplug" else None)
    monkeypatch.setattr(host_runtime, "find", lambda pid: defn if pid == "ssrfplug" else None)
    monkeypatch.setattr(host_runtime, "listed", lambda: (defn,))

    dest = DestinationView(
        id="d_000000000099",
        kind="plugin:ssrfplug:alerts",
        name="SSRF",
        enabled=True,
        scope="global",
        config={},
        details=True,
    )
    dest_dns = DestinationView(
        id="d_000000000100",
        kind="plugin:ssrfplug:alerts",
        name="SSRF DNS",
        enabled=True,
        scope="global",
        config={},
        details=True,
    )
    monkeypatch.setattr("src.core.notifications.engine.current_view", lambda: SimpleNamespace(destinations=lambda: [dest, dest_dns]))

    async def _secrets(_id: str) -> Dict[str, str]:
        return {}

    try:
        plugin_channels.sync_all(host, [defn])
        sender = sender_registry.sender_for("plugin:ssrfplug:alerts")
        assert sender is not None
        ev = plugin_channels.NotifyEvent(type_id="test", kind="test", title="Hi", ts=1.0)

        res_ungranted = await sender.send(ev, {}, {})
        assert res_ungranted.ok is False
        assert res_ungranted.failure == FailureClass.BLOCKED
        assert res_ungranted.detail == "permission_denied"

        engine = NotifyEngine(sender_lookup=sender_registry.sender_for, secrets_lookup=_secrets, is_muted=lambda _s, _t: False)
        out_ungranted = await engine.send_test("d_000000000099")
        assert out_ungranted.result is not None
        assert out_ungranted.result.ok is False
        assert out_ungranted.result.failure == FailureClass.BLOCKED
        assert out_ungranted.result.detail == "permission_denied"

        monkeypatch.setattr(netguard, "_peer_cache", [time.monotonic() + 60.0, netguard.Peers(set(), True)])
        owner_state.update(
            state_dir,
            m,
            None,
            lambda st: replace(st, enabled=True, grants=tuple(m.permissions), digest=m.code_digest),
        )
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        )
        res_dns = await sender.send(ev, {}, {})
        assert res_dns.ok is False
        assert res_dns.failure == FailureClass.BLOCKED
        assert res_dns.detail == "address_never"
        out_dns = await engine.send_test("d_000000000100")
        assert out_dns.result is not None and out_dns.result.failure == FailureClass.BLOCKED
        assert out_dns.result.detail == "address_never"

        ip_sender = plugin_channels.PluginChannelSender(
            host,
            "ssrfplug",
            "ipops",
            {"url": "http://127.0.0.1:8080/x", "method": "POST"},
        )
        res_ip = await ip_sender.send(ev, {}, {})
        assert res_ip.ok is False
        assert res_ip.failure == FailureClass.BLOCKED
        assert res_ip.detail == "ip_literal"

        act = activity_log.ActivityLog(state_dir).recent(host.install_key("ssrfplug"), 20)
        statuses = [r["status"] for r in act if r["method"] == "channel.send"]
        assert "permission_denied" in statuses
        assert "address_never" in statuses
        assert "ip_literal" in statuses
        caps = inspector_telemetry.telemetry_for(state_dir).capability_checks("ssrfplug", 20)
        reasons = [c["reason"] for c in caps if c["allowed"] is False]
        assert {"permission_denied", "address_never", "ip_literal"} <= set(reasons)
    finally:
        _cleanup_plugin("ssrfplug")


def test_failure_from_refused_and_secret_error_mappings(tmp_path: Path) -> None:
    assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused("rate_limited")) == FailureClass.RATE_LIMITED
    assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused("timeout")) == FailureClass.TIMEOUT
    assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused("upstream_error")) == FailureClass.NETWORK
    assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused("dns_failed")) == FailureClass.NETWORK
    assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused("secret_missing")) == FailureClass.SECRET_MISSING
    for invalid_code in ("bad_url", "bad_header", "body_not_allowed", "request_too_large", "response_too_large"):
        assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused(invalid_code)) == FailureClass.INVALID
    assert plugin_channels._failure_from_refused(guards.Refused("permission_denied", "no")) == FailureClass.BLOCKED
    assert plugin_channels._failure_from_refused(fetch_proxy.FetchRefused("private_address")) == FailureClass.BLOCKED

    state_dir = tmp_path / "sec_state"
    state_dir.mkdir()
    owner_switch.write(state_dir, True)
    host = host_runtime.Host(state_dir, publish=lambda _t: None)
    plug_dir = tmp_path / "sec_plug"
    _write_v2_plugin(plug_dir, "secplug", with_harness=False)
    m = load_sidecar_manifest(plug_dir, "secplug")
    defn = SidecarDefinition(manifest=m, item_id="acme/secplug", install_key="inst-secplug", code_root=plug_dir, folder=tmp_path / "d_sec")
    owner_state.update(state_dir, m, None, lambda st: replace(st, enabled=True, grants=tuple(m.permissions), digest=m.code_digest))

    class _LockedProxy:
        async def fetch(self, *_a, **_kw):
            raise secret_store.SecretError("secrets_unreadable", "locked")

    host.fetch_for = lambda _pid: _LockedProxy()
    sender = plugin_channels.PluginChannelSender(host, "secplug", "alerts", {"url": "https://hooks.example.com/alert"})
    orig_find = sidecar_registry.find
    sidecar_registry.find = lambda pid: defn if pid == "secplug" else orig_find(pid)
    try:
        import asyncio as _asyncio

        res = _asyncio.run(sender.send(plugin_channels.NotifyEvent(type_id="t", kind="t", title="Hi", ts=1.0), {}, {}))
        assert res.ok is False
        assert res.failure == FailureClass.KEYCHAIN_LOCKED
        assert res.detail == "secrets_unreadable"
    finally:
        sidecar_registry.find = orig_find


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_channel_send_live_darwin_sandbox_rpc_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_dir = tmp_path / "rpc_ch_plug"
    _write_v2_plugin(code_dir, "chrpc", run_cmd=["python3", "main.py"], with_harness=False)
    (code_dir / "main.py").write_text(
        """from cplug_sdk import Plugin

plugin = Plugin()

@plugin.channel("alerts")
async def send_alert(event, config):
    if config.get("force_fail"):
        return {"ok": False, "failure": "auth", "status_code": 401, "detail": "bad_token"}
    return {"ok": True, "status_code": 202, "detail": f"sent:{event.get('title', '')}"}
""",
        encoding="utf-8",
    )
    m = load_sidecar_manifest(code_dir, "chrpc")
    data_dir = state_dir / "cplugs" / "inst-chrpc"
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(manifest=m, item_id="acme/chrpc", install_key="inst-chrpc", code_root=code_dir, folder=data_dir)
    owner_state.update(state_dir, m, None, lambda st: replace(st, enabled=True, grants=tuple(m.permissions), digest=m.code_digest))

    fake_reg = SimpleNamespace(listed=lambda: [defn], find=lambda pid: defn if pid == "chrpc" else None)
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: defn if pid == "chrpc" else None)
    monkeypatch.setattr(host_runtime, "find", lambda pid: defn if pid == "chrpc" else None)
    monkeypatch.setattr(host_runtime, "listed", lambda: (defn,))

    owner_switch.write(state_dir, True)
    host = host_runtime.Host(state_dir, publish=lambda _t: None)
    rt = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    rt.supervisor.override_index("chrpc", True)
    host.sidecar_runtime = lambda: rt

    dest_ok = DestinationView(id="d_000000000101", kind="plugin:chrpc:alerts", name="RPC OK", enabled=True, scope="global", config={}, details=True)
    dest_fail = DestinationView(
        id="d_000000000102",
        kind="plugin:chrpc:alerts",
        name="RPC Fail",
        enabled=True,
        scope="global",
        config={"force_fail": True},
        details=True,
    )
    monkeypatch.setattr("src.core.notifications.engine.current_view", lambda: SimpleNamespace(destinations=lambda: [dest_ok, dest_fail]))

    async def _secrets(_id: str) -> Dict[str, str]:
        return {}

    try:
        await rt.supervisor.activate(host.sidecar_spec(defn))
        plugin_channels.sync_all(host, [defn], safe_mode_active=False, supervisor=rt.supervisor, tier0_registry=rt.tier0_channels)

        engine = NotifyEngine(sender_lookup=sender_registry.sender_for, secrets_lookup=_secrets, is_muted=lambda _s, _t: False)
        out_ok = await engine.send_test("d_000000000101")
        assert out_ok.result is not None
        assert out_ok.result.ok is True
        assert out_ok.result.status_code == 202
        assert out_ok.result.detail == "sent:carnivore test notification"

        out_fail = await engine.send_test("d_000000000102")
        assert out_fail.result is not None
        assert out_fail.result.ok is False
        assert out_fail.result.failure == FailureClass.AUTH
        assert out_fail.result.status_code == 401
        assert out_fail.result.detail == "bad_token"

        act = activity_log.ActivityLog(state_dir).recent(host.install_key("chrpc"), 20)
        ch_rows = [r for r in act if r["method"] == "channel.send"]
        assert any(r["status"] == "ok" for r in ch_rows)
        assert any(r["status"] == "failed" for r in ch_rows)
        caps = inspector_telemetry.telemetry_for(state_dir).capability_checks("chrpc", 20)
        assert any(c["permission"] == "channel:alerts" and c["allowed"] is True for c in caps)
        assert any(c["permission"] == "channel:alerts" and c["allowed"] is False and c["reason"] == "bad_token" for c in caps)
    finally:
        await rt.stop()
        _cleanup_plugin("chrpc")


@pytest.mark.asyncio
async def test_builtin_channels_harnesses_and_slots_survive_host_start_and_sidecar_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    owner_switch.write(state_dir, True)

    bi_dir = tmp_path / "bi_survive"
    _write_v2_plugin(bi_dir, "bisurvive", tier="builtin", with_channel=True, with_harness=True)
    raw_bi = json.loads((bi_dir / "carnivore.json").read_text(encoding="utf-8"))
    raw_bi["ui"] = {"slots": ["bisurvive.zone"]}
    (bi_dir / "carnivore.json").write_text(json.dumps(raw_bi), encoding="utf-8")
    (bi_dir / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    m_bi = load_manifest(str(bi_dir / "__init__.py"))
    d_bi = CplugDefinition(manifest=m_bi, code_root=bi_dir)
    owner_state.update(state_dir, m_bi, None, lambda st: replace(st, enabled=True, grants=tuple(m_bi.permissions)))

    sc_dir = tmp_path / "sc_survive"
    _write_v2_plugin(sc_dir, "scsurvive", with_channel=True, with_harness=True)
    m_sc = load_sidecar_manifest(sc_dir, "scsurvive")
    d_sc = SidecarDefinition(manifest=m_sc, item_id="acme/scsurvive", install_key="inst-scsurvive", code_root=sc_dir, folder=tmp_path / "d_sc")
    owner_state.update(state_dir, m_sc, None, lambda st: replace(st, enabled=True, grants=tuple(m_sc.permissions), digest=m_sc.code_digest))

    monkeypatch.setattr(host_runtime, "definitions", lambda: (d_bi,))
    host = host_runtime.Host(state_dir, publish=lambda _t: None)
    rt = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop(), env_safe=lambda: False)
    rt._ledger_rows = lambda: []

    orig_reg = sidecar_registry.current()
    try:
        count = rt.load_registry()
        assert count == 0
        assert kind_specs.get_kind("plugin:bisurvive:alerts") is not None
        assert sender_registry.sender_for("plugin:bisurvive:alerts") is not None
        assert "agent_bisurvive" in {m.id for m in harness_engine.manifests()}
        assert ui_slots.registry_for(state_dir).resolve(host=host, definitions=host.listed())["owners"].get("bisurvive.zone") == "bisurvive"

        await rt.activate_enabled()
        assert kind_specs.get_kind("plugin:bisurvive:alerts") is not None
        assert "agent_bisurvive" in {m.id for m in harness_engine.manifests()}
        assert ui_slots.registry_for(state_dir).resolve(host=host, definitions=host.listed())["owners"].get("bisurvive.zone") == "bisurvive"

        fake_reg = SimpleNamespace(listed=lambda: (d_sc,), find=lambda pid: d_sc if pid == "scsurvive" else None)
        sidecar_registry.install(fake_reg)
        await host.start()
        assert kind_specs.get_kind("plugin:bisurvive:alerts") is not None
        assert kind_specs.get_kind("plugin:scsurvive:alerts") is not None
        assert {"agent_bisurvive", "agent_scsurvive"} <= {m.id for m in harness_engine.manifests()}
    finally:
        sidecar_registry.install(orig_reg)
        for pid in ("bisurvive", "scsurvive"):
            _cleanup_plugin(pid)


def test_pause_cplug_unregisters_channels_harnesses_and_slots_for_tier0_and_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    owner_switch.write(state_dir, True)

    t0_dir = tmp_path / "pause_t0"
    _write_v2_plugin(t0_dir, "pauset0", with_channel=True, with_harness=True)
    raw_t0 = json.loads((t0_dir / "carnivore.json").read_text(encoding="utf-8"))
    raw_t0["permissions"]["reasons"] = {"ui.slot:terminal.toolbar": "Toolbar button"}
    raw_t0["ui"] = {"slots": ["pauset0.zone"], "contribute": {"terminal.toolbar": [{"id": "t0btn", "label": "T0"}]}}
    (t0_dir / "carnivore.json").write_text(json.dumps(raw_t0), encoding="utf-8")
    m_t0 = load_sidecar_manifest(t0_dir, "pauset0")
    d_t0 = SidecarDefinition(manifest=m_t0, item_id="acme/pauset0", install_key="inst-pauset0", code_root=t0_dir, folder=tmp_path / "d_pt0")
    owner_state.update(
        state_dir,
        m_t0,
        None,
        lambda st: replace(st, enabled=True, grants=tuple(m_t0.permissions), ui_slot_grants=("terminal.toolbar",), digest=m_t0.code_digest),
    )

    idle_dir = tmp_path / "pause_idle"
    _write_v2_plugin(idle_dir, "pauseidle", run_cmd=["python3", "main.py"], with_channel=True, with_harness=True)
    (idle_dir / "main.py").write_text("# stub\n", encoding="utf-8")
    raw_idle = json.loads((idle_dir / "carnivore.json").read_text(encoding="utf-8"))
    raw_idle["permissions"]["reasons"] = {"ui.slot:terminal.toolbar": "Toolbar button"}
    raw_idle["ui"] = {"slots": ["pauseidle.zone"], "contribute": {"terminal.toolbar": [{"id": "idlebtn", "label": "Idle"}]}}
    (idle_dir / "carnivore.json").write_text(json.dumps(raw_idle), encoding="utf-8")
    m_idle = load_sidecar_manifest(idle_dir, "pauseidle")
    d_idle = SidecarDefinition(manifest=m_idle, item_id="acme/pauseidle", install_key="inst-pauseidle", code_root=idle_dir, folder=tmp_path / "d_pidle")
    owner_state.update(
        state_dir,
        m_idle,
        None,
        lambda st: replace(st, enabled=True, grants=tuple(m_idle.permissions), ui_slot_grants=("terminal.toolbar",), digest=m_idle.code_digest),
    )

    defs = [d_t0, d_idle]
    by_id = {d.id: d for d in defs}
    fake_reg = SimpleNamespace(listed=lambda: list(defs), find=lambda pid: by_id.get(pid))
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: by_id.get(pid))
    monkeypatch.setattr(host_runtime, "find", lambda pid: by_id.get(pid))
    monkeypatch.setattr(host_runtime, "listed", lambda: tuple(defs))

    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    app.include_router(host_routes.router, prefix="/api/v1")
    published: List[str] = []
    host = host_runtime.Host(state_dir, app=app, publish=published.append)
    app.state.cplugs_host = host

    loop = asyncio.new_event_loop()
    rt = sidecar_boot.SidecarRuntime(host, app, loop, env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    rt.supervisor._state["pauset0"] = "tier0"
    rt.supervisor._state["pauseidle"] = "idle"
    app.state.sidecar_runtime = rt
    client = TestClient(app)

    try:
        plugin_channels.sync_all(host, defs, safe_mode_active=False, supervisor=rt.supervisor, tier0_registry=rt.tier0_channels)
        reg = ui_slots.registry_for(state_dir)
        reg.publish("pauset0", "terminal.toolbar", [{"id": "dyn_t0", "label": "Dyn T0"}], host=host, definitions=defs, safe_mode_active=False, supervisor=rt.supervisor)
        reg.publish("pauseidle", "terminal.toolbar", [{"id": "dyn_idle", "label": "Dyn Idle"}], host=host, definitions=defs, safe_mode_active=False, supervisor=rt.supervisor)

        for pid, slot_name in (("pauset0", "pauset0.zone"), ("pauseidle", "pauseidle.zone")):
            assert kind_specs.get_kind(f"plugin:{pid}:alerts") is not None
            assert sender_registry.sender_for(f"plugin:{pid}:alerts") is not None
            assert f"agent_{pid}" in {hm.id for hm in harness_engine.manifests()}
            assert reg._owners.get(slot_name) == pid

            r = client.post(f"/api/v1/cplugs/{pid}/pause")
            assert r.status_code == 200, r.text
            assert r.json()["paused"] is True
            assert kind_specs.get_kind(f"plugin:{pid}:alerts") is None
            assert sender_registry.sender_for(f"plugin:{pid}:alerts") is None
            assert f"agent_{pid}" not in {hm.id for hm in harness_engine.manifests()}
            assert slot_name not in reg._owners
            assert (pid, "terminal.toolbar") not in reg._dynamic

        for bad_state in ("killed", "index_expired", "disabled (safe mode)"):
            assert bad_state in plugin_channels._BAD_SUPERVISOR_STATES
            assert bad_state in ui_slots._BAD_SUPERVISOR_STATES
    finally:
        loop.close()
        for pid in ("pauset0", "pauseidle"):
            _cleanup_plugin(pid)
