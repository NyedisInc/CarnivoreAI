
from __future__ import annotations

import asyncio
import shutil
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.plugins.host import owner_switch, sidecar_boot, sidecar_registry, state as owner_state
from src.plugins.host.runtime import Host
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import sandbox, sock_cli
from src.plugins.runtime.dispatch import PluginContext
from src.plugins.sdk_py.plugin import HostError, Plugin, _bus_token
from src.plugins.sdk_py.testing import FakeHost, attach

DARWIN_SANDBOX = sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def _has_node() -> bool:
    try:
        sandbox._find_node()
        return True
    except sandbox.SandboxUnavailable:
        return False


def _write_plugin(folder: Path, toml_body: str, main_name: str, code_body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "carnivore.toml").write_text(toml_body, encoding="utf-8")
    (folder / main_name).write_text(textwrap.dedent(code_body), encoding="utf-8")


def _register_and_enable(
    state_dir: Path,
    code_dir: Path,
    plugin_id: str,
    install_key: str,
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
    owner_state.update(
        state_dir,
        manifest,
        None,
        lambda st: replace(st, enabled=True, grants=tuple(manifest.permissions), digest=manifest.code_digest),
    )
    return defn


def _install_registry(monkeypatch: pytest.MonkeyPatch, defs: List[SidecarDefinition]) -> None:
    by_id = {d.id: d for d in defs}
    fake_reg = SimpleNamespace(listed=lambda: list(defs), find=lambda pid: by_id.get(pid))
    monkeypatch.setattr(sidecar_registry, "current", lambda: fake_reg)
    monkeypatch.setattr(sidecar_registry, "find", lambda pid: by_id.get(pid))


@pytest.mark.asyncio
async def test_sdk_py_decorators_fake_host_and_method_not_found() -> None:
    p = Plugin()
    seen_events: List[tuple[Any, Any]] = []

    @p.on("acme:ready")
    async def on_ready(seq: Any, payload: Any) -> None:
        seen_events.append((seq, payload))

    @p.service("math.v1", "add")
    async def add_fn(args: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
        return {"sum": int(args["a"]) + int(args["b"]), "meta": meta}

    @p.service("math.v1")
    def sync_echo(args: Dict[str, Any], _meta: Dict[str, Any]) -> Dict[str, Any]:
        return {"echo": args.get("msg")}

    @p.channel("ops")
    async def send_ops(event: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "title": event.get("title"), "room": config.get("room")}

    init = await p.handle("initialize", {"settings": {}, "granted": []})
    assert init["capabilities"]["services"] is True
    assert init["capabilities"]["events"] is True
    assert init["subscriptions"] == ["acme:ready"]

    await p.handle("event.deliver", {"family": "acme:ready", "seq": 3, "payload": {"ok": True}})
    assert seen_events == [(3, {"ok": True})]

    assert await p.handle("service.call", {"service": "math.v1", "method": "add", "args": {"a": 2, "b": 5}}) == {
        "sum": 7,
        "meta": {"service": "math.v1", "method": "add"},
    }
    assert await p.handle("service.call", {"service": "math.v1", "method": "sync_echo", "args": {"msg": "hi"}}) == {
        "echo": "hi"
    }
    assert await p.handle("channel.send", {"channel": "ops", "event": {"title": "Deploy"}, "config": {"room": "eng"}}) == {
        "ok": True,
        "title": "Deploy",
        "room": "eng",
    }

    with pytest.raises(KeyError):
        await p.handle("service.call", {"service": "math.v1", "method": "missing", "args": {}})
    with pytest.raises(KeyError):
        await p.handle("channel.send", {"channel": "missing", "event": {}, "config": {}})

    written: List[Dict[str, Any]] = []
    p._write = written.append
    tasks: set = set()
    p._dispatch_frame(
        {"jsonrpc": "2.0", "id": 19, "method": "service.call", "params": {"service": "math.v1", "method": "nope"}},
        tasks,
    )
    p._dispatch_frame(
        {"jsonrpc": "2.0", "id": 20, "method": "channel.send", "params": {"channel": "nope", "event": {}, "config": {}}},
        tasks,
    )
    await asyncio.gather(*tasks)
    assert written == [
        {"jsonrpc": "2.0", "id": 19, "error": {"code": -32601, "message": "method_not_found"}},
        {"jsonrpc": "2.0", "id": 20, "error": {"code": -32601, "message": "method_not_found"}},
    ]

    async def async_emit(params: Dict[str, Any]) -> Dict[str, Any]:
        return {"delivered": 1, "event": params["event"]}

    fake = FakeHost(
        {
            "service.call": lambda params: {"got": f"{params['service']}.{params['method']}", "n": params["args"]["n"]},
            "events.emit": async_emit,
        }
    )
    attach(p, fake)
    assert await p.host.service.call("kv.v1", "get", {"n": 9}) == {"got": "kv.v1.get", "n": 9}
    assert await p.host.events.emit("acme:done", {"ok": True}) == {"delivered": 1, "event": "acme:done"}
    assert [c[0] for c in fake.calls] == ["service.call", "events.emit"]

    err_fake = FakeHost({"service.call": HostError(-32002, "not_granted", {"permission": "services:kv.v1"})})
    attach(p, err_fake)
    with pytest.raises(HostError) as exc_info:
        await p.host.service.call("kv.v1", "get", {})
    assert exc_info.value.reason == "not_granted"


def test_sock_cli_forwards_carnivore_bus_token_and_equals_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARNIVORE_BUS_TOKEN", "bus-tok-xyz")
    method, params = sock_cli._build_request(["service", "call", "kv.v1", "get", '--args={"k":"v"}'])
    assert method == "service.call"
    assert params == {"service": "kv.v1", "method": "get", "args": {"k": "v"}, "_bus_token": "bus-tok-xyz"}

    monkeypatch.delenv("CARNIVORE_BUS_TOKEN", raising=False)
    method2, params2 = sock_cli._build_request(["service", "call", "kv.v1", "get", '{"k":"v2"}'])
    assert method2 == "service.call"
    assert params2 == {"service": "kv.v1", "method": "get", "args": {"k": "v2"}}
    assert "_bus_token" not in params2


@pytest.mark.asyncio
async def test_sdk_py_carnivore_bus_token_env_fallback_and_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    p = Plugin()
    sent_frames: List[Dict[str, Any]] = []

    def _write(frame: Dict[str, Any]) -> None:
        sent_frames.append(frame)
        rid = frame["id"]
        fut = p._pending.get(rid)
        if fut is not None and not fut.done():
            fut.set_result({"echo": frame["params"]})

    p._write = _write

    monkeypatch.setenv("CARNIVORE_BUS_TOKEN", "   ")
    res_blank = await p.host.service.call("kv.v1", "get", {"k": 1})
    assert "_bus_token" not in res_blank["echo"]

    monkeypatch.setenv("CARNIVORE_BUS_TOKEN", "  env-tok-py  ")
    res_env = await p.host.service.call("kv.v1", "get", {"k": 2})
    assert res_env["echo"]["_bus_token"] == "env-tok-py"

    tok = _bus_token.set("ctx-tok-py")
    try:
        res_ctx = await p.host.service.call("kv.v1", "get", {"k": 3})
        assert res_ctx["echo"]["_bus_token"] == "ctx-tok-py"

        res_explicit = await p._call("service.call", {"service": "kv.v1", "method": "get", "args": {}, "_bus_token": "explicit-tok"})
        assert res_explicit["echo"]["_bus_token"] == "explicit-tok"
    finally:
        _bus_token.reset(tok)


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
async def test_sdk_py_decorators_bus_depth_and_missing_method_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    dir_a = tmp_path / "code_a"
    dir_b = tmp_path / "code_b"

    _write_plugin(
        dir_a,
        """schema = 2
id = "pya"
name = "Py A"
version = "1.0.0"
kind = "plugin"
description = "Python SDK service caller"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
services = ["pya.api", "pyb.api"]
events = ["pya:ping"]

[services]
consumes = ["pya.api", "pyb.api"]

[[services.provides]]
name = "pya.api"
methods = ["hop", "emit_and_call"]

[events]
emit = ["pya:ping"]
""",
        "main.py",
        """
        from cplug_sdk import HostError, Plugin

        plugin = Plugin()

        @plugin.service("pya.api", "hop")
        async def hop(args, _meta):
            depth = int(args.get("depth", 1))
            if depth >= 5:
                return {"done": depth}
            try:
                return await plugin.host.service.call("pyb.api", "hop", {"depth": depth + 1})
            except HostError as exc:
                return {"bus_err": exc.reason, "depth": depth, "data": exc.data}

        @plugin.service("pya.api", "emit_and_call")
        async def emit_and_call(args, _meta):
            ev = await plugin.host.events.emit("pya:ping", {"msg": args.get("msg", "ok")})
            try:
                await plugin.host.service.call("pyb.api", "does_not_exist", {})
                missing_err = None
            except HostError as exc:
                missing_err = exc.data.get("reason") or exc.reason
            return {"ev": ev, "missing_err": missing_err}
        """,
    )

    _write_plugin(
        dir_b,
        """schema = 2
id = "pyb"
name = "Py B"
version = "1.0.0"
kind = "plugin"
description = "Python SDK service provider"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
services = ["pya.api"]
events = ["pya:ping"]

[services]
consumes = ["pya.api"]

[[services.provides]]
name = "pyb.api"
methods = ["hop", "does_not_exist"]

[events]
on = ["pya:ping"]
""",
        "main.py",
        """
        from cplug_sdk import Plugin

        plugin = Plugin()
        seen = []

        @plugin.on("pya:ping")
        async def on_ping(seq, payload):
            seen.append({"seq": seq, "payload": payload})

        @plugin.service("pyb.api", "hop")
        async def hop(args, _meta):
            depth = int(args.get("depth", 1))
            return await plugin.host.service.call("pya.api", "hop", {"depth": depth + 1})

        @plugin.route("seen")
        async def get_seen(_req):
            return {"status": 200, "body": {"seen": seen}}
        """,
    )

    def_a = _register_and_enable(state_dir, dir_a, "pya", "inst-pya")
    def_b = _register_and_enable(state_dir, dir_b, "pyb", "inst-pyb")
    _install_registry(monkeypatch, [def_a, def_b])

    owner_switch.write(state_dir, True)
    host = Host(state_dir, publish=lambda _t: None)
    rt = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    rt.supervisor.override_index("pya", True)
    rt.supervisor.override_index("pyb", True)
    await rt.start()
    try:
        ctx_a = PluginContext(
            plugin_id="pya",
            install_key="inst-pya",
            data_dir=def_a.folder,
            granted=frozenset(def_a.manifest.permissions),
            services_consumes=tuple(def_a.manifest.services_consumes),
            events_emit=tuple(def_a.manifest.events_emit),
        )
        res = await rt.plugin_bus.call_service(ctx_a, "pya.api", "emit_and_call", {"msg": "hello"})
        assert res["ev"]["delivered"] == 1
        assert res["missing_err"] == "provider_method_missing"

        proc_b = await rt.supervisor.ensure("pyb")
        assert proc_b is not None
        seen_res = await proc_b.request("route.handle", {"route": "seen", "method": "GET"})
        assert seen_res["body"]["seen"][0]["payload"] == {"event": "pya:ping", "source": "pya", "data": {"msg": "hello"}}

        hop_res = await rt.plugin_bus.call_service(ctx_a, "pyb.api", "hop", {"depth": 1})
        assert hop_res["bus_err"] == "rate_limited"
        assert hop_res["depth"] == 4
    finally:
        await rt.stop()


@pytest.mark.asyncio
@pytest.mark.skipif(not (DARWIN_SANDBOX and _has_node()), reason="needs macOS sandbox-exec and node")
async def test_sdk_ts_and_sock_cli_bus_token_depth_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    ts_dir = tmp_path / "code_ts"
    cli_dir = tmp_path / "code_cli"

    _write_plugin(
        ts_dir,
        """schema = 2
id = "tsbus"
name = "TS Bus"
version = "1.0.0"
kind = "plugin"
description = "TS SDK bus parity plugin"
author = "Tester"

[run]
cmd = ["node", "main.mjs"]
mode = "rpc"

[permissions]
services = ["tsbus.api", "clibus.api"]

[services]
consumes = ["tsbus.api", "clibus.api"]

[[services.provides]]
name = "tsbus.api"
methods = ["hop"]
""",
        "main.mjs",
        """
        import { Plugin } from "@carnivore/plugin-sdk";

        const plugin = new Plugin().service("tsbus.api", "hop", async (args) => {
          const depth = Number(args.depth ?? 1);
          if (depth >= 6) {
            return { depth };
          }
          return await plugin.host.service.call("clibus.api", "hop", { depth: depth + 1 });
        });

        await plugin.serve();
        """,
    )

    _write_plugin(
        cli_dir,
        """schema = 2
id = "clibus"
name = "CLI Bus"
version = "1.0.0"
kind = "plugin"
description = "Oneshot $CARNIVORE_BIN service call plugin"
author = "Tester"

[run]
cmd = ["python3", "run.py"]
mode = "oneshot"

[permissions]
services = ["tsbus.api"]

[services]
consumes = ["tsbus.api"]

[[services.provides]]
name = "clibus.api"
methods = ["hop"]
""",
        "run.py",
        """
        import json
        import os
        import subprocess
        import sys

        req = json.loads(sys.stdin.read())
        depth = int((req.get("params") or {}).get("args", {}).get("depth", 1))
        rid = req.get("id", 1)
        proc = subprocess.run(
            [
                os.environ["CARNIVORE_BIN"],
                "service",
                "call",
                "tsbus.api",
                "hop",
                f"--args={json.dumps({'depth': depth + 1})}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            err_text = (proc.stderr or proc.stdout).strip()
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"cli_err": err_text}}) + "\\n")
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": json.loads(proc.stdout)}) + "\\n")
        sys.stdout.flush()
        """,
    )

    def_ts = _register_and_enable(state_dir, ts_dir, "tsbus", "inst-tsbus")
    def_cli = _register_and_enable(state_dir, cli_dir, "clibus", "inst-clibus")
    _install_registry(monkeypatch, [def_ts, def_cli])

    owner_switch.write(state_dir, True)
    host = Host(state_dir, publish=lambda _t: None)
    rt = sidecar_boot.SidecarRuntime(host, SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop(), env_safe=lambda: False)
    rt.supervisor.set_safe_mode(False)
    rt.supervisor.override_index("tsbus", True)
    rt.supervisor.override_index("clibus", True)
    await rt.start()
    try:
        ctx_ts = PluginContext(
            plugin_id="tsbus",
            install_key="inst-tsbus",
            data_dir=def_ts.folder,
            granted=frozenset(def_ts.manifest.permissions),
            services_consumes=tuple(def_ts.manifest.services_consumes),
        )
        res = await rt.plugin_bus.call_service(ctx_ts, "tsbus.api", "hop", {"depth": 1})
        cli_err = str(res.get("cli_err") or "")
        assert "rate_limited" in cli_err
        assert '"depth":4' in cli_err or '"depth": 4' in cli_err
    finally:
        await rt.stop()
