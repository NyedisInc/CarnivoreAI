
from __future__ import annotations

import asyncio
import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.cplugs.runtime import sandbox
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.runtime.process import PluginSpec
from src.cplugs.runtime.supervisor import Supervisor

FIXTURES = Path(__file__).parent / "fixtures"
CHANNEL_TOOLS = ({"name": "send_test", "description": "Send a test alert to the configured channels",
                  "inputSchema": {"type": "object"}, "gate": "inbox"},)

try:
    sandbox.find_interpreter()
    AVAILABLE = os.path.exists("/usr/bin/sandbox-exec")
except sandbox.SandboxUnavailable:
    AVAILABLE = False
if os.environ.get("CARNIVORE_REQUIRE_SANDBOX") == "1" and (not AVAILABLE or sys.platform != "darwin"):
    raise RuntimeError("CARNIVORE_REQUIRE_SANDBOX=1 but this machine cannot run the sandbox (needs macOS sandbox-exec and a framework Python)")
pytestmark = pytest.mark.skipif(not AVAILABLE or sys.platform != "darwin", reason="needs macOS sandbox-exec and the framework Python")


class Rig:

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.fetches: List[Dict[str, Any]] = []
        self.alerts: List[Any] = []
        self.activity: List[Dict[str, Any]] = []

        async def http_fetch(ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
            self.fetches.append({"url": params["url"], "plugin": ctx.plugin_id})
            return {"status": 200, "headers": {}, "body": ""}

        self.services = HostServices(activity=self.activity.append, http_fetch=http_fetch)
        self.dispatcher = HostDispatcher(self.services, OwnerTokens(), home=tmp / "home")
        self.sup = Supervisor(tmp / "state", "9.9.9", self.dispatcher, lambda pid, key, why: self.alerts.append((pid, key, why)),
                              lambda pid: {"inbox": 0, "timers": 0, "routes": 0}, self.activity.append,
                              index={"expires_at": "2999-01-01T00:00:00Z"})

    def spec(self, name: str, fixture: str, granted: set, **kw: Any) -> PluginSpec:
        data = self.tmp / "state" / "cplugs" / ("0" * 31 + str(len(name) % 10))
        data.mkdir(parents=True, exist_ok=True)
        code = self.tmp / "code" / name
        code.mkdir(parents=True, exist_ok=True)
        (code / "main.py").write_text((FIXTURES / fixture / "main.py").read_text())
        ctx = PluginContext(plugin_id=name, install_key="0" * 32, data_dir=data, granted=frozenset(granted),
                            manifest_tools=kw.pop("tools", ()), tier="local")
        return PluginSpec(ctx=ctx, code_dir=code, entry="main", capabilities=frozenset({"events", "tools"}),
                          subscriptions=frozenset(kw.pop("subs", {"alert"})))

    async def stored(self, spec: PluginSpec, key: str, timeout: float = 15.0) -> Any:
        end = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < end:
            value = self.dispatcher.storage(spec.ctx).get(key)
            if value is not None:
                return value
            await asyncio.sleep(0.1)
        raise AssertionError(f"plugin never stored {key}")


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 90))


def test_sns_and_slack_channel_plugin_runs_out_of_process(tmp_path):
    rig = Rig(tmp_path)
    spec = rig.spec("chan", "channel_plugin", {"network_hosts:hooks.slack.com", "network_hosts:sns.us-east-1.amazonaws.com"},
                    tools=CHANNEL_TOOLS)

    async def go():
        assert await rig.sup.enable(spec) == "running"
        proc = rig.sup.process("chan")
        assert proc.negotiated["subscriptions"] == ["alert"]
        assert await proc.deliver_event("alert", 4, {"title": "build done"})
        delivered = await rig.stored(spec, "delivered")
        await rig.sup.shutdown()
        return delivered

    delivered = run(go())
    assert delivered == {"seq": 4, "slack": 200, "sns": 200, "evil": "not_granted"}
    assert [f["url"] for f in rig.fetches] == ["https://hooks.slack.com/services/T0/B0/hook", "https://sns.us-east-1.amazonaws.com/"]
    assert any(a["method"] == "http.fetch" and a["outcome"] == "not_granted" for a in rig.activity)


def _probe(tmp_path):
    rig = Rig(tmp_path)
    secret, other, outside = tmp_path / "config.json", tmp_path / "other-plugin.db", tmp_path / "outside.txt"
    secret.write_text("{}")
    other.write_text("db")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    spec = rig.spec("probe", "probe_plugin", set(), subs={"probe"})

    async def go():
        assert await rig.sup.enable(spec) == "running"
        await rig.sup.process("probe").deliver_event("probe", 1, {
            "secret": str(secret), "other": str(other), "port": listener.getsockname()[1], "outside": str(outside)})
        results = await rig.stored(spec, "probe")
        await rig.sup.shutdown()
        return results

    try:
        return run(go()), outside
    finally:
        listener.close()


DENIED = ("read_secret", "read_other_plugin", "list_tmp", "connect_loopback", "exec_sh", "write_outside", "list_procs")


def test_sandbox_probe_every_denied_action_fails(tmp_path):
    results, outside = _probe(tmp_path)
    for name in DENIED:
        assert results[name] != "ALLOWED", f"{name} was allowed inside the sandbox"
    assert results["write_inside"] == "ALLOWED"
    assert results["procargs_of_parent"] == "ALLOWED"
    assert not outside.exists()
    assert set(results["env_keys"]) <= {"PATH", "HOME", "LANG", "LC_CTYPE", "PYTHONDONTWRITEBYTECODE", "__CF_USER_TEXT_ENCODING"}


def test_sandbox_probe_goes_red_under_a_permissive_profile(tmp_path, monkeypatch):
    real = sandbox.render_profile
    monkeypatch.setattr(sandbox, "render_profile", lambda layout: real(layout) + (
        '(allow network*)\n(allow sysctl-read)\n(allow file-read* (subpath "/private/var") (subpath "/private/tmp"))\n'
        '(allow file-write* (subpath "/private/var"))\n'))
    results, _ = _probe(tmp_path)
    assert [n for n in DENIED if results[n] == "ALLOWED"], "the probe stayed green against a profile with no sandbox"


def test_a_hostile_frame_the_rss_watchdog_and_a_tool_rug_pull_each_end_the_process(tmp_path):
    rig = Rig(tmp_path)
    raw = rig.spec("rawer", "probe_plugin", set(), subs={"raw"})
    fat = rig.spec("fatty", "probe_plugin", set(), subs={"alloc"})
    pulled = rig.spec("pulled", "channel_plugin", set(), tools=({**CHANNEL_TOOLS[0], "description": "something else"},))

    async def wait_ended(name: str, timeout: float = 20.0) -> str:
        proc = rig.sup.process(name)
        end = asyncio.get_running_loop().time() + timeout
        while proc.ended is None and asyncio.get_running_loop().time() < end:
            await asyncio.sleep(0.1)
        return proc.ended

    async def go():
        assert await rig.sup.enable(raw) == "running"
        await rig.sup.process("rawer").deliver_event("raw", 1, {})
        first = await wait_ended("rawer")
        assert await rig.sup.enable(fat) == "running"
        await rig.sup.process("fatty").deliver_event("alloc", 1, {"mb": 220})
        second = await wait_ended("fatty")
        await rig.sup.enable(pulled)
        third = rig.sup.process("pulled").ended
        await rig.sup.shutdown()
        return first, second, third

    first, second, third = run(go())
    assert first == "violation:id_not_increasing"
    assert second == "resource_abuse"
    assert third == "integrity"
    assert ("pulled", "integrity", "integrity") in rig.alerts


def test_safe_mode_spawns_nothing(tmp_path):
    rig = Rig(tmp_path)
    rig.sup.set_safe_mode(True)
    spec = rig.spec("chan", "channel_plugin", set())
    assert run(rig.sup.enable(spec)) == "disabled (safe mode)"
    assert rig.sup.process("chan") is None


def test_three_crashes_in_ten_minutes_auto_disable_and_cancel_side_effects(tmp_path):
    rig = Rig(tmp_path)
    cancelled: List[str] = []

    async def instant(seconds: float) -> None:
        await asyncio.sleep(0)

    rig.sup = Supervisor(tmp_path / "state", "9.9.9", rig.dispatcher, lambda pid, key, why: rig.alerts.append((pid, key, why)),
                         lambda pid: cancelled.append(pid) or {"inbox": 2}, rig.activity.append, sleep=instant,
                         index={"expires_at": "2999-01-01T00:00:00Z"})
    spec = rig.spec("crashy", "channel_plugin", set())
    (spec.code_dir / "main.py").write_text((FIXTURES / "crash_plugin_main.py").read_text())

    async def go():
        await rig.sup.enable(spec)
        for _ in range(200):
            if rig.sup.state("crashy") == "crash_loop":
                break
            await asyncio.sleep(0.05)
        reached = rig.sup.state("crashy")
        await rig.sup.shutdown()
        return reached

    assert run(go()) == "crash_loop"
    assert ("crashy", "crash_loop", "exited") in rig.alerts
    assert cancelled == ["crashy"]
    assert any(a["method"] == "side_effects.cancel" and a["detail"] == "inbox=2" for a in rig.activity)
