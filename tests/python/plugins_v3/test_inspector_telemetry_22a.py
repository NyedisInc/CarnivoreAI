
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.core.db_migration import ensure_db_migrated
from src.core.resource_push.topics import CPLUG_INSPECTOR, RESOURCE_TOPICS
from src.plugins.host import dev_stream, inspector_telemetry, runtime, sidecar_boot, sidecar_registry
from src.plugins.host.plugin_manifest import SidecarManifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.sdk.manifest import NetworkDecl
from src.plugins.runtime import guards, watchdog
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import PluginContext, PluginSpec
from src.plugins.runtime.supervisor import Supervisor
from tests.python.api_keys.conftest import bearer, owner_jwt  # noqa: F401


def test_cplug_inspector_topic_registered_and_dispatcher_records_rpc_and_cli_sock(tmp_path: Path) -> None:
    assert CPLUG_INSPECTOR == "cplug_inspector"
    assert CPLUG_INSPECTOR in RESOURCE_TOPICS

    pushed: list[str] = []
    tel = inspector_telemetry.InspectorTelemetry(tmp_path, publish=pushed.append)
    tel.set_aliases("demo", "uuid-demo")

    async def _list_sessions() -> list[dict[str, Any]]:
        return [{"id": "s1", "uuid": "s1", "title": "Main", "state": "idle"}]

    svc = HostServices(activity=lambda _row: None, list_sessions=_list_sessions)
    disp = HostDispatcher(svc, OwnerTokens(), trace_sink=tel.record_event)
    ctx = PluginContext(plugin_id="demo", install_key="uuid-demo", data_dir=tmp_path, granted=frozenset({"sessions.read"}))

    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(disp.handle(ctx, "sessions.list", {}, source="rpc"))
        assert len(res["sessions"]) == 1
        assert res["sessions"][0]["id"] == "s1"

        with pytest.raises(guards.Refused) as exc_denied:
            loop.run_until_complete(disp.handle(ctx, "sessions.output", {"ref": "s1"}, source="cli_sock"))
        assert exc_denied.value.code == "not_granted"
    finally:
        loop.close()

    traces = tel.rpc_trace("demo")
    assert len(traces) == 2
    assert traces[0]["source"] == "rpc" and traces[0]["method"] == "sessions.list" and traces[0]["ok"] is True
    assert traces[1]["source"] == "cli_sock" and traces[1]["method"] == "sessions.output" and traces[1]["ok"] is False
    assert traces[1]["error_code"] == "not_granted"

    caps = tel.capability_checks("demo")
    assert len(caps) == 2
    assert caps[0]["permission"] == "sessions.read" and caps[0]["allowed"] is True
    assert caps[1]["permission"] == "sessions.output" and caps[1]["allowed"] is False
    assert f"{CPLUG_INSPECTOR}:demo" in pushed
    assert f"{CPLUG_INSPECTOR}:uuid-demo" in pushed


def test_supervisor_pause_resume_and_restart_clears_pause_and_strikes(tmp_path: Path) -> None:
    state_transitions: list[tuple[str, str]] = []
    disp = HostDispatcher(HostServices(activity=lambda _row: None), OwnerTokens())
    sup = Supervisor(
        tmp_path,
        "1.0.0",
        disp,
        alert=lambda *_a: None,
        cancel_side_effects=lambda _pid: {"inbox": 0, "timers": 0, "routes": 0},
        activity=lambda _row: None,
        safe_mode=False,
    )
    sup.on_state_change = lambda pid, st: state_transitions.append((pid, st))

    ctx = PluginContext(plugin_id="tier0demo", install_key="k1", data_dir=tmp_path, granted=frozenset(), tier="local")
    spec = PluginSpec(ctx=ctx, code_dir=tmp_path, entry="main.py", tier0=True)

    loop = asyncio.new_event_loop()
    try:
        st1 = loop.run_until_complete(sup.activate(spec))
        assert st1 == "declarative"

        sup._strikes.setdefault("tier0demo", watchdog.StrikeLedger()).strike()
        st_paused = loop.run_until_complete(sup.pause("tier0demo"))
        assert st_paused == "paused"
        assert sup.is_paused("tier0demo") is True
        assert sup.admit(spec) == "paused"
        assert loop.run_until_complete(sup.ensure("tier0demo")) is None

        st_resumed = loop.run_until_complete(sup.resume(spec))
        assert st_resumed == "declarative"
        assert sup.is_paused("tier0demo") is False

        loop.run_until_complete(sup.pause("tier0demo"))
        st_restarted = loop.run_until_complete(sup.restart(spec))
        assert st_restarted == "declarative"
        assert sup.is_paused("tier0demo") is False
        assert sup.restart_count("tier0demo") == 1
        assert "tier0demo" not in sup._strikes
        assert ("tier0demo", "paused") in state_transitions
    finally:
        loop.close()


def test_inspector_pause_resume_http_routes_and_paused_409_act(
    tmp_path: Path,
    owner_jwt,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    code_dir = tmp_path / "code" / "inspplug"
    code_dir.mkdir(parents=True)
    manifest = SidecarManifest(
        id="inspplug",
        name="Inspector Plug",
        description="Tier 0 plug",
        version="1.0.0",
        entry="main.py",
        tools=(),
        permissions=(),
        network=NetworkDecl(),
        author="Acme",
        tier="catalog",
        code_digest="deadbeef",
        tier0=True,
        routes=("ping",),
    )
    defn = SidecarDefinition(manifest, "acme/inspplug", "uuid-insp", code_dir, tmp_path / "data", "PUBKEY")

    published: list[str] = []
    host_stub = SimpleNamespace(
        state_dir=state,
        publish=lambda topic: published.append(topic),
        publish_coalesced=lambda topic, *_a, **_kw: published.append(topic),
        install_key=lambda _pid: "uuid-insp",
    )
    loop = asyncio.new_event_loop()
    rt = sidecar_boot.SidecarRuntime(host_stub, app, loop, env_safe=lambda: False, app_version="9.9.9")
    rt.route_safe = False
    rt.supervisor.set_safe_mode(False)

    tel = rt.inspector
    tel.set_aliases("inspplug", "uuid-insp")
    tel.record_rpc("inspplug", source="rpc", method="storage.get", target="cfg", latency_ms=1.2, ok=True)
    tel.record_capability("inspplug", permission="sessions.read", allowed=True, reason="granted", caller="rpc:sessions.list")

    app.state.sidecar_runtime = rt
    from dataclasses import replace as dc_replace
    from src.plugins.host import state as owner_state

    owner_state.update(state, manifest, None, lambda st: dc_replace(st, enabled=True, digest="deadbeef"))
    host_real = runtime.Host(state, app)
    monkeypatch.setattr(host_real, "enabled", lambda pid: pid == "inspplug")
    monkeypatch.setattr(host_real, "install_key", lambda _pid: "uuid-insp")
    monkeypatch.setattr(host_real, "sidecar_spec", lambda d: PluginSpec(
        ctx=PluginContext(plugin_id=d.id, install_key="uuid-insp", data_dir=d.folder, granted=frozenset(), tier="catalog"),
        code_dir=d.code_root,
        entry="main.py",
        code_digest=None,
        tier0=True,
    ))
    app.state.cplugs_host = host_real

    orig_find = runtime.find
    monkeypatch.setattr(runtime, "find", lambda cid: defn if cid == "inspplug" else orig_find(cid))
    orig_hidden = runtime.hidden
    monkeypatch.setattr(runtime, "hidden", lambda d: False if d is defn else orig_hidden(d))

    try:
        with TestClient(app) as tc:
            r_insp = tc.get("/api/v1/cplugs/inspplug/inspector", headers=bearer(owner_jwt))
            assert r_insp.status_code == 200, r_insp.text
            snap = r_insp.json()
            assert snap["cplug_id"] == "inspplug"
            assert snap["trust_tier"] == "warez_verified"
            assert snap["trust_badge"] == "Warez Verified"
            assert snap["watchdog"]["memory_limit_bytes"] == watchdog.MEMORY_LIMIT_BYTES
            assert snap["surfaces"]["routes"] == ["ping"]
            assert snap["surfaces"]["absent_surfaces"] == []
            assert snap["surfaces"]["timers"] == []
            assert snap["secrets_status"] == {}
            assert len(snap["rpc_trace"]) == 1
            assert len(snap["capability_checks"]) == 1

            r_missing = tc.get("/api/v1/cplugs/nonexistent/inspector", headers=bearer(owner_jwt))
            assert r_missing.status_code == 404
            assert r_missing.json()["detail"] == {"code": "cplug_unknown", "detail": "no plugin nonexistent"}

            r_pause = tc.post("/api/v1/cplugs/inspplug/pause", headers=bearer(owner_jwt))
            assert r_pause.status_code == 200, r_pause.text
            assert r_pause.json()["paused"] is True
            assert f"{CPLUG_INSPECTOR}:inspplug" in published

            r_act = tc.post(
                "/api/v1/cplug-owner/act",
                json={"cplug_id": "inspplug", "route": "ping"},
                headers=bearer(owner_jwt),
            )
            assert r_act.status_code == 409
            assert r_act.json()["detail"]["code"] == "cplug_paused"

            r_res = tc.post("/api/v1/cplugs/inspplug/resume", headers=bearer(owner_jwt))
            assert r_res.status_code == 200, r_res.text
            assert r_res.json()["paused"] is False

            r_builtin = tc.get("/api/v1/cplugs/huddle/inspector", headers=bearer(owner_jwt))
            assert r_builtin.status_code == 200
            assert r_builtin.json()["trust_tier"] == "builtin"
            assert r_builtin.json()["trust_badge"] == "Built-in"

            r_builtin_pause = tc.post("/api/v1/cplugs/huddle/pause", headers=bearer(owner_jwt))
            assert r_builtin_pause.status_code == 409
            assert r_builtin_pause.json()["detail"]["code"] == "cplug_not_sidecar"
    finally:
        if hasattr(app.state, "sidecar_runtime"):
            delattr(app.state, "sidecar_runtime")
        if hasattr(app.state, "cplugs_host"):
            delattr(app.state, "cplugs_host")
        sidecar_registry.install(None)
        loop.close()


def test_inspector_pause_and_resume_refuse_peer_tokens_with_403_peer_forbidden(
    owner_jwt,  # noqa: F811
) -> None:
    from src.core.federation import peer_token
    from src.main import app

    assert owner_jwt
    peer_jwt, _ = peer_token.mint(SimpleNamespace(grant_id="g-insp-peer"), "iid-insp-peer")
    client = TestClient(app, raise_server_exceptions=False)
    headers = bearer(peer_jwt)

    for action in ("pause", "resume"):
        resp = client.post(f"/api/v1/cplugs/inspplug/{action}", headers=headers)
        assert resp.status_code == 403, f"{action}: {resp.status_code} {resp.text}"
        assert resp.json()["detail"]["code"] == "peer_forbidden"

    read_resp = client.get("/api/v1/cplugs/inspplug/inspector", headers=headers)
    assert read_resp.status_code == 401


def test_inspector_telemetry_redacts_rpc_secrets_userinfo_and_stderr(tmp_path: Path) -> None:
    tel = inspector_telemetry.InspectorTelemetry(tmp_path)
    gh_tok = "ghp_" + "A1b2C3d4" * 5
    ant_tok = "sk-ant-api03-" + "X9y8Z7w6" * 5
    tel.record_rpc(
        "redplug",
        source="rpc",
        method="http.fetch",
        target=f"https://user:superpass@example.com/path?tok={gh_tok}",
        latency_ms=3.4,
        ok=False,
        error_code="http_error",
        error_message=f"connect failed to https://admin:MegaSecret99@internal.example.com/api with {gh_tok}",
    )
    tel.record_capability(
        "redplug",
        permission="network_hosts:example.com",
        allowed=False,
        reason="denied https://u:Pass99@example.com/r",
        caller="https://u:Pass99@example.com",
    )
    traces = tel.rpc_trace("redplug")
    assert len(traces) == 1
    assert "superpass" not in traces[0]["target"]
    assert "user:" not in traces[0]["target"]
    assert "example.com/path" in traces[0]["target"]
    assert gh_tok not in traces[0]["target"]
    assert "?" not in traces[0]["target"]
    assert "tok=" not in traces[0]["target"]
    assert gh_tok not in traces[0]["error_message"]
    assert "MegaSecret99" not in traces[0]["error_message"]
    assert "admin:" not in traces[0]["error_message"]
    assert "https://internal.example.com/api" in traces[0]["error_message"]
    assert "****" in traces[0]["error_message"]

    tel.record_rpc(
        "redplug",
        source="rpc",
        method="http.fetch",
        target="https://user:pass@api.example.com/v1/items?api_key=sk-1234567890abcdefghij1234#secret=xyz",
        latency_ms=1.0,
        ok=True,
    )
    direct = tel.rpc_trace("redplug")[-1]
    assert direct["target"] == "https://api.example.com/v1/items"
    assert "api_key" not in direct["target"]
    assert "sk-123456" not in direct["target"]
    assert "#secret" not in direct["target"]

    caps = tel.capability_checks("redplug")
    assert len(caps) == 1
    assert "Pass99" not in caps[0]["reason"]
    assert "Pass99" not in caps[0]["caller"]
    assert "https://example.com" in caps[0]["caller"]

    fake_proc = SimpleNamespace(stderr=[f"unredacted stderr leak https://bob:Secret99@example.com {ant_tok}"])
    stream = dev_stream.stream_for(tmp_path)
    stream.publish("redplug", "reloaded", {"reason": "save", "url": f"https://u:Pass99@example.com?t={gh_tok}"})
    tail = inspector_telemetry._logs_tail(tmp_path, "redplug", fake_proc)
    assert len(tail) == 2
    assert ant_tok not in tail[0]["line"]
    assert "Secret99" not in tail[0]["line"]
    assert "bob:" not in tail[0]["line"]
    assert "https://example.com" in tail[0]["line"]
    assert "****" in tail[0]["line"]
    assert tail[1]["source"] == "reloaded"
    assert tail[1]["payload"]["reason"] == "save"
    assert "Pass99" not in tail[1]["payload"]["url"]
    assert gh_tok not in tail[1]["payload"]["url"]
    assert "****" in tail[1]["payload"]["url"]


def test_inspector_logs_tail_decodes_real_stderr_log_bytearray_and_redacts_userinfo(tmp_path: Path) -> None:
    from src.plugins.runtime.log_redaction import StderrLog

    gh_tok = "ghp_" + "A1b2C3d4" * 5
    slog = StderrLog("realplug")
    slog.feed(f"hello plugin\nhttps://bob:Secret99@example.com/path\ntok={gh_tok}\n".encode("utf-8"))
    slog.close()
    assert isinstance(slog.kept, bytearray)

    tail = inspector_telemetry._logs_tail(tmp_path, "realplug", SimpleNamespace(stderr=slog.kept))
    assert [entry["line"] for entry in tail] == [
        "hello plugin",
        "https://example.com/path",
        "tok=" + ("*" * len(gh_tok)),
    ]
    assert all(entry["source"] == "stderr" for entry in tail)


def test_supervisor_auto_restart_increments_restart_count_and_watchdog_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace as dc_replace
    import src.plugins.runtime.supervisor as sup_mod

    spawned_procs: list[Any] = []
    observed_counts_on_running: list[int] = []

    class _FakeProc:
        def __init__(self, spec: PluginSpec, _layout: Any, _disp: Any, _ver: str, on_exit: Any, _sampler: Any) -> None:
            self.spec = spec
            self._on_exit = on_exit
            self.ended: str | None = None
            self.busy = 0
            self.pid = 40000 + len(spawned_procs)
            self.started_at = 1.0
            self.stderr = bytearray()
            spawned_procs.append(self)

        async def start(self) -> None:
            return None

        async def stop(self, reason: str = "disabled", **_kw: Any) -> None:
            self.ended = reason

        async def kill(self, reason: str = "killed") -> None:
            self.ended = reason

    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(sup_mod, "PluginProcess", _FakeProc)

    disp = HostDispatcher(HostServices(activity=lambda _row: None), OwnerTokens())
    sup = Supervisor(
        tmp_path,
        "1.0.0",
        disp,
        alert=lambda *_a: None,
        cancel_side_effects=lambda _pid: {"inbox": 0, "timers": 0, "routes": 0},
        activity=lambda _row: None,
        safe_mode=False,
        sleep=_fast_sleep,
    )
    monkeypatch.setattr(sup, "_layout", lambda _spec, **_kw: SimpleNamespace(files_dir=tmp_path))
    sup.on_state_change = lambda pid, st: observed_counts_on_running.append(sup.restart_count(pid)) if st == "running" else None

    code_dir = tmp_path / "code"
    code_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ctx = PluginContext(plugin_id="rssplug", install_key="k-rss", data_dir=data_dir, granted=frozenset(), tier="local")
    spec = PluginSpec(ctx=ctx, code_dir=code_dir, entry="main.py")

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(sup.enable(spec)) == "running"
        assert sup.restart_count("rssplug") == 0
        assert observed_counts_on_running == [0]

        loop.run_until_complete(sup._exited("rssplug", "resource_abuse"))
        loop.run_until_complete(sup._restarts["rssplug"])
        assert sup.state("rssplug") == "running"
        assert sup.restart_count("rssplug") == 1
        assert observed_counts_on_running == [0, 1]
        summary_1 = inspector_telemetry.watchdog_row_summary(tmp_path, sup, "rssplug", data_dir)
        assert summary_1["restart_count"] == 1
        assert summary_1["strikes"] == 1
        assert summary_1["crash_loop_paused"] is False

        loop.run_until_complete(sup._exited("rssplug", "crashed"))
        loop.run_until_complete(sup._restarts["rssplug"])
        assert sup.state("rssplug") == "running"
        assert sup.restart_count("rssplug") == 2
        assert observed_counts_on_running == [0, 1, 2]

        loop.run_until_complete(sup._exited("rssplug", "resource_abuse"))
        assert sup.state("rssplug") == "crash_loop"
        assert sup.restart_count("rssplug") == 2
        summary_cl = inspector_telemetry.watchdog_row_summary(tmp_path, sup, "rssplug", data_dir)
        assert summary_cl["restart_count"] == 2
        assert summary_cl["strikes"] == 3
        assert summary_cl["crash_loop_paused"] is True

        sup._specs["rssplug"] = dc_replace(spec, consent_owed=True)
        sup._state["rssplug"] = "backing_off"
        loop.run_until_complete(sup._restart_after("rssplug", 0.0))
        assert sup.state("rssplug") == "needs_approval"
        assert sup.restart_count("rssplug") == 2
    finally:
        loop.close()
