
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_spec import build_spec
from src.plugins.runtime import sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.supervisor import Supervisor

try:
    sandbox.find_interpreter()
    AVAILABLE = os.path.exists("/usr/bin/sandbox-exec")
except sandbox.SandboxUnavailable:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE or sys.platform != "darwin", reason="needs macOS sandbox-exec and framework Python")


@pytest.mark.asyncio
async def test_real_sandbox_exec_v2_manifest_ui_tool_and_timer(tmp_path: Path) -> None:
    code = tmp_path / "code" / "v3smoke"
    code.mkdir(parents=True, exist_ok=True)
    (code / "main.py").write_text(
        """
from cplug_sdk import Plugin

plugin = Plugin()

@plugin.tool("ping_v3", "Return pong", {"type": "object"}, gate="read")
async def ping_v3(args, caller):
    return f"pong:{args.get('msg', '')}"

@plugin.ui("widget")
async def widget(params):
    return {"schema": 1, "root": {"type": "text", "value": f"v3:{params.get('tag', 'ok')}"}}

@plugin.timer("beat")
async def beat(scheduled_for):
    await plugin.host.storage.put(key="last_tick", value=scheduled_for)

@plugin.on_event("feed.meta")
async def on_meta(seq, payload):
    await plugin.host.storage.put(key="last_meta", value={"seq": seq, "payload": payload})
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "v3smoke"
name = "V3 Smoke"
version = "1.0.0"
kind = "plugin"
description = "Sandbox v3 smoke plugin"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[permissions]
read = ["feed.meta"]

[timers.beat]
every_seconds = 5

[mcp]
[[mcp.tools]]
name = "ping_v3"
description = "Return pong"
gate = "read"
inputSchema = { type = "object" }

[events]
on = ["feed.meta"]
""",
        encoding="utf-8",
    )

    sm = load_sidecar_manifest(code, "v3smoke")
    data_dir = tmp_path / "state" / "cplugs" / ("a" * 32)
    data_dir.mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(manifest=sm, item_id="local/v3smoke", install_key="a" * 32, code_root=code, folder=data_dir)
    spec = build_spec(defn, frozenset({"feed.view: meta"}), settings={})

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
    try:
        state = await sup.activate(spec)
        assert state == "running"
        proc = await sup.ensure("v3smoke")
        assert proc is not None

        tool_res = await proc.request("tools/call", {"name": "ping_v3", "arguments": {"msg": "hello"}, "caller": {"kind": "owner"}})
        assert tool_res["content"][0]["text"] == "pong:hello"

        ui_res = await proc.request("ui.render", {"surface": "widget", "params": {"tag": "live"}})
        assert ui_res == {"document": {"schema": 1, "root": {"type": "text", "value": "v3:live"}}}

        await proc.request("timer.tick", {"name": "beat", "scheduled_for": 1700000123})
        assert dispatcher.storage(spec.ctx).get("last_tick") == 1700000123

        assert await sup.deliver_event("v3smoke", "feed.meta", 1, {"reason": "created"}) is True
        for _ in range(40):
            if dispatcher.storage(spec.ctx).get("last_meta") is not None:
                break
            await asyncio.sleep(0.05)
        assert dispatcher.storage(spec.ctx).get("last_meta") == {"seq": 1, "payload": {"reason": "created"}}
    finally:
        await sup.shutdown()


@pytest.mark.asyncio
async def test_real_sandbox_exec_v2_tool_omitted_input_schema_passes_pin(tmp_path: Path) -> None:
    code = tmp_path / "code" / "noschema"
    code.mkdir(parents=True, exist_ok=True)
    (code / "main.py").write_text(
        """
from cplug_sdk import Plugin

plugin = Plugin()

@plugin.tool("read_info", "Read info", gate="read")
async def read_info(args, caller):
    return "ok"
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "noschema"
name = "No Schema"
version = "1.0.0"
kind = "plugin"
description = "Omits optional inputSchema on tool"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[mcp]
[[mcp.tools]]
name = "read_info"
description = "Read info"
gate = "read"
""",
        encoding="utf-8",
    )

    sm = load_sidecar_manifest(code, "noschema")
    data_dir = tmp_path / "state" / "cplugs" / ("b" * 32)
    data_dir.mkdir(parents=True, exist_ok=True)
    defn = SidecarDefinition(manifest=sm, item_id="local/noschema", install_key="b" * 32, code_root=code, folder=data_dir)
    spec = build_spec(defn, frozenset(), settings={})

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
    try:
        state = await sup.enable(spec)
        assert state == "running"
        proc = await sup.ensure("noschema")
        assert proc is not None
        res = await proc.request("tools/call", {"name": "read_info", "arguments": {}, "caller": {"kind": "owner"}})
        assert res["content"][0]["text"] == "ok"
    finally:
        await sup.shutdown()
