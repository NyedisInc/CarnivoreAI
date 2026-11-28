
from __future__ import annotations

import asyncio
import json
import shutil
import socket
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core import resource_push, session_change_notice
from src.core.mcp import pending
from src.core.resource_push import topics
from src.core.sessions import session_events
from src.plugins.host import activity_log, owner_switch, plugin_bus, sidecar_boot, sidecar_registry, sidecar_spec, state as owner_state
from src.plugins.host.runtime import Host
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import dispatch, frames, guards, sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import PluginProcess

DARWIN_SANDBOX = sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def _write_stdio_plugin(folder: Path, plugin_id: str, toml_body: str, py_body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "carnivore.toml").write_text(toml_body, encoding="utf-8")
    (folder / "main.py").write_text(textwrap.dedent(py_body), encoding="utf-8")


def _sock_rpc(sock_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(sock_path))
        conn.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8").splitlines()[0])


def _register_and_enable(
    state_dir: Path,
    code_dir: Path,
    plugin_id: str,
    install_key: str,
    *,
    grants: tuple[str, ...] | None = None,
    enabled: bool = True,
) -> SidecarDefinition:
    manifest = load_sidecar_manifest(code_dir, plugin_id)
    data_dir = state_dir / "cplugs" / install_key
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(
        manifest=manifest,
        item_id=f"acme/{plugin_id}",
        install_key=install_key,
        code_root=code_dir,
        folder=data_dir,
    )
    eff_grants = tuple(manifest.permissions) if grants is None else grants
    owner_state.update(
        state_dir,
        manifest,
        None,
        lambda st: replace(st, enabled=enabled, grants=eff_grants, digest=manifest.code_digest),
    )
    return defn


def _install_registry(monkeypatch: pytest.MonkeyPatch, defs: List[SidecarDefinition]) -> None:
    by_id = {d.id: d for d in defs}
    fake_reg = SimpleNamespace(listed=lambda: list(defs), find=lambda pid: by_id.get(pid))
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: by_id.get(pid))


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_cross_plugin_service_call_and_events_e2e_stdio_and_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    prov_dir = tmp_path / "code_prov"
    cons_dir = tmp_path / "code_cons"

    _write_stdio_plugin(
        prov_dir,
        "provb",
        """schema = 2
id = "provb"
name = "Provider B"
version = "1.0.0"
kind = "plugin"
description = "Provides acme.calc and listens to events"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
events = ["consa:done"]

[events]
on = ["consa:done"]

[[services.provides]]
name = "acme.calc"
methods = ["add", "echo_big"]

[services.provides.schemas.add]
type = "object"
required = ["a", "b"]
additionalProperties = false
[services.provides.schemas.add.properties]
a = { type = "integer" }
b = { type = "integer" }
""",
        """
        from pathlib import Path
        from cplug_sdk.plugin import Plugin

        plugin = Plugin()

        @plugin.on_event("consa:done")
        async def on_done(seq, payload):
            out = Path("received_events.jsonl")
            with out.open("a", encoding="utf-8") as fh:
                import json
                fh.write(json.dumps({"seq": seq, "payload": payload}) + "\\n")

        async def handle_override(method, params):
            if method == "service.call":
                if params.get("method") == "add":
                    args = params.get("args") or {}
                    return {"sum": int(args["a"]) + int(args["b"])}
                if params.get("method") == "echo_big":
                    return {"blob": "x" * (300 * 1024)}
            return await Plugin.handle(plugin, method, params)

        plugin.handle = handle_override
        """,
    )

    _write_stdio_plugin(
        cons_dir,
        "consa",
        """schema = 2
id = "consa"
name = "Consumer A"
version = "1.0.0"
kind = "plugin"
description = "Calls acme.calc and emits consa:done"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
services = ["acme.calc"]
events = ["consa:done"]

[services]
consumes = ["acme.calc"]

[events]
emit = ["consa:done"]

[mcp]
[[mcp.tools]]
name = "consa_run"
description = "Run cross-plugin call and emit"
gate = "read"
inputSchema = { type = "object" }
""",
        """
        from cplug_sdk.plugin import Plugin

        plugin = Plugin()

        @plugin.tool("consa_run", "Run cross-plugin call and emit")
        async def consa_run(args, caller):
            calc = await plugin._call("service.call", {"service": "acme.calc", "method": "add", "args": {"a": 7, "b": 5}})
            ev = await plugin._call("events.emit", {"event": "consa:done", "payload": {"total": calc["sum"]}})
            return {"calc": calc, "ev": ev}
        """,
    )

    owner_switch.write(state_dir, True)
    prov_def = _register_and_enable(state_dir, prov_dir, "provb", "inst-provb")
    cons_def = _register_and_enable(state_dir, cons_dir, "consa", "inst-consa")
    _install_registry(monkeypatch, [prov_def, cons_def])

    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    host = Host(state_dir, app=app)
    monkeypatch.setattr(host, "install_key", lambda pid: f"inst-{pid}")
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)

    try:
        rt.supervisor.override_index("provb", True)
        rt.supervisor.override_index("consa", True)
        await rt.supervisor.activate(host.sidecar_spec(prov_def))
        await rt.supervisor.activate(host.sidecar_spec(cons_def))
        assert rt.supervisor.state("consa") == "idle"

        cons_proc = await rt.supervisor.ensure("consa")
        assert cons_proc is not None
        res = await cons_proc.request("tools/call", {"name": "consa_run", "arguments": {}, "caller": {}})
        parsed = json.loads(res["content"][0]["text"])
        assert parsed == {"calc": {"sum": 12}, "ev": {"event": "consa:done", "delivered": 1}}

        ev_file = prov_def.folder / "files" / "received_events.jsonl"
        for _ in range(40):
            if ev_file.exists():
                break
            await asyncio.sleep(0.05)
        assert ev_file.exists()
        ev_row = json.loads(ev_file.read_text(encoding="utf-8").strip())
        assert ev_row["payload"] == {"event": "consa:done", "source": "consa", "data": {"total": 12}}

        recent = activity_log.ActivityLog(state_dir).recent("inst-consa")
        by_method = {r["method"]: r for r in recent}
        assert by_method["service.call"]["permission"] == "services:acme.calc"
        assert by_method["service.call"]["target"] == "acme.calc.add"
        assert by_method["service.call"]["status"] == "ok"
        assert by_method["events.emit"]["permission"] == "events:consa:done"
        assert by_method["events.emit"]["target"] == "consa:done"

        traces = rt.inspector.rpc_trace("consa")
        checks = rt.inspector.capability_checks("consa")
        assert any(t["target"] == "acme.calc.add" and t["ok"] is True for t in traces)
        assert any(c["permission"] == "services:acme.calc" and c["allowed"] is True for c in checks)

        with pytest.raises(guards.Refused) as bad_args:
            await rt.dispatcher.handle(
                cons_proc.spec.ctx,
                "service.call",
                {"service": "acme.calc", "method": "add", "args": {"a": "wrong", "b": 2}},
            )
        assert bad_args.value.code == "invalid_params"

        with pytest.raises(guards.Refused) as big_res:
            await rt.dispatcher.handle(
                cons_proc.spec.ctx,
                "service.call",
                {"service": "acme.calc", "method": "echo_big", "args": {}},
            )
        assert big_res.value.code == "too_large"

        sock_path = await rt.socket_manager.ensure(state_dir, cons_proc.spec.ctx, rt.dispatcher)
        sock_resp = await asyncio.to_thread(
            _sock_rpc,
            sock_path,
            {"jsonrpc": "2.0", "id": 9, "method": "service.call", "params": {"service": "acme.calc", "method": "add", "args": {"a": 10, "b": 11}}},
        )
        assert sock_resp["result"] == {"sum": 21}
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_bus_cycle_depth_guard_across_real_subprocesses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    a_dir = tmp_path / "code_a"
    b_dir = tmp_path / "code_b"

    def _cycle_code(target_svc: str) -> str:
        return f"""
        from cplug_sdk.plugin import Plugin

        plugin = Plugin()

        async def handle_override(method, params):
            if method == "service.call" and params.get("method") == "hop":
                n = int((params.get("args") or {{}}).get("n", 0))
                return await plugin._call("service.call", {{"service": "{target_svc}", "method": "hop", "args": {{"n": n + 1}}}})
            return await Plugin.handle(plugin, method, params)

        plugin.handle = handle_override
        """

    _write_stdio_plugin(
        a_dir,
        "cycla",
        """schema = 2
id = "cycla"
name = "Cycle A"
version = "1.0.0"
kind = "plugin"
description = "Cycle A"
author = "Tester"
[run]
cmd = ["python3", "main.py"]
mode = "rpc"
[permissions]
services = ["svc.b"]
[services]
consumes = ["svc.b"]
[[services.provides]]
name = "svc.a"
methods = ["hop"]
""",
        _cycle_code("svc.b"),
    )
    _write_stdio_plugin(
        b_dir,
        "cyclb",
        """schema = 2
id = "cyclb"
name = "Cycle B"
version = "1.0.0"
kind = "plugin"
description = "Cycle B"
author = "Tester"
[run]
cmd = ["python3", "main.py"]
mode = "rpc"
[permissions]
services = ["svc.a"]
[services]
consumes = ["svc.a"]
[[services.provides]]
name = "svc.b"
methods = ["hop"]
""",
        _cycle_code("svc.a"),
    )

    owner_switch.write(state_dir, True)
    def_a = _register_and_enable(state_dir, a_dir, "cycla", "inst-cycla")
    def_b = _register_and_enable(state_dir, b_dir, "cyclb", "inst-cyclb")
    _install_registry(monkeypatch, [def_a, def_b])

    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    host = Host(state_dir, app=app)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    try:
        rt.supervisor.override_index("cycla", True)
        rt.supervisor.override_index("cyclb", True)
        await rt.supervisor.activate(host.sidecar_spec(def_a))
        await rt.supervisor.activate(host.sidecar_spec(def_b))
        proc_a = await rt.supervisor.ensure("cycla")
        assert proc_a is not None
        with pytest.raises(guards.Refused) as exc_info:
            await rt.dispatcher.handle(proc_a.spec.ctx, "service.call", {"service": "svc.b", "method": "hop", "args": {"n": 0}})
        assert exc_info.value.code in ("rate_limited", "unavailable")
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_bus_unavailable_states_consent_denials_anti_spoofing_and_rate_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    prov_dir = tmp_path / "code_prov"
    _write_stdio_plugin(
        prov_dir,
        "provu",
        """schema = 2
id = "provu"
name = "Provider U"
version = "1.0.0"
kind = "plugin"
description = "Unavailable & rate limit test provider"
author = "Tester"
[run]
cmd = ["python3", "main.py"]
mode = "rpc"
[[services.provides]]
name = "acme.u"
methods = ["ping"]
""",
        "import asyncio\nfrom cplug_sdk.plugin import Plugin\nasyncio.run(Plugin().serve())\n",
    )
    prov_def = _register_and_enable(state_dir, prov_dir, "provu", "inst-provu")
    _install_registry(monkeypatch, [prov_def])

    now = [100.0]
    pstate = {"provu": "idle"}
    paused = {"provu": False}
    delivered_events: List[Any] = []
    ensure_calls = [0]

    class _FakeProc:
        ended = None

        def __init__(self, handler):
            self._handler = handler

        async def request(self, method, params, timeout=5.0):
            return await self._handler(method, params)

    fake_proc = _FakeProc(lambda _m, _p: asyncio.sleep(0, result={"pong": True}))

    class _FakeSup:
        def is_paused(self, pid):
            return paused.get(pid, False)

        def state(self, pid):
            return pstate.get(pid, "unknown")

        async def ensure(self, pid):
            ensure_calls[0] += 1
            return fake_proc

        async def deliver_event(self, pid, family, seq, payload):
            delivered_events.append((pid, family, seq, payload))
            return True

    sup = _FakeSup()
    safe_flag = {"env": False, "owner": False, "off": False}
    host = Host(state_dir, app=SimpleNamespace(state=SimpleNamespace()))
    bus = plugin_bus.PluginBus(
        host=host,
        state_dir=lambda: state_dir,
        supervisor_getter=lambda: sup,
        safe_mode_getter=lambda: safe_flag,
        on_loop=lambda fn, *a: fn(*a),
        definitions_getter=lambda: [prov_def],
        clock=lambda: now[0],
    )
    disp = HostDispatcher(
        HostServices(activity=lambda _r: None, service_call=bus.call_service, events_emit=bus.emit_plugin_event),
        OwnerTokens(b"k" * 32),
        clock=lambda: now[0],
    )
    caller_ctx = PluginContext(
        plugin_id="cons",
        install_key="k-cons",
        data_dir=tmp_path / "cons",
        granted=frozenset({"services:acme.u", "services:missing.svc", "events:cons:ok", "events:session.started", "events:other:hack"}),
        services_consumes=("acme.u", "missing.svc"),
        events_emit=("cons:ok", "session.started", "other:hack"),
    )

    with pytest.raises(guards.Refused) as e_none:
        await disp.handle(caller_ctx, "service.call", {"service": "missing.svc", "method": "ping", "args": {}})
    assert e_none.value.code == "service_unavailable" and e_none.value.data["reason"] == "no_provider"
    assert dispatch.CODES[e_none.value.code] == frames.DISABLED

    paused["provu"] = True
    with pytest.raises(guards.Refused) as e_paused:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_paused.value.code == "service_unavailable" and e_paused.value.data["reason"] == "provider_paused"
    paused["provu"] = False

    pstate["provu"] = "backing_off"
    with pytest.raises(guards.Refused) as e_restart:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_restart.value.code == "service_unavailable" and e_restart.value.data["reason"] == "provider_restarting"

    for bad_state in ("crash_loop", "revoked", "needs_approval", "disabled"):
        pstate["provu"] = bad_state
        with pytest.raises(guards.Refused) as e_st:
            await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
        assert e_st.value.code == "service_unavailable"
    pstate["provu"] = "idle"

    owner_state.update(state_dir, prov_def.manifest, None, lambda st: replace(st, enabled=False))
    with pytest.raises(guards.Refused) as e_dis:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_dis.value.code == "service_unavailable" and e_dis.value.data["reason"] == "provider_disabled"

    owner_state.update(state_dir, prov_def.manifest, None, lambda st: replace(st, enabled=True, digest="0" * 64))
    with pytest.raises(guards.Refused) as e_app:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_app.value.code == "service_unavailable" and e_app.value.data["reason"] == "provider_needs_approval"
    owner_state.update(state_dir, prov_def.manifest, None, lambda st: replace(st, enabled=True, digest=prov_def.manifest.code_digest))

    async def _slow(_m, _p):
        raise asyncio.TimeoutError()

    fake_proc._handler = _slow
    with pytest.raises(guards.Refused) as e_to:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_to.value.code == "timeout"
    fake_proc._handler = lambda _m, _p: asyncio.sleep(0, result={"pong": True})

    before_ensure = ensure_calls[0]
    with pytest.raises(guards.Refused) as e_nan:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {"x": float("nan")}})
    assert e_nan.value.code == "invalid_params"
    with pytest.raises(guards.Refused) as e_big:
        await disp.handle(caller_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {"x": "a" * (70 * 1024)}})
    assert e_big.value.code == "too_large"
    assert ensure_calls[0] == before_ensure

    ungranted_ctx = replace(caller_ctx, granted=frozenset())
    with pytest.raises(guards.Refused) as e_ungranted:
        await disp.handle(ungranted_ctx, "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_ungranted.value.code == "not_granted"

    for bad_ev in ("session.started", "git.commit", "approval.requested", "task.updated", "feed.raw", "webhook.ci", "mcp.health", "cplug.x", "system.boot", "cplugs", "other:hack"):
        with pytest.raises(guards.Refused) as e_spoof:
            await disp.handle(caller_ctx, "events.emit", {"event": bad_ev, "payload": {}})
        assert e_spoof.value.code == "permission_denied", bad_ev

    now[0] += 5.0
    for i in range(60):
        c_i = replace(caller_ctx, plugin_id=f"c{i % 10}")
        assert await disp.handle(c_i, "service.call", {"service": "acme.u", "method": "ping", "args": {}}) == {"pong": True}
    with pytest.raises(guards.Refused) as e_prov_rl:
        await disp.handle(replace(caller_ctx, plugin_id="c99"), "service.call", {"service": "acme.u", "method": "ping", "args": {}})
    assert e_prov_rl.value.code == "rate_limited"

    now[0] += 5.0
    for _ in range(20):
        await disp.handle(caller_ctx, "events.emit", {"event": "cons:ok", "payload": {"n": 1}})
    with pytest.raises(guards.Refused) as e_fam_rl:
        await disp.handle(caller_ctx, "events.emit", {"event": "cons:ok", "payload": {"n": 2}})
    assert e_fam_rl.value.code == "rate_limited"


@pytest.mark.asyncio
async def test_process_deliver_event_enforces_grants_and_core_lifecycle_bridges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    sub_dir = tmp_path / "code_sub"
    _write_stdio_plugin(
        sub_dir,
        "subp",
        """schema = 2
id = "subp"
name = "Subscriber"
version = "1.0.0"
kind = "plugin"
description = "Subscribes to core lifecycle events"
author = "Tester"
[run]
cmd = ["python3", "main.py"]
mode = "rpc"
[permissions]
events = [
  "session.started", "session.status_changed", "session.idle", "session.died",
  "session.slept", "session.created", "session.destroyed",
  "approval.requested", "approval.approved", "approval.denied",
  "git.status_changed", "git.checkpoint", "task.updated",
]
[events]
on = [
  "session.started", "session.status_changed", "session.idle", "session.died",
  "session.slept", "session.created", "session.destroyed",
  "approval.requested", "approval.approved", "approval.denied",
  "git.status_changed", "git.checkpoint", "task.updated",
]
""",
        "import asyncio\nfrom cplug_sdk.plugin import Plugin\nasyncio.run(Plugin().serve())\n",
    )
    sub_def = _register_and_enable(state_dir, sub_dir, "subp", "inst-subp")
    _install_registry(monkeypatch, [sub_def])

    spec_ungranted = sidecar_spec.build_spec(sub_def, frozenset({"hooks.inbound:ci"}), {})
    proc = PluginProcess(
        spec_ungranted,
        sandbox.Layout(sub_dir, sub_def.folder, tmp_path / "rt", state_dir, "subp", "inst-subp"),
        HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"x" * 32)),
        "1.0.0",
        lambda _r: asyncio.sleep(0),
    )
    proc.negotiated = {"subscriptions": ["session.started", "webhook.ci", "webhook.denied"]}
    proc._proc = SimpleNamespace(stdin=SimpleNamespace(is_closing=lambda: False, write=lambda _d: None, drain=lambda: asyncio.sleep(0)))
    assert await proc.deliver_event("session.started", 1, {}) is False
    assert await proc.deliver_event("webhook.denied", 2, {}) is False
    assert await proc.deliver_event("webhook.ci", 3, {}) is True

    delivered: List[tuple[str, str, int, Any]] = []

    class _CapSup:
        def is_paused(self, _pid):
            return False

        def state(self, _pid):
            return "running"

        async def deliver_event(self, pid, family, seq, payload):
            delivered.append((pid, family, seq, payload))
            return True

    store = pending.PendingActions()
    monkeypatch.setattr(pending, "get_store", lambda: store)
    published_frames: List[Dict[str, Any]] = []
    resource_push.install(lambda frame: published_frames.append(frame) or 1, loop=asyncio.get_running_loop(), window_seconds=0.01)

    host = Host(state_dir, app=SimpleNamespace(state=SimpleNamespace()))
    loop = asyncio.get_running_loop()
    bus = plugin_bus.PluginBus(
        host=host,
        state_dir=lambda: state_dir,
        supervisor_getter=lambda: _CapSup(),
        safe_mode_getter=lambda: {"env": False, "owner": False, "off": False},
        on_loop=lambda fn, *a: fn(*a) if asyncio.get_running_loop() is loop else loop.call_soon_threadsafe(fn, *a),
        definitions_getter=lambda: [sub_def],
    )
    bus.start()
    try:
        await session_events.emit(session_events.SessionEvent(kind=session_events.STARTED, tmux_name="carnivore_a", reason="created", session_uuid="u-1"))

        for reason in ("slept", "created", "destroyed"):
            session_change_notice.publish(host.app.state, session_change_notice.build_structural_notice(reason))
        session_change_notice.publish(
            host.app.state,
            session_change_notice.build_status_notice(
                session_id="ses_1", tmux_session="carnivore_a", activity_status="working", unread=False, startup_gate="ready",
            ),
        )
        session_change_notice.publish(
            host.app.state,
            session_change_notice.build_status_notice(session_id="ses_2", tmux_session="carnivore_b", activity_status="dead"),
        )
        session_change_notice.publish(
            host.app.state,
            session_change_notice.build_status_notice(session_id="ses_4", activity_status="idle"),
        )
        sm = SimpleNamespace(hook_tokens=SimpleNamespace(tmux_names={"ses_3": "carnivore_c"}), _instance_epochs={}, _is_unread=lambda *_a: True)
        session_change_notice.publish_attention_status(host.app.state, sm, "ses_3", activity_status="idle")

        act1 = store.create(
            caller_session_id="ses_c", caller_tmux="t_c", target_session_id="ses_t", target_tmux="t_t",
            action="test_act", args_summary="run test", execute=lambda: asyncio.sleep(0, result={"ok": True}),
        )
        await store.approve(act1.id)
        act2 = store.create(
            caller_session_id="ses_c", caller_tmux="t_c", target_session_id="ses_t", target_tmux="t_t",
            action="test_act2", args_summary="deny test", execute=lambda: asyncio.sleep(0, result={"ok": True}),
        )
        store.deny(act2.id)

        resource_push.notify(topics.keyed(topics.GIT_STATUS, "ses_1"))
        resource_push.notify(topics.keyed(topics.CHECKPOINTS, "ses_1"))
        resource_push.notify("cplug.taskmanager.list:inbox")

        expected_families = {
            "session.started", "session.status_changed", "session.idle", "session.died",
            "session.slept", "session.created", "session.destroyed",
            "approval.requested", "approval.approved", "approval.denied",
            "git.status_changed", "git.checkpoint", "task.updated",
        }
        for _ in range(50):
            if expected_families <= {row[1] for row in delivered}:
                break
            await asyncio.sleep(0.02)

        assert expected_families <= {row[1] for row in delivered}
        by_fam: Dict[str, List[Any]] = {}
        for _pid, fam, _seq, payload in delivered:
            by_fam.setdefault(fam, []).append(payload)
        assert any(p.get("source") == "core" and p.get("data") == {"session_id": "ses_1", "tmux_session": "carnivore_a", "activity_status": "working", "unread": False, "startup_gate": "ready"}
                   for p in by_fam["session.status_changed"])
        assert any(p.get("data", {}).get("session_id") == "ses_3" and p["data"].get("tmux_session") == "carnivore_c" and p["data"].get("activity_status") == "finished_unread"
                   for p in by_fam["session.status_changed"])
        assert any(p.get("data", {}).get("session_id") == "ses_2" and p["data"].get("activity_status") == "dead" for p in by_fam["session.died"])
        assert any(p.get("data", {}).get("session_id") == "ses_4" for p in by_fam["session.idle"])
    finally:
        await bus.stop()
        resource_push.uninstall()

    count_after_stop = len(delivered)
    await session_events.emit(session_events.SessionEvent(kind=session_events.STARTED, tmux_name="carnivore_after", reason="created"))
    session_change_notice.publish(host.app.state, session_change_notice.build_structural_notice("slept"))
    session_change_notice.publish(host.app.state, session_change_notice.build_status_notice(session_id="ses_after", activity_status="idle"))
    await asyncio.sleep(0.05)
    assert len(delivered) == count_after_stop


def _write_json_plugin(folder: Path, manifest: Dict[str, Any], py_body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "carnivore.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "main.py").write_text(textwrap.dedent(py_body), encoding="utf-8")


def _make_bus_def(tmp_path: Path, state_dir: Path, pid: str, provides: list, consumes: list, body: str = "") -> SidecarDefinition:
    code_dir = tmp_path / f"code_{pid}"
    manifest = {
        "schema": 2, "id": pid, "name": pid, "version": "1.0.0", "kind": "plugin", "description": pid, "author": "T",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "permissions": {"services": consumes}, "services": {"provides": provides, "consumes": consumes},
    }
    _write_json_plugin(code_dir, manifest, body or "from cplug_sdk.plugin import Plugin\nplugin = Plugin()\n")
    return _register_and_enable(state_dir, code_dir, pid, f"inst-{pid}")


@pytest.mark.asyncio
async def test_concurrent_bus_depth_tracking_and_out_of_order_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    defs = {
        "pa": _make_bus_def(tmp_path, state_dir, "pa", [], ["svc.x"]),
        "px": _make_bus_def(tmp_path, state_dir, "px", [{"name": "svc.x", "methods": ["hop"]}], ["svc.y"]),
        "py": _make_bus_def(tmp_path, state_dir, "py", [{"name": "svc.y", "methods": ["hop"]}], ["svc.z"]),
        "pz": _make_bus_def(tmp_path, state_dir, "pz", [{"name": "svc.z", "methods": ["hop"]}], ["svc.b"]),
        "pb": _make_bus_def(tmp_path, state_dir, "pb", [{"name": "svc.b", "methods": ["hop"]}], ["svc.e"]),
        "pd": _make_bus_def(tmp_path, state_dir, "pd", [], ["svc.b"]),
        "pe": _make_bus_def(tmp_path, state_dir, "pe", [{"name": "svc.e", "methods": ["hop"]}], []),
    }
    _install_registry(monkeypatch, list(defs.values()))
    procs: Dict[str, Any] = {}
    sup = SimpleNamespace(is_paused=lambda _p: False, state=lambda _p: "running", ensure=lambda p: asyncio.sleep(0, result=procs[p]))
    host = Host(state_dir, app=SimpleNamespace(state=SimpleNamespace()))
    bus = plugin_bus.PluginBus(host=host, state_dir=lambda: state_dir, supervisor_getter=lambda: sup,
                               safe_mode_getter=lambda: {"env": False}, on_loop=lambda fn, *a: fn(*a), definitions_getter=lambda: list(defs.values()))
    disp = HostDispatcher(HostServices(activity=lambda _r: None, service_call=bus.call_service), OwnerTokens(b"k" * 32))
    ctxs = {pid: PluginContext(plugin_id=pid, install_key=f"inst-{pid}", data_dir=defs[pid].folder,
                               granted=frozenset(defs[pid].manifest.permissions), services_consumes=defs[pid].manifest.services_consumes)
            for pid in defs}

    def _hop_proc(pid: str, next_svc: str):
        async def _req(_m, p, **_kw):
            return await disp.handle(ctxs[pid], "service.call", {"service": next_svc, "method": "hop", "args": p["args"], "_bus_token": p["_bus_token"]})
        return SimpleNamespace(ended=None, request=_req)

    deep_entered, deep_release = asyncio.Event(), asyncio.Event()
    shallow_entered, shallow_call_e = asyncio.Event(), asyncio.Event()
    echo_token = [True]

    async def _pb_req(_m, p, **_kw):
        tag = p["args"].get("tag")
        tok_kw = {"_bus_token": p["_bus_token"]} if echo_token[0] else {}
        if tag == "deep":
            deep_entered.set()
            await deep_release.wait()
            if p["args"].get("exceed"):
                return await disp.handle(ctxs["pb"], "service.call", {"service": "svc.e", "method": "hop", "args": {}, **tok_kw})
            return {"b": "deep_ok"}
        if tag == "ooo":
            shallow_entered.set()
            await shallow_call_e.wait()
        return await disp.handle(ctxs["pb"], "service.call", {"service": "svc.e", "method": "hop", "args": {}, **tok_kw})

    procs.update({"px": _hop_proc("px", "svc.y"), "py": _hop_proc("py", "svc.z"), "pz": _hop_proc("pz", "svc.b"),
                  "pb": SimpleNamespace(ended=None, request=_pb_req), "pe": SimpleNamespace(ended=None, request=lambda _m, _p, **_kw: asyncio.sleep(0, result={"e": "ok"}))})
    deep_task = asyncio.create_task(disp.handle(ctxs["pa"], "service.call", {"service": "svc.x", "method": "hop", "args": {"tag": "deep", "exceed": True}}))
    await deep_entered.wait()
    assert await disp.handle(ctxs["pd"], "service.call", {"service": "svc.b", "method": "hop", "args": {"tag": "shallow"}}) == {"e": "ok"}
    deep_release.set()
    with pytest.raises(guards.Refused) as exc_depth:
        await deep_task
    assert exc_depth.value.code == "rate_limited" and exc_depth.value.data["depth"] == 4
    for use_tok in (True, False):
        echo_token[0] = use_tok
        for ev in (deep_entered, deep_release, shallow_entered, shallow_call_e):
            ev.clear()
        deep_t = asyncio.create_task(disp.handle(ctxs["pa"], "service.call", {"service": "svc.x", "method": "hop", "args": {"tag": "deep"}}))
        await deep_entered.wait()
        shallow_t = asyncio.create_task(disp.handle(ctxs["pd"], "service.call", {"service": "svc.b", "method": "hop", "args": {"tag": "ooo"}}))
        await shallow_entered.wait()
        deep_release.set()
        assert await deep_t == {"b": "deep_ok"}
        shallow_call_e.set()
        assert await shallow_t == {"e": "ok"}
    assert bus._inflight_calls == {} and bus._inflight_by_provider == {}


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_concurrent_bus_depth_across_real_subprocesses_and_raw_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    def _hop_body(t: str) -> str:
        return (
            "from cplug_sdk.plugin import Plugin\nplugin = Plugin()\nasync def h(m, p):\n"
            f"    return await plugin._call('service.call', {{'service': '{t}', 'method': 'hop', 'args': p.get('args') or {{}}}}) if m == 'service.call' else await Plugin.handle(plugin, m, p)\n"
            "plugin.handle = h\n"
        )
    pb_body = """
    import asyncio
    from pathlib import Path
    from cplug_sdk.plugin import Plugin
    plugin = Plugin()
    async def h(m, p):
        if m == "service.call":
            args = p.get("args") or {}
            if args.get("tag") == "deep":
                Path("deep_entered.flag").write_text("1", encoding="utf-8")
                while not Path("deep_release.flag").exists():
                    await asyncio.sleep(0.02)
                return {"b": "deep_done"}
            return await plugin._call("service.call", {"service": "svc.e", "method": "hop", "args": args})
        return await Plugin.handle(plugin, m, p)
    plugin.handle = h
    """
    raw_body = """
    from cplug_sdk import plugin as sdk_mod
    from cplug_sdk.plugin import HostError, Plugin
    plugin = Plugin()
    async def h(m, p):
        if m == "service.call":
            sdk_mod._bus_token.set(None)
            try:
                return await plugin._call("service.call", {"service": "svc.raw", "method": "hop", "args": {}})
            except HostError as exc:
                return {"err": exc.code}
        return await Plugin.handle(plugin, m, p)
    plugin.handle = h
    """
    defs = {
        "pa": _make_bus_def(tmp_path, state_dir, "pa", [], ["svc.x"]),
        "px": _make_bus_def(tmp_path, state_dir, "px", [{"name": "svc.x", "methods": ["hop"]}], ["svc.y"], _hop_body("svc.y")),
        "py": _make_bus_def(tmp_path, state_dir, "py", [{"name": "svc.y", "methods": ["hop"]}], ["svc.z"], _hop_body("svc.z")),
        "pz": _make_bus_def(tmp_path, state_dir, "pz", [{"name": "svc.z", "methods": ["hop"]}], ["svc.b"], _hop_body("svc.b")),
        "pb": _make_bus_def(tmp_path, state_dir, "pb", [{"name": "svc.b", "methods": ["hop"]}], ["svc.e"], pb_body),
        "pd": _make_bus_def(tmp_path, state_dir, "pd", [], ["svc.b"]),
        "pe": _make_bus_def(tmp_path, state_dir, "pe", [{"name": "svc.e", "methods": ["hop"]}], [],
                            "from cplug_sdk.plugin import Plugin\nplugin = Plugin()\nasync def h(m, p): return {'e': True} if m == 'service.call' else await Plugin.handle(plugin, m, p)\nplugin.handle = h\n"),
        "prw": _make_bus_def(tmp_path, state_dir, "prw", [{"name": "svc.raw", "methods": ["hop"]}], ["svc.raw"], raw_body),
    }
    _install_registry(monkeypatch, list(defs.values()))
    owner_switch.write(state_dir, True)
    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    host = Host(state_dir, app=app)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    try:
        for pid, d in defs.items():
            rt.supervisor.override_index(pid, True)
            await rt.supervisor.activate(host.sidecar_spec(d))
        proc_a, proc_d, proc_raw = await rt.supervisor.ensure("pa"), await rt.supervisor.ensure("pd"), await rt.supervisor.ensure("prw")
        assert proc_a and proc_d and proc_raw
        deep_task = asyncio.create_task(rt.dispatcher.handle(proc_a.spec.ctx, "service.call", {"service": "svc.x", "method": "hop", "args": {"tag": "deep"}}))
        entered = defs["pb"].folder / "files" / "deep_entered.flag"
        for _ in range(100):
            if entered.exists():
                break
            await asyncio.sleep(0.05)
        assert entered.exists()
        assert await rt.dispatcher.handle(proc_d.spec.ctx, "service.call", {"service": "svc.b", "method": "hop", "args": {"tag": "shallow"}}) == {"e": True}
        (defs["pb"].folder / "files" / "deep_release.flag").write_text("1", encoding="utf-8")
        assert await deep_task == {"b": "deep_done"}
        assert await rt.dispatcher.handle(proc_raw.spec.ctx, "service.call", {"service": "svc.raw", "method": "hop", "args": {}}) == {"err": frames.RATE_LIMITED}
    finally:
        await rt.stop()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_bus_token_spoofing_and_event_namespace_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    d_prov = _make_bus_def(
        tmp_path, state_dir, "provt", [{"name": "acme.tok", "methods": ["hold"]}], [],
        "import asyncio\nfrom pathlib import Path\nfrom cplug_sdk.plugin import Plugin\nplugin = Plugin()\n"
        "async def h(m, p):\n"
        "    if m == 'service.call':\n"
        "        Path('tok.txt').write_text(str(p.get('_bus_token', '')), encoding='utf-8')\n"
        "        while not Path('rel.txt').exists(): await asyncio.sleep(0.02)\n"
        "        return {'ok': True}\n"
        "    return await Plugin.handle(plugin, m, p)\nplugin.handle = h\n",
    )
    d_cons = _make_bus_def(
        tmp_path, state_dir, "const", [], ["acme.tok"],
        "import json\nfrom cplug_sdk.plugin import HostError, Plugin\nplugin = Plugin()\n"
        "@plugin.tool('call_tok', 'call tok')\nasync def call_tok(args, caller):\n"
        "    try: return await plugin._call('service.call', {'service': 'acme.tok', 'method': 'hold', 'args': {}, '_bus_token': args['tok']})\n"
        "    except HostError as exc: return json.dumps({'code': exc.code, 'reason': exc.reason})\n",
    )
    _install_registry(monkeypatch, [d_prov, d_cons])
    owner_switch.write(state_dir, True)
    app = SimpleNamespace(state=SimpleNamespace(session_manager=None))
    host = Host(state_dir, app=app)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    try:
        rt.supervisor.override_index("provt", True)
        rt.supervisor.override_index("const", True)
        await rt.supervisor.activate(host.sidecar_spec(d_prov))
        await rt.supervisor.activate(host.sidecar_spec(d_cons))
        proc_c = await rt.supervisor.ensure("const")
        assert proc_c is not None
        hold_task = asyncio.create_task(rt.dispatcher.handle(proc_c.spec.ctx, "service.call", {"service": "acme.tok", "method": "hold", "args": {}}))
        tok_file = d_prov.folder / "files" / "tok.txt"
        for _ in range(100):
            if tok_file.exists() and tok_file.read_text(encoding="utf-8"):
                break
            await asyncio.sleep(0.05)
        stolen = tok_file.read_text(encoding="utf-8").strip()
        assert stolen
        sock_path = await rt.socket_manager.ensure(state_dir, proc_c.spec.ctx, rt.dispatcher)
        spoof_resp = await asyncio.to_thread(_sock_rpc, sock_path, {"jsonrpc": "2.0", "id": 1, "method": "service.call", "params": {"service": "acme.tok", "method": "hold", "args": {}, "_bus_token": stolen}})
        assert spoof_resp["error"]["code"] == frames.PERMISSION_DENIED and spoof_resp["error"]["message"] == "permission_denied"
        (d_prov.folder / "files" / "rel.txt").write_text("1", encoding="utf-8")
        assert await hold_task == {"ok": True}
        prov_call_ctx = PluginContext(
            plugin_id="provt", install_key="inst-provt", data_dir=d_prov.folder,
            granted=frozenset({"services:acme.tok"}), services_consumes=("acme.tok",),
        )
        for caller_ctx, tok in ((proc_c.spec.ctx, stolen), (prov_call_ctx, stolen), (proc_c.spec.ctx, "forged_tok")):
            with pytest.raises(guards.Refused) as exc_tok:
                await rt.dispatcher.handle(caller_ctx, "service.call", {"service": "acme.tok", "method": "hold", "args": {}, "_bus_token": tok})
            assert exc_tok.value.code == "permission_denied" and "invalid_bus_token" in str(exc_tok.value)
        for req_id, tok in ((2, stolen), (3, "forged_tok")):
            bad_sock = await asyncio.to_thread(_sock_rpc, sock_path, {"jsonrpc": "2.0", "id": req_id, "method": "service.call", "params": {"service": "acme.tok", "method": "hold", "args": {}, "_bus_token": tok}})
            assert bad_sock["error"]["code"] == frames.PERMISSION_DENIED and bad_sock["error"]["message"] == "permission_denied"
            stdio_res = await proc_c.request("tools/call", {"name": "call_tok", "arguments": {"tok": tok}, "caller": {}})
            assert json.loads(stdio_res["content"][0]["text"]) == {"code": frames.PERMISSION_DENIED, "reason": "permission_denied"}
        ev_roots = ("core.started", "cplugs.foo", "session", "git", "approval", "task", "feed", "webhook", "mcp", "cplug", "cplugs", "system", "core")
        ev_ctx = replace(proc_c.spec.ctx, events_emit=("pulse.ready", "status.changed", *ev_roots),
                         granted=frozenset({"events:pulse.ready", "events:status.changed", *(f"events:{e}" for e in ev_roots)}))
        assert await rt.dispatcher.handle(ev_ctx, "events.emit", {"event": "pulse.ready", "payload": {}}) == {"event": "pulse.ready", "delivered": 0}
        assert await rt.dispatcher.handle(ev_ctx, "events.emit", {"event": "status.changed", "payload": {}}) == {"event": "status.changed", "delivered": 0}
        for bad_ev in ev_roots:
            with pytest.raises(guards.Refused) as exc_ev:
                await rt.dispatcher.handle(ev_ctx, "events.emit", {"event": bad_ev, "payload": {}})
            assert exc_ev.value.code == "permission_denied" and "reserved_event_namespace" in str(exc_ev.value)
    finally:
        await rt.stop()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_defensive_invalid_service_schema_refusal_unit_and_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    d_prov = _make_bus_def(tmp_path, state_dir, "provbad", [{"name": "bad.svc", "methods": ["op"]}], [])
    cons_dir = tmp_path / "code_consbad"
    _write_json_plugin(
        cons_dir,
        {"schema": 2, "id": "consbad", "name": "ConsBad", "version": "1.0.0", "kind": "plugin", "description": "ConsBad", "author": "T",
         "run": {"cmd": ["python3", "main.py"], "mode": "rpc"}, "permissions": {"services": ["bad.svc"]},
         "services": {"consumes": ["bad.svc"]}, "mcp": {"tools": [{"name": "call_bad", "description": "call bad", "gate": "read"}]}},
        "import json\nfrom cplug_sdk.plugin import HostError, Plugin\nplugin = Plugin()\n"
        "@plugin.tool('call_bad', 'call bad')\nasync def call_bad(args, caller):\n"
        "    try: await plugin._call('service.call', {'service': 'bad.svc', 'method': 'op', 'args': {}}); return {'ok': True}\n"
        "    except HostError as exc: return json.dumps({'code': exc.code, 'reason': exc.reason})\n",
    )
    d_cons = _register_and_enable(state_dir, cons_dir, "consbad", "inst-consbad")
    caller_ctx = PluginContext(plugin_id="consbad", install_key="inst-consbad", data_dir=d_cons.folder,
                               granted=frozenset({"services:bad.svc"}), services_consumes=("bad.svc",))
    host = Host(state_dir, app=SimpleNamespace(state=SimpleNamespace(session_manager=None)))
    for bad_schema in ({"type": "bogus_type"}, {"type": "object", "properties": {"s": {"type": "string", "pattern": "[unclosed"}}},
                       {"type": "object", "properties": {"s": {"type": "string", "minLength": "not_int"}}}, {"type": "object", "required": 123},
                       {"$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"}):
        bypassed_prov = replace(d_prov, manifest=replace(d_prov.manifest, services_provides=({"name": "bad.svc", "methods": ["op"], "schemas": {"op": bad_schema}},)))
        bus = plugin_bus.PluginBus(host=host, state_dir=lambda: state_dir, supervisor_getter=lambda: None,
                                   safe_mode_getter=lambda: {"env": False}, on_loop=lambda fn, *a: fn(*a), definitions_getter=lambda: [bypassed_prov])
        disp = HostDispatcher(HostServices(activity=lambda _r: None, service_call=bus.call_service), OwnerTokens(b"k" * 32))
        with pytest.raises(guards.Refused) as exc_unit:
            await disp.handle(caller_ctx, "service.call", {"service": "bad.svc", "method": "op", "args": {}})
        assert exc_unit.value.code == "invalid_params" and exc_unit.value.data["reason"] == "invalid_service_schema"
    bypassed_prov = replace(d_prov, manifest=replace(d_prov.manifest, services_provides=({"name": "bad.svc", "methods": ["op"], "schemas": {"op": {"type": "bogus_type"}}},)))
    _install_registry(monkeypatch, [bypassed_prov, d_cons])
    owner_switch.write(state_dir, True)
    rt = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=SimpleNamespace(session_manager=None)), asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    try:
        rt.supervisor.override_index("provbad", True)
        rt.supervisor.override_index("consbad", True)
        await rt.supervisor.activate(host.sidecar_spec(bypassed_prov))
        await rt.supervisor.activate(host.sidecar_spec(d_cons))
        proc_c = await rt.supervisor.ensure("consbad")
        assert proc_c is not None
        res = await proc_c.request("tools/call", {"name": "call_bad", "arguments": {}, "caller": {}})
        assert json.loads(res["content"][0]["text"]) == {"code": frames.INVALID_PARAMS, "reason": "invalid_params"}
    finally:
        await rt.stop()
