
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.host import owner_switch, sidecar_boot
from src.cplugs.runtime import sandbox
from src.cplugs.runtime.children import ChildLedger
from src.cplugs.runtime.dispatch import PluginContext
from src.cplugs.runtime.process import PluginSpec
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401

FIXTURE = Path(__file__).parent / "runtime" / "fixtures" / "probe_plugin" / "main.py"
CANARY = "CANARY-9f3b1c-never-in-a-child"

try:
    sandbox.find_interpreter()
    AVAILABLE = os.path.exists("/usr/bin/sandbox-exec") and sys.platform == "darwin"
except sandbox.SandboxUnavailable:
    AVAILABLE = False
if os.environ.get("CARNIVORE_REQUIRE_SANDBOX") == "1" and not AVAILABLE:
    raise RuntimeError("CARNIVORE_REQUIRE_SANDBOX=1 but this machine cannot run the sandbox (needs macOS sandbox-exec and a framework Python)")
needs_sandbox = pytest.mark.skipif(not AVAILABLE, reason="needs macOS sandbox-exec and the framework Python")


def build(tmp: Path, *, env_safe: bool = False, loop=None):
    alerts, published = [], []
    host = SimpleNamespace(state_dir=tmp / "state", publish=published.append, install_key=lambda name: name)
    app = SimpleNamespace(state=SimpleNamespace())
    rt = sidecar_boot.SidecarRuntime(host, app, loop or asyncio.new_event_loop(), env_safe=lambda: env_safe, app_version="9.9.9",
                                     raise_alert=lambda key, **kw: alerts.append((key, kw)))
    return rt, alerts, published


def spec(tmp: Path) -> PluginSpec:
    data, code = tmp / "state" / "cplugs" / ("0" * 32), tmp / "code" / "probe"
    data.mkdir(parents=True, exist_ok=True)
    code.mkdir(parents=True, exist_ok=True)
    (code / "main.py").write_text(FIXTURE.read_text())
    ctx = PluginContext(plugin_id="probe", install_key="0" * 32, data_dir=data, granted=frozenset(), manifest_tools=(), tier="local")
    return PluginSpec(ctx=ctx, code_dir=code, entry="main", capabilities=frozenset({"events", "tools"}), subscriptions=frozenset({"probe"}))


def test_switch_off_or_env_safe_mode_spawns_nothing_and_raises_the_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "probe", lambda *a, **k: pytest.fail("boot must not probe the sandbox"))
    for env_safe, switched in ((False, False), (True, True)):
        rt, alerts, _ = build(tmp_path / f"{env_safe}", env_safe=env_safe)

        async def go():
            await rt.start()
            if switched:
                owner_switch.write(rt.state_dir, True)
                await rt._apply()
            return await rt.supervisor.enable(spec(tmp_path / f"{env_safe}"))

        assert asyncio.run(go()) == "disabled (safe mode)", (env_safe, switched)
        assert rt.supervisor.process("probe") is None
        assert [k for k, _ in alerts] == ["cplug.probe.safe_mode"]
        assert not (rt.state_dir / "cplugs" / "children.json").exists()
    assert not owner_switch.read(tmp_path / "False" / "state")
    assert not owner_switch.switch_path(tmp_path / "False" / "state").exists()


@needs_sandbox
def test_switched_on_the_fixture_runs_in_the_real_sandbox_and_a_host_secret_never_reaches_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CPLUG_TEST_CANARY", CANARY)
    rt, alerts, _ = build(tmp_path)
    plugin = spec(tmp_path)

    async def go():
        await rt.start()
        assert await rt.set_switch(True)
        assert rt.status()["sandbox"]["ok"] is True
        state = await rt.supervisor.enable(plugin)
        proc = rt.supervisor.process("probe")
        pid = proc.pid
        seen = subprocess.run(["ps", "eww", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False).stdout
        recorded = json.loads((rt.state_dir / "cplugs" / "children.json").read_text())["children"]
        argv = sandbox.build_command(proc._layout, rt.state_dir / "p.sb", "main", 1024)
        env = sandbox.allow_env(proc._layout, "en")
        await rt.stop()
        return state, seen, recorded, pid, argv, env

    state, seen, recorded, pid, argv, env = asyncio.run(go())
    assert state == "running" and not alerts
    assert "PATH=" in seen, "ps could not show the child's environment, so the leak check below would prove nothing"
    assert CANARY not in seen and CANARY not in " ".join(argv) and CANARY not in json.dumps(env)
    assert recorded["probe"]["pid"] == pid
    assert not json.loads((rt.state_dir / "cplugs" / "children.json").read_text())["children"]


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(["sleep", "300"], start_new_session=True)


def test_orphan_is_killed_when_pid_and_lstart_match_and_left_alone_when_lstart_differs(tmp_path):
    mine, stranger = _sleeper(), _sleeper()
    try:
        ledger = ChildLedger(tmp_path / "state")
        assert ledger.record("mine", mine.pid) and ledger.record("stranger", stranger.pid)
        path = tmp_path / "state" / "cplugs" / "children.json"
        data = json.loads(path.read_text())
        data["children"]["stranger"]["started_lstart"] = "Thu Jan  1 00:00:00 1970"
        path.write_text(json.dumps(data))
        rt, _, _ = build(tmp_path)
        asyncio.run(rt.start())
        assert mine.wait(timeout=10) is not None
        assert stranger.poll() is None
        assert json.loads(path.read_text()) == {"children": {}}
    finally:
        for p in (mine, stranger):
            p.kill()
            p.wait()


def test_an_api_key_is_refused_on_both_routes_and_the_owner_is_not(client, owner_jwt, key_store, tmp_path):  # noqa: F811
    from src.main import app

    _row, secret = key_store.create("script")
    rt, _, _ = build(tmp_path)
    app.state.sidecar_runtime = rt
    try:
        for path, body in (("/api/v1/cplug-owner/switch", {"enabled": True}), ("/api/v1/cplugs/safe-mode", {"on": True})):
            r = client.put(path, json=body, headers=bearer(secret))
            assert r.status_code == 403 and r.json()["detail"] == {"reason": "api_key_forbidden"}, (path, r.text)
        assert client.get("/api/v1/cplug-owner/switch", headers=bearer(secret)).status_code == 403
        assert not owner_switch.read(rt.state_dir)
        r = client.put("/api/v1/cplug-owner/switch", json={"enabled": False}, headers=bearer(owner_jwt))
        assert r.status_code == 200 and r.json()["enabled"] is False
        r = client.put("/api/v1/cplugs/safe-mode", json={"on": True}, headers=bearer(owner_jwt))
        assert r.status_code == 200 and r.json()["safe_mode"]["active"] is True
    finally:
        del app.state.sidecar_runtime


def test_boot_installs_the_sidecar_registry_and_reads_the_ledger_only_when_a_database_exists(tmp_path):
    from src.cplugs.host import sidecar_registry

    sidecar_registry.install(None)
    try:
        rt, _, _ = build(tmp_path)
        assert rt._ledger_rows() == []
        loaded = []
        rt._ledger_rows = lambda: loaded.append(1) or []
        asyncio.run(rt.start())
        assert loaded, "boot never read the install ledger"
        assert sidecar_registry.current() is not None and sidecar_registry.listed() == ()
    finally:
        sidecar_registry.install(None)


def test_one_child_whose_stop_raises_does_not_shield_the_later_recorded_children(tmp_path, monkeypatch):
    from src.core.automations import lifecycle

    first, second = _sleeper(), _sleeper()
    try:
        ledger = ChildLedger(tmp_path / "state")
        assert ledger.record("first", first.pid) and ledger.record("second", second.pid)
        real = lifecycle.stop_orphan

        def flaky(rec):
            if rec["pid"] == first.pid:
                raise PermissionError(1, "Operation not permitted")
            return real(rec)

        monkeypatch.setattr(lifecycle, "stop_orphan", flaky)
        outcome = ledger.reap()
        assert outcome["first"] == "left" and outcome["second"] == "stopped"
        assert second.wait(timeout=10) is not None and first.poll() is None
    finally:
        for p in (first, second):
            p.kill()
            p.wait()


def test_switch_safe_mode_and_a_supervisor_hold_publish_the_cplugs_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "probe", lambda *a, **k: SimpleNamespace(ok=True, detail=""))
    rt, _, published = build(tmp_path)

    async def go():
        rt.loop = asyncio.get_running_loop()
        await rt.set_switch(True)
        await rt.set_safe_mode(True)
        rt._supervisor_alert("probe", "revoked", "withdrawn")
        await asyncio.sleep(0)

    asyncio.run(go())
    assert published.count("cplugs") == 3
