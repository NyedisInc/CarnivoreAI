
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import List

import pytest

from src.plugins.host import sidecar_registry, sidecar_spec, ui_doc
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.runtime import sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.supervisor import Supervisor


def _can_run_darwin_sandbox() -> bool:
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    try:
        sandbox.find_interpreter()
        return True
    except sandbox.SandboxUnavailable:
        return False


DARWIN_SANDBOX = _can_run_darwin_sandbox()


def _has_runtime(finder) -> bool:
    try:
        finder()
        return True
    except sandbox.SandboxUnavailable:
        return False


def _write_ts_plugin(code_dir: Path, *, cmd: List[str], mode: str, ext: str = "mjs") -> None:
    code_dir.mkdir(parents=True, exist_ok=True)
    entry = f"main.{ext}"
    (code_dir / "carnivore.toml").write_text(
        "\n".join([
            "schema = 2",
            'id = "tssdkdemo"',
            'name = "TS SDK Demo"',
            'version = "1.0.0"',
            'kind = "plugin"',
            'description = "TS SDK sandbox integration fixture"',
            'author = "Tester"',
            "",
            "[run]",
            f"cmd = {json.dumps(cmd)}",
            f'mode = "{mode}"',
            "",
            "[permissions]",
            'read = ["sessions"]',
            'services = ["math.v1"]',
            'events = ["demo.ping"]',
            "",
            "[services]",
            'consumes = ["math.v1"]',
            "",
            "[events]",
            'on = ["demo.ping"]',
            'emit = ["demo.pong"]',
            "",
            "[timers]",
            "heartbeat = { every_seconds = 60 }",
            "",
            "[webhooks.github]",
            'hmac_secret = "gh_secret"',
            "",
            "[ui]",
            'routes = ["status"]',
            "",
            "[[mcp.tools]]",
            'name = "ts_echo"',
            'description = "Echo and call host"',
            'gate = "read"',
            'inputSchema = { type = "object", properties = { msg = { type = "string" } } }',
            "",
        ]),
        encoding="utf-8",
    )
    (code_dir / entry).write_text(
        """import { Plugin } from "@carnivore/plugin-sdk";

const plugin = new Plugin()
  .tool(
    "ts_echo",
    "Echo and call host",
    { type: "object", properties: { msg: { type: "string" } } },
    "read",
    async (args) => {
      console.log("debug stdout line must go to stderr, not stdio JSON-RPC");
      const sess = await plugin.host.sessions.list();
      await plugin.host.storage.put("last", args.msg ?? "none");
      const got = await plugin.host.storage.get("last");
      const svc = await plugin.host.service.call("math.v1", "add", { a: 1, b: 2 });
      const ev = await plugin.host.events.emit("demo.pong", { ok: true });
      return { msg: args.msg, sessions: sess.sessions.length, stored: got.value, svc, ev };
    },
  )
  .route("status", async (req) => ({ status: 200, body: { ok: true, route: req.route } }))
  .ui("widget", async () => ({
    schema: 1,
    root: { type: "section", title: "TS Widget", children: [{ type: "text", value: "Live" }] },
  }))
  .timer("heartbeat", async (ts) => {
    await plugin.host.storage.put("timer_ts", ts);
  })
  .webhook("github", async (payload) => {
    await plugin.host.storage.put("hook_payload", payload);
  });

await plugin.serve();
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize(
    ("runtime_name", "finder", "cmd", "mode"),
    [
        ("node", sandbox._find_node, ["node", "main.mjs"], "rpc"),
        ("node", sandbox._find_node, ["node", "main.mjs"], "oneshot"),
        ("bun", sandbox._find_bun, ["bun", "main.ts"], "rpc"),
        ("bun", sandbox._find_bun, ["bun", "main.ts"], "oneshot"),
    ],
)
async def test_ts_sdk_runs_in_sandbox_without_plugin_node_modules(
    tmp_path: Path,
    runtime_name: str,
    finder,
    cmd: List[str],
    mode: str,
) -> None:
    if not _has_runtime(finder):
        pytest.skip(f"{runtime_name} runtime not installed")

    code_dir = tmp_path / "code"
    ext = "ts" if cmd[-1].endswith(".ts") else "mjs"
    _write_ts_plugin(code_dir, cmd=cmd, mode=mode, ext=ext)
    assert not (code_dir / "node_modules").exists()

    state_dir = tmp_path / "state"
    data_dir = state_dir / "cplugs" / "inst-ts-1"
    (data_dir / "files").mkdir(parents=True, exist_ok=True)

    manifest = load_sidecar_manifest(code_dir, "tssdkdemo", allow_local=True)
    defn = sidecar_registry.SidecarDefinition(
        manifest=manifest,
        item_id="local/tssdkdemo",
        install_key="inst-ts-1",
        code_root=code_dir,
        folder=data_dir,
    )
    grants = frozenset(manifest.permissions) | frozenset({"services:math.v1", "events:demo.pong"})
    spec = sidecar_spec.build_spec(defn, grants, {}, consented=True, consent_owed=False)

    async def _list_sessions():
        return [{"session": {"id": "ses_1"}, "label": "main"}]

    async def _svc_call(_ctx, service, method, args):
        return {"service": service, "method": method, "sum": args["a"] + args["b"]}

    async def _events_emit(_ctx, event, payload):
        return {"event": event, "emitted": True, "payload": payload}

    disp = HostDispatcher(
        HostServices(
            activity=lambda _r: None,
            list_sessions=_list_sessions,
            service_call=_svc_call,
            events_emit=_events_emit,
        ),
        OwnerTokens(b"t" * 32),
    )
    sup = Supervisor(
        state_dir,
        "1.0.0",
        disp,
        lambda _pid, _k, _r: None,
        lambda _pid: {},
        lambda _r: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )
    try:
        st = await sup.enable(spec)
        assert st == "running"
        proc = sup.process("tssdkdemo")
        assert proc is not None

        tool_res = await proc.request("tools/call", {"name": "ts_echo", "arguments": {"msg": "hi"}})
        parsed = json.loads(tool_res["content"][0]["text"])
        assert parsed == {
            "msg": "hi",
            "sessions": 1,
            "stored": "hi",
            "svc": {"service": "math.v1", "method": "add", "sum": 3},
            "ev": {"event": "demo.pong", "emitted": True, "payload": {"ok": True}},
        }

        route_res = await proc.request("route.handle", {"route": "status", "method": "GET"})
        assert route_res == {"status": 200, "body": {"ok": True, "route": "status"}}

        ui_res = await proc.request("ui.render", {"surface": "widget", "params": {}})
        validated = ui_doc.validate(ui_res["document"], routes=manifest.routes, tools=("ts_echo",))
        assert validated["schema"] == 1

        await proc.request("timer.tick", {"name": "heartbeat", "scheduled_for": 777})
        assert disp.storage(spec.ctx).get("timer_ts") == 777

        delivered = await proc.deliver_event("webhook.github", 1, {"hook": "github", "payload": {"pr": 9}})
        assert delivered is True
        if mode == "rpc":
            await asyncio.sleep(0.05)
        assert disp.storage(spec.ctx).get("hook_payload") == {"pr": 9}
    finally:
        await sup.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
async def test_ts_sdk_oneshot_concurrent_host_calls_and_console_debug_redirect(tmp_path: Path) -> None:
    if not _has_runtime(sandbox._find_node):
        pytest.skip("node runtime not installed")

    code_dir = tmp_path / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "carnivore.toml").write_text(
        "\n".join([
            "schema = 2",
            'id = "tsoneshotadv"',
            'name = "TS Oneshot Adv"',
            'version = "1.0.0"',
            'kind = "plugin"',
            'description = "Concurrent oneshot & console.debug regression fixture"',
            'author = "Tester"',
            "",
            "[run]",
            'cmd = ["node", "main.mjs"]',
            'mode = "oneshot"',
            "",
            "[[mcp.tools]]",
            'name = "ts_multi"',
            'description = "Calls storage concurrently and logs console.debug/table/dir"',
            'gate = "read"',
            'inputSchema = { type = "object", properties = {} }',
            "",
        ]),
        encoding="utf-8",
    )
    (code_dir / "main.mjs").write_text(
        """import { Plugin } from "@carnivore/plugin-sdk";

const plugin = new Plugin().tool("ts_multi", "Concurrent host + console.debug", async () => {
  console.debug("CONSOLE_DEBUG_ON_STDOUT");
  console.dir({ dir: true });
  console.table([{ k: 1 }]);
  await plugin.host.storage.put("oneshot_k", 42);
  const [got, listed] = await Promise.all([
    plugin.host.storage.get("oneshot_k"),
    plugin.host.storage.list(""),
  ]);
  return { got: got.value, keys: listed.keys };
});

await plugin.serve();
""",
        encoding="utf-8",
    )

    state_dir = tmp_path / "state"
    data_dir = state_dir / "cplugs" / "inst-ts-adv"
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    manifest = load_sidecar_manifest(code_dir, "tsoneshotadv", allow_local=True)
    defn = sidecar_registry.SidecarDefinition(
        manifest=manifest,
        item_id="local/tsoneshotadv",
        install_key="inst-ts-adv",
        code_root=code_dir,
        folder=data_dir,
    )
    spec = sidecar_spec.build_spec(defn, frozenset(manifest.permissions), {}, consented=True, consent_owed=False)
    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"t" * 32))
    sup = Supervisor(
        state_dir,
        "1.0.0",
        disp,
        lambda _pid, _k, _r: None,
        lambda _pid: {},
        lambda _r: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )
    try:
        st = await sup.enable(spec)
        assert st == "running"
        proc = sup.process("tsoneshotadv")
        assert proc is not None
        res = await proc.request("tools/call", {"name": "ts_multi", "arguments": {}}, timeout=5.0)
        parsed = json.loads(res["content"][0]["text"])
        assert parsed == {"got": 42, "keys": ["oneshot_k"]}
    finally:
        await sup.shutdown()
