
from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.notifications.contracts import NotifyEvent
from src.core.plugin_studio import actions as studio_actions, dev_session, inspector_preview, store as studio_store
from src.plugins.host import developer_mode, plugin_channels, runtime as host_runtime, sidecar_routes
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime.process import PluginProcess
from src.plugins.runtime.supervisor import SupervisorError
from tests.helpers.plugins_v3_e2e_world import DARWIN_SANDBOX, build_plugins_v3_world
from tests.helpers.plugins_v3_polyglot_fixtures import DEFAULT_MIT_LICENSE, write_plugin_files
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _plugin_files(
    plugin_id: str,
    ver: str = "0.1.0",
    *,
    timers_toml: str = "",
    routes_toml: str = "",
    ui_widget: bool = False,
    crash_init: bool = False,
) -> Dict[str, str]:
    toml = (
        f'schema = 2\nid = "{plugin_id}"\nname = "{plugin_id.title()}"\nversion = "{ver}"\n'
        f'kind = "plugin"\ndescription = "R6 regression plugin"\nauthor = "Tester"\nlicense = "MIT"\ntier = "local"\n'
        '[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n'
        '[mcp]\n[[mcp.tools]]\nname = "ping"\ndescription = "Return version"\ngate = "read"\n'
        'inputSchema = { type = "object", properties = {} }\n'
    )
    if routes_toml:
        toml += routes_toml
    if ui_widget:
        toml += '[ui.widget]\ntitle = "Widget"\nmode = "declarative"\n'
    if timers_toml:
        toml += timers_toml

    if crash_init:
        main_py = "import sys\nsys.exit(1)\n"
    else:
        main_py = (
            "from cplug_sdk import Plugin\n"
            "plugin = Plugin()\n"
            '@plugin.tool("ping", "Return version", {"type": "object", "properties": {}}, gate="read")\n'
            "async def ping(_args, _caller):\n"
            f'    return {{"v": "{ver}"}}\n'
        )
        if ui_widget:
            main_py += (
                '@plugin.ui("widget")\n'
                "async def draw_widget(_params):\n"
                f'    return {{"schema": 2, "root": {{"type": "text", "value": "ok-{ver}"}}}}\n'
            )
    return {"carnivore.toml": toml, "main.py": main_py, "LICENSE.md": DEFAULT_MIT_LICENSE}


def _track_spawns(monkeypatch: pytest.MonkeyPatch, plugin_id: str) -> List[int]:
    spawned: List[int] = []
    orig_start = PluginProcess.start

    async def _wrapped_start(self: PluginProcess) -> None:
        try:
            await orig_start(self)
        finally:
            if self.spec.ctx.plugin_id == plugin_id and self.pid is not None:
                spawned.append(self.pid)

    monkeypatch.setattr(PluginProcess, "start", _wrapped_start)
    return spawned




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r6_supervisor_error_subclasses_runtime_error_on_forget_live_or_busy(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    assert issubclass(SupervisorError, RuntimeError)
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "supe_src", _plugin_files("supeplug"))
        w.sideload_and_enable(src, "supeplug")
        assert w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "supeplug", "tool": "ping", "args": {}}, headers=w.owner_headers).status_code == 200

        with pytest.raises(SupervisorError):
            w.rt.supervisor.forget("supeplug")
        with pytest.raises(RuntimeError):
            w.rt.supervisor.forget("supeplug")

        assert w.client.portal is not None
        w.client.portal.call(w.rt.supervisor.disable, "supeplug")
        entered = threading.Event()
        release = threading.Event()

        async def _hold() -> None:
            async with w.rt.supervisor._hold_lock("supeplug"):
                entered.set()
                await asyncio.to_thread(release.wait, 5.0)

        t = threading.Thread(target=lambda: w.client.portal.call(_hold), daemon=True)
        t.start()
        assert entered.wait(timeout=4.0)
        try:
            with pytest.raises(SupervisorError):
                w.rt.supervisor.forget("supeplug")
        finally:
            release.set()
            t.join(timeout=5.0)




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r6_bug1_studio_install_then_dev_start_spawns_one_process_no_orphans(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        monkeypatch.setattr(developer_mode, "is_on", lambda: True)
        ws_dir = w.state / "plugin-studio" / "workspaces" / "r6instdev"
        write_plugin_files(ws_dir, _plugin_files("r6instdev"))
        row = studio_store.upsert_workspace(
            w.state,
            {"studio_id": "ws-r6instdev", "plugin_id": "r6instdev", "name": "R6InstDev", "folder": str(ws_dir)},
        )
        spawned = _track_spawns(monkeypatch, "r6instdev")
        assert w.client.portal is not None

        inst = w.client.portal.call(studio_actions.install_workspace, w.app, ws_dir)
        assert inst["ok"] is True
        assert spawned == []

        mgr = dev_session.manager_for(w.app)
        res = w.client.portal.call(mgr.start, "ws-r6instdev", row)
        assert res["active"] is True
        assert len(spawned) == 1, f"expected single spawn, got {spawned}"

        proc = w.rt.supervisor.process("r6instdev")
        assert proc is not None and proc.pid == spawned[0] and _pid_alive(proc.pid)

        w.client.portal.call(mgr.stop, "ws-r6instdev", row)
        w.client.portal.call(w.rt.supervisor.shutdown)
        assert not any(_pid_alive(pid) for pid in spawned), f"orphaned PIDs after shutdown: {spawned}"


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r6_bug1_fresh_dev_start_with_timers_spawns_one_process_no_orphans(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        monkeypatch.setattr(developer_mode, "is_on", lambda: True)
        ws_dir = w.state / "plugin-studio" / "workspaces" / "r6timers"
        write_plugin_files(ws_dir, _plugin_files("r6timers", timers_toml="[timers.beat]\nevery_seconds = 60\n"))
        row = studio_store.upsert_workspace(
            w.state,
            {"studio_id": "ws-r6timers", "plugin_id": "r6timers", "name": "R6Timers", "folder": str(ws_dir)},
        )
        spawned = _track_spawns(monkeypatch, "r6timers")
        assert w.client.portal is not None

        mgr = dev_session.manager_for(w.app)
        res = w.client.portal.call(mgr.start, "ws-r6timers", row)
        assert res["active"] is True
        assert len(spawned) == 1, f"expected single spawn for [timers] plugin, got {spawned}"

        proc = w.rt.supervisor.process("r6timers")
        assert proc is not None and proc.pid == spawned[0] and _pid_alive(proc.pid)

        w.client.portal.call(mgr.stop, "ws-r6timers", row)
        w.client.portal.call(w.rt.supervisor.shutdown)
        assert not any(_pid_alive(pid) for pid in spawned), f"orphaned PIDs after shutdown: {spawned}"


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r6_bug1_direct_supervisor_enable_twice_stops_proc1_and_leaves_zero_orphans(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        src = write_plugin_files(tmp_path / "en2_src", _plugin_files("r6en2"))
        w.sideload_and_enable(src, "r6en2")

        defn = host_runtime.find("r6en2")
        assert defn is not None
        spec = w.host.sidecar_spec(defn)
        assert w.client.portal is not None

        assert w.client.portal.call(w.rt.supervisor.enable, spec) == "running"
        proc1 = w.rt.supervisor.process("r6en2")
        assert proc1 is not None and proc1.pid is not None and _pid_alive(proc1.pid)
        pid1 = proc1.pid

        assert w.client.portal.call(w.rt.supervisor.enable, spec) == "running"
        proc2 = w.rt.supervisor.process("r6en2")
        assert proc2 is not None and proc2 is not proc1 and proc2.pid is not None and proc2.pid != pid1
        assert not _pid_alive(pid1), f"proc1 PID {pid1} leaked as orphan after second enable()"
        assert proc1.ended == "restart"
        assert _pid_alive(proc2.pid)

        w.client.portal.call(w.rt.supervisor.shutdown)
        assert not _pid_alive(pid1) and not _pid_alive(proc2.pid)




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_r6_bug2_spawn_failure_process_ended_and_timeout_leave_procs_empty_and_preview_recovers(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        assert w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
        monkeypatch.setattr(developer_mode, "is_on", lambda: True)
        assert w.client.portal is not None

        src_crash = write_plugin_files(
            tmp_path / "crashinit_src",
            _plugin_files("r6crash", routes_toml='[ui]\nroutes = ["ping"]\n', crash_init=True),
        )
        w.sideload_and_enable(src_crash, "r6crash")
        r_route = w.client.get("/api/v1/cplugs/r6crash/r/ping", headers=w.owner_headers)
        assert r_route.status_code == 409
        assert r_route.json()["detail"]["code"] == "cplug_not_running"
        assert w.rt.supervisor._procs.get("r6crash") is None
        assert w.rt.supervisor.process("r6crash") is None
        assert w.client.portal.call(w.rt.supervisor.ensure, "r6crash") is None
        assert w.rt.supervisor.process("r6crash") is None

        src_to = write_plugin_files(tmp_path / "to_src", _plugin_files("r6to", ui_widget=True))
        w.sideload_and_enable(src_to, "r6to")
        orig_start = PluginProcess.start

        async def _timeout_once(self: PluginProcess) -> None:
            if self.spec.ctx.plugin_id == "r6to":
                raise asyncio.TimeoutError("simulated init timeout")
            await orig_start(self)

        monkeypatch.setattr(PluginProcess, "start", _timeout_once)
        assert w.client.portal.call(w.rt.supervisor.ensure, "r6to") is None
        assert w.rt.supervisor._procs.get("r6to") is None
        assert w.rt.supervisor.process("r6to") is None
        assert w.rt.supervisor._restarts.get("r6to") is None
        monkeypatch.setattr(PluginProcess, "start", orig_start)

        ws_dir = w.state / "plugin-studio" / "workspaces" / "r6prev"
        write_plugin_files(ws_dir, _plugin_files("r6prev", ui_widget=True, crash_init=True))
        row = studio_store.upsert_workspace(
            w.state,
            {"studio_id": "ws-r6prev", "plugin_id": "r6prev", "name": "R6Prev", "folder": str(ws_dir)},
        )
        inst = w.client.portal.call(studio_actions.install_workspace, w.app, ws_dir)
        assert inst["ok"] is True
        assert w.rt.supervisor.state("r6prev") == "idle"

        prev1 = w.client.portal.call(inspector_preview.preview_render, w.app, "ws-r6prev", row)
        assert prev1["errors"] and prev1["errors"][0]["code"] == "cplug_not_running"
        assert w.rt.supervisor.process("r6prev") is None
        assert w.rt.supervisor._procs.get("r6prev") is None

        fixed_files = _plugin_files("r6prev", ver="0.2.0", ui_widget=True, crash_init=False)
        (ws_dir / "main.py").write_text(fixed_files["main.py"], encoding="utf-8")
        from src.plugins.host import sideload_routes  # noqa: PLC0415

        w.client.portal.call(sideload_routes.sync_folder, w.rt, ws_dir, None)
        defn_fixed = host_runtime.find("r6prev")
        assert defn_fixed is not None
        dev_session._consent_and_enable_blocking(w.state, defn_fixed.manifest, auto_approve=True)
        assert w.client.portal.call(w.rt.supervisor.activate, w.host.sidecar_spec(defn_fixed)) == "idle"
        assert w.rt.supervisor.process("r6prev") is None

        prev2 = w.client.portal.call(inspector_preview.preview_render, w.app, "ws-r6prev", row)
        assert prev2["errors"] == [], prev2
        assert prev2["kind"] == "declarative"
        assert prev2["doc"] is not None
        assert prev2["doc"]["root"]["value"] == "ok-0.2.0"
        proc_ok = w.rt.supervisor.process("r6prev")
        assert proc_ok is not None and proc_ok.ended is None


@pytest.mark.asyncio
async def test_r6_bug2_hardened_callers_reject_ended_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    plug_dir = write_plugin_files(tmp_path / "deadplug", _plugin_files("deadplug", ui_widget=True, routes_toml='[ui]\nroutes = ["ping"]\n'))
    manifest = load_sidecar_manifest(plug_dir, "deadplug", allow_local=True)
    defn = SidecarDefinition(
        manifest=manifest,
        item_id="local/deadplug",
        install_key="dead-key",
        code_root=plug_dir,
        folder=plug_dir,
    )

    called = {"rpc": 0}

    class _DeadProc:
        ended = "exited"

        async def request(self, *_a: Any, **_k: Any) -> Any:
            called["rpc"] += 1
            return {}

    dead = _DeadProc()

    class _StubSup:
        def process(self, _pid: str) -> Any:
            return dead

        async def ensure(self, _pid: str) -> Any:
            return dead

        def state(self, _pid: str) -> str:
            return "running"

        def is_paused(self, _pid: str) -> bool:
            return False

    stub_sup = _StubSup()
    stub_rt = SimpleNamespace(supervisor=stub_sup, state_dir=state, safe_mode=lambda: {"env": False, "owner": False, "off": False})
    stub_host = SimpleNamespace(
        state_dir=state,
        enabled=lambda _pid: True,
        sidecar_runtime=lambda: stub_rt,
        install_key=lambda _pid: "dead-key",
    )
    stub_app = SimpleNamespace(state=SimpleNamespace(sidecar_runtime=stub_rt, cplugs_host=stub_host))

    monkeypatch.setattr(host_runtime, "find", lambda pid: defn if pid == "deadplug" else None)
    prev = await inspector_preview.preview_render(stub_app, "ws-dead", {"plugin_id": "deadplug", "folder": str(plug_dir)})
    assert prev["errors"] and prev["errors"][0]["code"] == "cplug_not_running"

    monkeypatch.setattr(host_runtime, "host_for", lambda _app: stub_host)
    req = SimpleNamespace(app=stub_app)
    with pytest.raises(Exception) as exc_info:
        await sidecar_routes._target(req, "deadplug", "ping")
    assert getattr(exc_info.value, "status_code", None) == 409
    assert exc_info.value.detail["code"] == "cplug_not_running"

    sender = plugin_channels.PluginChannelSender(stub_host, "deadplug", "alerts", {"kind": "rpc"})
    ev = NotifyEvent(
        type_id="t1", kind="test", title="Hi", details="Body", severity="info",
        project="p", session_id="s1", session_ref="s1", ts=1.0,
    )
    ch_res = await sender._send_rpc(defn, ev, {}, time.monotonic())
    assert ch_res.ok is False and ch_res.detail == "not_running"

    from src.plugins.host import sidecar_boot, sidecar_registry

    monkeypatch.setattr(sidecar_registry, "find", lambda pid: defn if pid == "deadplug" else None)
    fake_boot = SimpleNamespace(_mcp_health_owner="deadplug", supervisor=stub_sup)
    mcp_res = await sidecar_boot.SidecarRuntime._render_mcp_status(fake_boot)
    assert mcp_res is None
    assert called["rpc"] == 0
