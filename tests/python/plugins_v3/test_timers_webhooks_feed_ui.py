
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core import session_change_notice
from src.core.session_output.tap import TAP
from src.plugins.host import feed_fanout, routes as plugin_routes, runtime, secret_store, webhook_routes
from src.plugins.host.plugin_manifest import SidecarManifest, load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_spec import build_spec
from src.plugins.runtime import sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import FEED_GRANTS
from src.plugins.runtime.supervisor import Supervisor
from src.plugins.runtime.timers import MIN_INTERVAL_SECONDS, TimerScheduler
from src.plugins.runtime.webhooks import sign
from src.plugins.sdk.network import NetworkDecl, Secret
from src.plugins.sdk_py import testing as sdk_testing
from src.plugins.sdk_py.plugin import Plugin


@pytest.mark.asyncio
async def test_timer_scheduler_coalescing_min_interval_and_cancel() -> None:
    calls: List[Tuple[str, str, int]] = []
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def send_tick(pid: str, name: str, scheduled_for: int) -> None:
        calls.append((pid, name, scheduled_for))
        entered.set()
        await gate.wait()

    sched = TimerScheduler(send_tick, min_interval=1, clock=lambda: 1700000000.0)
    assert TimerScheduler(send_tick)._min_interval == MIN_INTERVAL_SECONDS

    try:
        armed = sched.arm("p1", {"beat": 1})
        assert armed == 1
        assert sched.active_count("p1") == 1
        await asyncio.wait_for(entered.wait(), timeout=3.0)
        assert sched.in_flight("p1", "beat") is True
        await asyncio.sleep(1.2)
        assert len(calls) == 1
        gate.set()
        await asyncio.sleep(0.05)
        assert sched.in_flight("p1", "beat") is False
        assert sched.cancel_for("p1") == 1
        assert sched.active_count("p1") == 0
    finally:
        await sched.stop_all()


@pytest.mark.asyncio
async def test_sdk_ui_decorator_and_testing_helper() -> None:
    plugin = Plugin()

    @plugin.ui("widget")
    async def draw_widget(params: Dict[str, Any]) -> Dict[str, Any]:
        return {"schema": 1, "root": {"type": "text", "value": f"hi {params.get('who', 'world')}"}}

    res = await sdk_testing.render_ui(plugin, "widget", {"who": "alice"})
    assert res == {"document": {"schema": 1, "root": {"type": "text", "value": "hi alice"}}}

    with pytest.raises(KeyError):
        await plugin.handle("ui.render", {"surface": "tab", "params": {}})


def _setup_webhook_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest = SidecarManifest(
        id="hooker",
        name="Hooker",
        description="Webhook plugin",
        version="1.0.0",
        entry="main.py",
        tools=({"name": "echo_tool", "description": "Echo", "gate": "read", "inputSchema": {"type": "object"}},),
        permissions=("hooks.inbound:ci",),
        network=NetworkDecl(secrets=(Secret(name="HOOK_SEC", label="Hook", help="Webhook HMAC"),)),
        code_digest="c" * 64,
        webhooks={"ci": {"hmac_secret": "HOOK_SEC"}},
    )
    defn = SidecarDefinition(
        manifest=manifest,
        item_id="acme/hooker",
        install_key="k-hooker",
        code_root=tmp_path / "code",
        folder=tmp_path / "data",
    )
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(plugin_routes.router, prefix="/api/v1")

    host = runtime.Host(tmp_path, app=app)
    monkeypatch.setattr(runtime, "host_for", lambda _app: host)
    monkeypatch.setattr(runtime, "find", lambda pid: defn if pid == "hooker" else None)
    monkeypatch.setattr(runtime, "hidden", lambda _d: False)
    monkeypatch.setattr(host, "enabled", lambda pid: pid == "hooker")
    monkeypatch.setattr(host, "install_key", lambda pid: "k-hooker")
    monkeypatch.setattr(host, "_live_grants", lambda _m: frozenset({"hooks.inbound:ci"}))

    delivered: List[Tuple[str, str, int, Any]] = []

    class _FakeSupervisor:
        def state(self, _pid: str) -> str:
            return "running"

        async def ensure(self, _pid: str):
            return _FakeProc()

        async def deliver_event(self, pid: str, family: str, seq: int, payload: Any) -> bool:
            delivered.append((pid, family, seq, payload))
            return True

    class _FakeProc:
        ended = None

        async def request(self, method: str, params: Dict[str, Any], timeout: float = 5.0) -> Any:
            return {"content": [{"type": "text", "text": f"tool:{params['name']}:{params['arguments']}"}]}

    live = SimpleNamespace(
        safe_mode=lambda: {"env": False, "owner": False, "off": False},
        supervisor=_FakeSupervisor(),
        tokens=SimpleNamespace(mint=lambda k, r: f"tok:{k}:{r}"),
    )
    app.state.sidecar_runtime = live

    mem_kc: Dict[Tuple[str, str], str] = {}

    class _FakeKC:
        def read(self, svc, acc):
            return mem_kc.get((svc, acc))

        def write(self, svc, acc, val):
            mem_kc[(svc, acc)] = val

        def delete(self, svc, acc):
            return mem_kc.pop((svc, acc), None) is not None

    monkeypatch.setattr(secret_store, "_Login", _FakeKC)
    secret_store.SecretStore(tmp_path).set("k-hooker", manifest, "HOOK_SEC", "s" * 32)
    webhook_routes.clear_install("k-hooker")
    return app, delivered


def test_webhook_route_preserves_2651_checks_and_trusted_proxy_ip_ratelimit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, delivered = _setup_webhook_app(tmp_path, monkeypatch)
    client = TestClient(app)

    body = json.dumps({"event": "push"}).encode("utf-8")
    now = int(time.time())
    sig = sign(b"s" * 32, now, "nonce-1", body)
    r_before = client.post(
        "/api/v1/cplugs/hooker/webhook/ci",
        content=body,
        headers={"x-timestamp": str(now), "x-nonce": "nonce-1", "x-signature": sig},
    )
    assert r_before.status_code == 401
    assert r_before.json()["detail"]["code"] == "before_start"

    verifier = webhook_routes._verifiers["k-hooker"]
    verifier._started = now - 40

    r_ok = client.post(
        "/api/v1/cplugs/hooker/webhook/ci",
        content=body,
        headers={"x-timestamp": str(now), "x-nonce": "nonce-1", "x-signature": sig},
    )
    assert r_ok.status_code == 202
    assert len(delivered) == 1
    assert delivered[0][1] == "webhook.ci"
    assert delivered[0][3]["payload"] == {"event": "push"}

    r_replay = client.post(
        "/api/v1/cplugs/hooker/webhook/ci",
        content=body,
        headers={"x-timestamp": str(now), "x-nonce": "nonce-1", "x-signature": sig},
    )
    assert r_replay.status_code == 401
    assert r_replay.json()["detail"]["code"] == "replay"

    monkeypatch.setattr("src.core.mcp.trusted_proxy.configured", lambda: ["192.0.2.11"])
    req_untrusted = SimpleNamespace(client=SimpleNamespace(host="203.0.113.5"), headers={"x-forwarded-for": "1.2.3.4"})
    assert webhook_routes.client_ip_for(req_untrusted) == "203.0.113.5"

    req_trusted = SimpleNamespace(client=SimpleNamespace(host="192.0.2.11"), headers={"x-forwarded-for": "198.51.100.7, 192.0.2.11"})
    assert webhook_routes.client_ip_for(req_trusted) == "198.51.100.7"

    assert webhook_routes.clear_install("k-hooker") == 1


def test_owner_tool_route_immediate_and_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, _delivered = _setup_webhook_app(tmp_path, monkeypatch)
    client = TestClient(app)

    r_ok = client.post(
        "/api/v1/cplug-owner/tool",
        json={"cplug_id": "hooker", "tool": "echo_tool", "args": {"hello": "world"}},
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["ok"] is True
    assert "echo_tool" in r_ok.json()["text"]

    r_404 = client.post(
        "/api/v1/cplug-owner/tool",
        json={"cplug_id": "hooker", "tool": "missing_tool", "args": {}},
    )
    assert r_404.status_code == 404


@pytest.mark.asyncio
async def test_feed_fanout_subscribes_lazily_and_scrubs_output(tmp_path: Path) -> None:
    assert "feed.view: meta" in FEED_GRANTS["feed.meta"]
    assert "feed.view: scrubbed" in FEED_GRANTS["feed.scrubbed"]
    assert "feed.view: raw" in FEED_GRANTS["feed.raw"]

    delivered: List[Tuple[str, str, int, Any]] = []

    async def deliver(pid: str, family: str, seq: int, payload: Any) -> bool:
        delivered.append((pid, family, seq, payload))
        return True

    subs: Dict[str, List[str]] = {"feed.meta": [], "feed.scrubbed": [], "feed.raw": []}
    fanout = feed_fanout.FeedFanout(deliver, lambda fam: list(subs[fam]))
    base_tap_count = TAP.observer_count()
    fanout.refresh()
    assert TAP.observer_count() == base_tap_count

    subs["feed.scrubbed"] = ["p-scrub"]
    subs["feed.meta"] = ["p-meta"]
    fanout.refresh()
    assert TAP.observer_count() == base_tap_count + 1

    try:
        fake_secret = "sk-ant-api03-" + ("X9y8Z7w6V5" * 4)
        TAP.emit("ses_feed1", f"\x1b[31mhi\x1b[0m {fake_secret}\n".encode("utf-8"))
        session_change_notice.publish(None, session_change_notice.build_structural_notice("created"))
        for _ in range(40):
            if len(delivered) >= 2:
                break
            await asyncio.sleep(0.02)
        scrub_events = [d for d in delivered if d[1] == "feed.scrubbed"]
        meta_events = [d for d in delivered if d[1] == "feed.meta"]
        assert len(scrub_events) == 1
        assert "\x1b[" not in scrub_events[0][3]["text"]
        assert fake_secret not in scrub_events[0][3]["text"]
        assert len(meta_events) == 1
        assert meta_events[0][3]["reason"] == "created"
    finally:
        await fanout.stop()
        assert TAP.observer_count() == base_tap_count


def test_fail_limiter_prunes_expired_keys() -> None:
    limiter = webhook_routes.FailLimiter(limit=5, window_s=0.05, max_keys=4)
    for i in range(4):
        limiter.record_failure("k1", f"198.51.100.{i}")
    assert len(limiter._hits) == 4
    time.sleep(0.06)
    limiter.record_failure("k1", "198.51.100.99")
    assert list(limiter._hits.keys()) == [("k1", "198.51.100.99")]


@pytest.mark.asyncio
async def test_webhook_route_delivers_to_real_supervisor_without_events_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        sandbox.find_interpreter()
        sandbox_ok = sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists()
    except sandbox.SandboxUnavailable:
        sandbox_ok = False
    if not sandbox_ok:
        pytest.skip("needs macOS sandbox-exec and framework Python")

    code = tmp_path / "code" / "hookreal"
    code.mkdir(parents=True, exist_ok=True)
    (code / "main.py").write_text(
        """
from cplug_sdk import Plugin

plugin = Plugin()

@plugin.on_event("webhook.ci")
async def on_ci(seq, payload):
    await plugin.host.storage.put(key="last_hook", value={"seq": seq, "payload": payload})
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "hookreal"
name = "Hook Real"
version = "1.0.0"
kind = "plugin"
description = "Real Supervisor webhook plugin without events.on"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[permissions]
secrets = [{ name = "HOOK_SEC", label = "Hook Secret", help = "Webhook HMAC" }]

[webhooks.ci]
hmac_secret = "HOOK_SEC"
""",
        encoding="utf-8",
    )

    sm = load_sidecar_manifest(code, "hookreal")
    assert "webhook.ci" in sm.subscriptions

    install_key = "c" * 32
    data_dir = tmp_path / "state" / "cplugs" / install_key
    data_dir.mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(manifest=sm, item_id="acme/hookreal", install_key=install_key, code_root=code, folder=data_dir)
    spec = build_spec(defn, frozenset({"hooks.inbound:ci"}), settings={})

    activity: List[Dict[str, Any]] = []
    dispatcher = HostDispatcher(HostServices(activity=activity.append), OwnerTokens(), home=tmp_path / "home")
    sup = Supervisor(
        tmp_path / "state",
        "9.9.9",
        dispatcher,
        lambda _pid, _k, _why: None,
        lambda _pid: {"inbox": 0, "timers": 0, "routes": 0},
        activity.append,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )

    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(plugin_routes.router, prefix="/api/v1")
    host = runtime.Host(tmp_path / "state", app=app)
    monkeypatch.setattr(runtime, "host_for", lambda _app: host)
    monkeypatch.setattr(runtime, "find", lambda pid: defn if pid == "hookreal" else None)
    monkeypatch.setattr(runtime, "hidden", lambda _d: False)
    monkeypatch.setattr(host, "enabled", lambda pid: pid == "hookreal")
    monkeypatch.setattr(host, "install_key", lambda pid: install_key)
    monkeypatch.setattr(host, "_live_grants", lambda _m: frozenset({"hooks.inbound:ci"}))

    mem_kc: Dict[Tuple[str, str], str] = {}

    class _FakeKC:
        def read(self, svc, acc):
            return mem_kc.get((svc, acc))

        def write(self, svc, acc, val):
            mem_kc[(svc, acc)] = val

        def delete(self, svc, acc):
            return mem_kc.pop((svc, acc), None) is not None

    monkeypatch.setattr(secret_store, "_Login", _FakeKC)
    secret_store.SecretStore(tmp_path / "state").set(install_key, sm, "HOOK_SEC", "s" * 32)
    webhook_routes.clear_install(install_key)

    app.state.sidecar_runtime = SimpleNamespace(
        safe_mode=lambda: {"env": False, "owner": False, "off": False},
        supervisor=sup,
        tokens=OwnerTokens(),
    )

    try:
        assert await sup.activate(spec) == "running"
        verifier = webhook_routes._verifier_for(install_key)
        now = int(time.time())
        verifier._started = now - 40
        body = json.dumps({"build": 42}).encode("utf-8")
        sig = sign(b"s" * 32, now, "nonce-real-1", body)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/cplugs/hookreal/webhook/ci",
                content=body,
                headers={"x-timestamp": str(now), "x-nonce": "nonce-real-1", "x-signature": sig},
            )
        assert resp.status_code == 202
        assert resp.json() == {"ok": True, "delivered": True}

        for _ in range(40):
            stored = dispatcher.storage(spec.ctx).get("last_hook")
            if stored is not None:
                break
            await asyncio.sleep(0.05)
        assert stored == {"seq": 1, "payload": {"hook": "ci", "payload": {"build": 42}}}
    finally:
        webhook_routes.clear_install(install_key)
        await sup.shutdown()
