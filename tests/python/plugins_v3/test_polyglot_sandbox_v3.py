
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.mcp import pending
from src.plugins.host import install_gates, sidecar_services
from src.plugins.host.install_gates import CplugGateRefusal
from src.plugins.host.runtime import Host
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_spec import build_spec
from src.plugins.runtime import sandbox, socket_server
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


def test_resolve_runtime_and_linux_bwrap_landlock_builders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not DARWIN_SANDBOX:
        monkeypatch.setattr(sandbox, "find_interpreter", lambda: Path(sys.executable))

    code = tmp_path / "plug"
    code.mkdir()
    venv_sp = code / ".venv" / "lib" / "python3.12" / "site-packages"
    venv_sp.mkdir(parents=True)
    bin_file = code / "mybin"
    bin_file.write_bytes(b"\xcf\xfa\xed\xfe\x00\x00\x00\x00")
    bin_file.chmod(0o755)

    uv_rt = sandbox.resolve_runtime(["uv", "run", "--frozen", "main.py", "--flag"], code)
    assert uv_rt.kind == "uv"
    assert uv_rt.args == ("main.py", "--flag")
    assert venv_sp in uv_rt.pythonpath_extra
    assert (code / ".venv").resolve() in uv_rt.read_roots

    bash_rt = sandbox.resolve_runtime(["bash", "main.sh"], code)
    assert bash_rt.kind == "bash"
    assert bash_rt.allow_fork is True
    assert bash_rt.args == ("main.sh",)

    bin_rt = sandbox.resolve_runtime(["./mybin", "--serve"], code)
    assert bin_rt.kind == "binary"
    assert bin_rt.primary_exec == bin_file.resolve()
    assert bin_rt.args == ("--serve",)

    layout = sandbox.Layout(
        interpreter=Path("/usr/bin/python3"),
        stdlib_root=Path("/usr/lib/python3.12"),
        runtime_dir=tmp_path / "rt",
        code_dir=code,
        data_dir=tmp_path / "data",
        socket_path=tmp_path / "run" / "p.sock",
        carnivore_bin=tmp_path / "bin" / "carnivore",
        plugin_id="demo",
        run_mode="oneshot",
    )
    (layout.runtime_dir).mkdir()
    (layout.data_dir / "files").mkdir(parents=True)
    (layout.carnivore_bin.parent).mkdir(parents=True)
    layout.carnivore_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    (layout.socket_path.parent).mkdir(parents=True)
    layout.socket_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    bwrap_cmd = sandbox.build_linux_command(layout, ["/usr/bin/python3", "main.py"])
    assert "--unshare-net" in bwrap_cmd
    assert "--unshare-pid" in bwrap_cmd
    assert "--die-with-parent" in bwrap_cmd
    assert str(layout.files_dir) in bwrap_cmd
    assert bwrap_cmd[-3:] == ["--", "/usr/bin/python3", "main.py"]

    ll = sandbox.landlock_ruleset(layout)
    assert str(code) in ll["ro"]
    assert str(layout.carnivore_bin) in ll["ro"]
    assert str(layout.files_dir) in ll["rw"]
    assert os.path.realpath(layout.socket_path) in ll["rw"]


def test_install_gates_v2_polyglot_suffixes_and_declared_binary(tmp_path: Path) -> None:
    v2_sh = tmp_path / "v2_sh"
    v2_sh.mkdir()
    (v2_sh / "main.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")
    (v2_sh / "carnivore.toml").write_text(
        'schema = 2\nid = "v2sh"\nname = "V2 Sh"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "d"\nauthor = "Tester"\n[run]\ncmd = ["bash", "main.sh"]\nmode = "oneshot"\n',
        encoding="utf-8",
    )
    install_gates.evaluate("acme/v2sh", v2_sh)

    v2_bin = tmp_path / "v2_bin"
    v2_bin.mkdir()
    (v2_bin / "plugbin").write_bytes(b"\xcf\xfa\xed\xfe\x07\x00\x00\x01")
    (v2_bin / "plugbin").chmod(0o755)
    (v2_bin / "carnivore.toml").write_text(
        'schema = 2\nid = "v2bin"\nname = "V2 Bin"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "d"\nauthor = "Tester"\n[run]\ncmd = ["./plugbin"]\nmode = "rpc"\n',
        encoding="utf-8",
    )
    install_gates.evaluate("acme/v2bin", v2_bin)

    (v2_bin / "sneaky_extra").write_bytes(b"\xcf\xfa\xed\xfe\x07\x00\x00\x01")
    with pytest.raises(CplugGateRefusal) as exc_extra:
        install_gates.evaluate("acme/v2bin", v2_bin)
    assert exc_extra.value.code == install_gates.NOT_SAFE

    v1_sh = tmp_path / "v1_sh"
    v1_sh.mkdir()
    (v1_sh / "main.py").write_text("print(1)\n", encoding="utf-8")
    (v1_sh / "bad.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (v1_sh / "carnivore.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "acme/v1sh",
                "name_key": "n",
                "description_key": "d",
                "version": "1.0.0",
                "icon": "list",
                "author": "Tester",
                "min_app_version": "1.0.0",
                "tier": "catalog",
                "default_enabled": False,
                "surfaces": {},
                "settings_schema": {"version": 1, "fields": {}},
                "permissions": {"app": []},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CplugGateRefusal) as exc_v1:
        install_gates.evaluate("acme/v1sh", v1_sh)
    assert exc_v1.value.code == install_gates.NOT_SAFE


def test_declared_binary_cannot_disguise_views_assets_or_scripts_across_all_gates(tmp_path: Path) -> None:
    from src.core.catalog import publish_prepare_kinds as kinds
    from src.plugins.cli import checker

    macho = b"\xcf\xfa\xed\xfe\x07\x00\x00\x01"

    def _make_plugin(name: str, cmd: list[str], rel_file: str, content: bytes, *, mode: int = 0o755, views_toml: str = "") -> Path:
        root = tmp_path / name
        root.mkdir(parents=True)
        target = root / rel_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)
        (root / "carnivore.toml").write_text(
            f'schema = 2\nid = "{name}"\nname = "{name}"\nversion = "1.0.0"\nkind = "plugin"\n'
            f'description = "d"\nauthor = "Tester"\n{views_toml}\n[run]\ncmd = {json.dumps(cmd)}\nmode = "rpc"\n',
            encoding="utf-8",
        )
        return root

    bad_cases = (
        ("evilview", ["./views/evil.html"], "views/evil.html", macho, ""),
        (
            "evildeclview",
            ["./views/panel/evil.html"],
            "views/panel/evil.html",
            macho,
            '[[ui.views]]\nname = "panel"\nsurfaces = ["panel"]\nfiles = ["evil.html"]\n',
        ),
        ("evilhtml", ["./payload.html"], "payload.html", macho, ""),
        ("evilsh", ["./main.sh"], "main.sh", macho, ""),
    )
    for pid, cmd, rel, data, views_toml in bad_cases:
        folder = _make_plugin(pid, cmd, rel, data, mode=0o755, views_toml=views_toml)
        with pytest.raises(CplugGateRefusal) as exc:
            install_gates.evaluate(f"acme/{pid}", folder)
        assert exc.value.code == install_gates.NOT_SAFE, pid
        assert kinds.prepare_kind("cplug", str(folder), "1.0.0", "acme").refusals, pid
        chk = checker.check_folder(folder)
        assert not chk.ok, pid

    ok_cases = (
        ("okbin", ["./plugbin"], "plugbin", macho, 0o755),
        ("okbash", ["bash", "main.sh"], "main.sh", b"#!/bin/bash\necho ok\n", 0o644),
        ("okexecsh", ["./main.sh"], "main.sh", b"#!/bin/bash\necho ok\n", 0o755),
    )
    for pid, cmd, rel, data, mode in ok_cases:
        folder = _make_plugin(pid, cmd, rel, data, mode=mode)
        install_gates.evaluate(f"acme/{pid}", folder)
        prepared = kinds.prepare_kind("cplug", str(folder), "1.0.0", "acme")
        assert prepared.refusals == [], (pid, prepared.refusals)
        chk = checker.check_folder(folder)
        assert chk.ok, (pid, chk.errors)


async def _run_plugin_tool(tmp_path: Path, plugin_id: str, code: Path, granted: set[str], tool_args: dict) -> Any:
    sm = load_sidecar_manifest(code, plugin_id)
    d = SidecarDefinition(
        manifest=sm,
        item_id=f"local/{plugin_id}",
        install_key=plugin_id,
        code_root=code,
        folder=tmp_path / "data" / plugin_id,
    )
    spec = build_spec(
        d,
        frozenset(granted),
        {},
        consent_owed=False,
    )
    svc = HostServices(
        activity=lambda _row: None,
        list_sessions=lambda: asyncio.sleep(0, result=[{"id": "s-poly", "label": "poly", "host_key": "local"}]),
    )
    disp = HostDispatcher(svc, OwnerTokens(b"p" * 32))
    mgr = socket_server.PluginSocketManager()
    sup = Supervisor(
        tmp_path / "state",
        "9.9.9",
        disp,
        lambda _pid, _k, _why: None,
        lambda _pid: {"inbox": 0, "timers": 0, "routes": 0},
        lambda _row: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
        sockets=mgr,
    )
    try:
        await sup.enable(spec)
        proc = await sup.ensure(plugin_id)
        assert proc is not None
        reply = await proc.request("tools/call", {"name": "echo", "arguments": tool_args, "caller": {"kind": "owner"}})
        if isinstance(reply, dict) and isinstance(reply.get("content"), list) and reply["content"]:
            text = reply["content"][0].get("text", "")
            try:
                return json.loads(text)
            except ValueError:
                return text
        return reply
    finally:
        await sup.shutdown()
        await mgr.stop_all()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize("mode", ["rpc", "oneshot"])
async def test_real_sandbox_exec_python_and_uv_modes(tmp_path: Path, mode: str) -> None:
    code = tmp_path / "code" / f"uv_{mode}"
    code.mkdir(parents=True)
    if mode == "rpc":
        (code / "main.py").write_text(
            """
from cplug_sdk import Plugin
plugin = Plugin()
@plugin.tool("echo", "Echo", {"type": "object"}, gate="read")
async def echo(args, caller):
    return {"mode": "rpc", "msg": args.get("msg")}
""",
            encoding="utf-8",
        )
    else:
        (code / "main.py").write_text(
            """
import json, sys
req = json.loads(sys.stdin.read())
print(json.dumps({"mode": "oneshot", "msg": req["params"]["arguments"]["msg"]}))
""",
            encoding="utf-8",
        )
    (code / "carnivore.toml").write_text(
        f"""
schema = 2
id = "uv{mode}"
name = "UV {mode}"
version = "1.0.0"
kind = "plugin"
description = "uv translated"
author = "Tester"

[run]
cmd = ["uv", "run", "main.py"]
mode = "{mode}"

[mcp]
[[mcp.tools]]
name = "echo"
description = "Echo"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )
    res = await _run_plugin_tool(tmp_path, f"uv{mode}", code, set(), {"msg": "hi-uv"})
    assert res == {"mode": mode, "msg": "hi-uv"}


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
@pytest.mark.parametrize("mode", ["rpc", "oneshot"])
async def test_real_sandbox_exec_bash_rpc_and_oneshot_with_carnivore_bin(tmp_path: Path, mode: str) -> None:
    code = tmp_path / "code" / f"bash_{mode}"
    code.mkdir(parents=True)
    if mode == "rpc":
        (code / "main.sh").write_text(
            """#!/bin/bash
while IFS= read -r line; do
  id="${line##*\\"id\\":}"
  id="${id%%,*}"
  id="${id%%\\}*}"
  id="${id//[!0-9]/}"
  if [[ "$line" == *'"initialize"'* ]]; then
    printf '{"jsonrpc":"2.0","id":%s,"result":{"api_version":1,"capabilities":{"tools":true},"subscriptions":[]}}\\n' "$id"
  elif [[ "$line" == *'"tools/list"'* ]]; then
    printf '{"jsonrpc":"2.0","id":%s,"result":{"tools":[{"name":"echo","description":"Echo","gate":"read","inputSchema":{"type":"object"}}]}}\\n' "$id"
  elif [[ "$line" == *'"tools/call"'* ]]; then
    sess=$("$CARNIVORE_BIN" sessions list)
    printf '{"jsonrpc":"2.0","id":%s,"result":{"shell":"bash","sessions":%s}}\\n' "$id" "$sess"
  elif [[ "$line" == *'"shutdown"'* ]]; then
    printf '{"jsonrpc":"2.0","id":%s,"result":{"ok":true}}\\n' "$id"
    exit 0
  fi
done
""",
            encoding="utf-8",
        )
    else:
        (code / "main.sh").write_text(
            """#!/bin/bash
IFS= read -r _req || true
sess=$("$CARNIVORE_BIN" sessions list)
printf '{"shell":"bash-oneshot","sessions":%s}\\n' "$sess"
""",
            encoding="utf-8",
        )
    (code / "main.sh").chmod(0o755)
    (code / "carnivore.toml").write_text(
        f"""
schema = 2
id = "bash{mode}"
name = "Bash {mode}"
version = "1.0.0"
kind = "plugin"
description = "Bash polyglot"
author = "Tester"

[run]
cmd = ["bash", "main.sh"]
mode = "{mode}"

[permissions]
read = ["sessions"]

[mcp]
[[mcp.tools]]
name = "echo"
description = "Echo"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )
    res = await _run_plugin_tool(tmp_path, f"bash{mode}", code, {"sessions.read"}, {"msg": "ok"})
    assert res["sessions"] == {"sessions": [{"id": "s-poly", "label": "poly"}]}


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX or not _has_runtime(sandbox._find_node), reason="needs macOS sandbox-exec + node")
@pytest.mark.parametrize("mode", ["rpc", "oneshot"])
async def test_real_sandbox_exec_node_rpc_and_oneshot(tmp_path: Path, mode: str) -> None:
    code = tmp_path / "code" / f"node_{mode}"
    code.mkdir(parents=True)
    if mode == "rpc":
        (code / "main.js").write_text(
            """
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  if (!line.trim()) return;
  const msg = JSON.parse(line);
  if (msg.method === "initialize") {
    process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { api_version: 1, capabilities: { tools: true }, subscriptions: [] } }) + "\\n");
  } else if (msg.method === "tools/list") {
    process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { tools: [{ name: "echo", description: "Echo", gate: "read", inputSchema: { type: "object" } }] } }) + "\\n");
  } else if (msg.method === "tools/call") {
    process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { runtime: "node", msg: msg.params.arguments.msg } }) + "\\n");
  } else if (msg.method === "shutdown") {
    process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { ok: true } }) + "\\n");
    process.exit(0);
  }
});
""",
            encoding="utf-8",
        )
    else:
        (code / "main.js").write_text(
            """
const fs = require("fs");
const req = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({ runtime: "node-oneshot", msg: req.params.arguments.msg }) + "\\n");
""",
            encoding="utf-8",
        )
    (code / "carnivore.toml").write_text(
        f"""
schema = 2
id = "node{mode}"
name = "Node {mode}"
version = "1.0.0"
kind = "plugin"
description = "Node polyglot"
author = "Tester"

[run]
cmd = ["node", "main.js"]
mode = "{mode}"

[mcp]
[[mcp.tools]]
name = "echo"
description = "Echo"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )
    res = await _run_plugin_tool(tmp_path, f"node{mode}", code, set(), {"msg": "hi-node"})
    assert res == {"runtime": "node" if mode == "rpc" else "node-oneshot", "msg": "hi-node"}


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX or not _has_runtime(sandbox._find_bun), reason="needs macOS sandbox-exec + bun")
@pytest.mark.parametrize("mode", ["rpc", "oneshot"])
async def test_real_sandbox_exec_bun_rpc_and_oneshot(tmp_path: Path, mode: str) -> None:
    code = tmp_path / "code" / f"bun_{mode}"
    code.mkdir(parents=True)
    if mode == "rpc":
        (code / "main.ts").write_text(
            """
const decoder = new TextDecoder();
let buf = "";
for await (const chunk of Bun.stdin.stream()) {
  buf += decoder.decode(chunk);
  let idx;
  while ((idx = buf.indexOf("\\n")) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    const msg = JSON.parse(line);
    if (msg.method === "initialize") {
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { api_version: 1, capabilities: { tools: true }, subscriptions: [] } }));
    } else if (msg.method === "tools/list") {
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { tools: [{ name: "echo", description: "Echo", gate: "read", inputSchema: { type: "object" } }] } }));
    } else if (msg.method === "tools/call") {
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { runtime: "bun", msg: msg.params.arguments.msg } }));
    } else if (msg.method === "shutdown") {
      console.log(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { ok: true } }));
      process.exit(0);
    }
  }
}
""",
            encoding="utf-8",
        )
    else:
        (code / "main.ts").write_text(
            """
const text = await new Response(Bun.stdin.stream()).text();
const req = JSON.parse(text);
console.log(JSON.stringify({ runtime: "bun-oneshot", msg: req.params.arguments.msg }));
""",
            encoding="utf-8",
        )
    (code / "carnivore.toml").write_text(
        f"""
schema = 2
id = "bun{mode}"
name = "Bun {mode}"
version = "1.0.0"
kind = "plugin"
description = "Bun polyglot"
author = "Tester"

[run]
cmd = ["bun", "run", "main.ts"]
mode = "{mode}"

[mcp]
[[mcp.tools]]
name = "echo"
description = "Echo"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )
    res = await _run_plugin_tool(tmp_path, f"bun{mode}", code, set(), {"msg": "hi-bun"})
    assert res == {"runtime": "bun" if mode == "rpc" else "bun-oneshot", "msg": "hi-bun"}


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX or shutil.which("cc") is None, reason="needs macOS sandbox-exec + cc")
@pytest.mark.parametrize("mode", ["rpc", "oneshot"])
async def test_real_sandbox_exec_compiled_native_binary_rpc_and_oneshot(tmp_path: Path, mode: str) -> None:
    code = tmp_path / "code" / f"bin_{mode}"
    code.mkdir(parents=True)
    src_c = tmp_path / f"plug_{mode}.c"
    if mode == "rpc":
        src_c.write_text(
            r"""
#include <stdio.h>
#include <string.h>
int main(void) {
    char line[4096];
    while (fgets(line, sizeof(line), stdin)) {
        if (strstr(line, "\"initialize\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"api_version\":1,\"capabilities\":{\"tools\":true},\"subscriptions\":[]}}\n");
            fflush(stdout);
        } else if (strstr(line, "\"tools/list\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":{\"tools\":[{\"name\":\"echo\",\"description\":\"Echo\",\"gate\":\"read\",\"inputSchema\":{\"type\":\"object\"}}]}}\n");
            fflush(stdout);
        } else if (strstr(line, "\"tools/call\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":3,\"result\":{\"runtime\":\"binary-rpc\"}}\n");
            fflush(stdout);
        } else if (strstr(line, "\"shutdown\"")) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":4,\"result\":{\"ok\":true}}\n");
            fflush(stdout);
            break;
        }
    }
    return 0;
}
""",
            encoding="utf-8",
        )
    else:
        src_c.write_text(
            r"""
#include <stdio.h>
int main(void) {
    int c;
    while ((c = getchar()) != EOF) {}
    printf("{\"runtime\":\"binary-oneshot\"}\n");
    return 0;
}
""",
            encoding="utf-8",
        )
    bin_path = code / "plugbin"
    subprocess.run([shutil.which("cc"), "-O2", str(src_c), "-o", str(bin_path)], check=True)
    (code / "carnivore.toml").write_text(
        f"""
schema = 2
id = "bin{mode}"
name = "Bin {mode}"
version = "1.0.0"
kind = "plugin"
description = "Compiled binary polyglot"
author = "Tester"

[run]
cmd = ["./plugbin"]
mode = "{mode}"

[mcp]
[[mcp.tools]]
name = "echo"
description = "Echo"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )
    res = await _run_plugin_tool(tmp_path, f"bin{mode}", code, set(), {"msg": "ignored"})
    assert res == {"runtime": f"binary-{mode}"}


@pytest.mark.asyncio
async def test_stop_via_inbox_succeeds_for_oneshot_after_child_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not DARWIN_SANDBOX:
        monkeypatch.setattr(sandbox, "find_interpreter", lambda: Path(sys.executable))

    code = tmp_path / "code" / "oneshotstop"
    code.mkdir(parents=True)
    (code / "main.py").write_text("print('{\"ok\":true}')\n", encoding="utf-8")
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "oneshotstop"
name = "Oneshot Stop"
version = "1.0.0"
kind = "plugin"
description = "Stops via inbox in oneshot mode"
author = "Tester"

[run]
cmd = ["python3", "main.py"]
mode = "oneshot"

[permissions]
write = ["sessions.control"]
""",
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(code, "oneshotstop")
    d = SidecarDefinition(
        manifest=sm,
        item_id="local/oneshotstop",
        install_key="oneshotstop",
        code_root=code,
        folder=tmp_path / "data" / "oneshotstop",
    )
    spec = build_spec(
        d,
        frozenset({"sessions.control"}),
        {},
        consent_owed=False,
    )
    from dataclasses import replace
    from src.plugins.host import state as owner_state

    owner_state.update(
        tmp_path / "state",
        sm,
        None,
        lambda st: replace(st, enabled=True, digest=sm.code_digest, grants=("sessions.control",)),
    )
    host = Host(tmp_path / "state")
    monkeypatch.setattr("src.plugins.host.runtime.find", lambda cid: d if cid == "oneshotstop" else None)
    disp = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"s" * 32))
    sup = Supervisor(
        tmp_path / "state",
        "9.9.9",
        disp,
        lambda _pid, _k, _why: None,
        lambda _pid: {"inbox": 0, "timers": 0, "routes": 0},
        lambda _row: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )

    destroyed: List[str] = []

    class _FakeSM:
        async def destroy_session(self, session_id: str) -> None:
            destroyed.append(session_id)

    app_state = SimpleNamespace(
        session_manager=_FakeSM(),
        services=SimpleNamespace(registry=SimpleNamespace(get_backend=lambda _sid: None)),
    )
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "get_store", lambda: store)
    monkeypatch.setattr("src.core.session_ops.close_record.stop_and_record", lambda fn, **_kw: fn())

    await sup.activate(spec)
    assert sup.process("oneshotstop") is None
    assert sup.available("oneshotstop") is True

    info = SimpleNamespace(session=SimpleNamespace(id="sess-99"), tmux_session="tmux-99")
    monkeypatch.setattr("src.plugins.host.capabilities.local_infos_from_app", lambda _st: (lambda: asyncio.sleep(0, result=[info])))
    app = SimpleNamespace(state=app_state)
    svc = sidecar_services.build_services(
        host=host,
        app=app,
        state_dir=lambda: tmp_path / "state",
        supervisor_getter=lambda: sup,
    )
    task = asyncio.create_task(svc["control_session"]("oneshotstop", "sess-99", "stop"))
    for _ in range(40):
        items = store.list()
        if items:
            await store.approve(items[0]["id"])
            break
        await asyncio.sleep(0.02)
    res = await task
    assert res == {"ok": True}
    assert destroyed == ["sess-99"]
    await sup.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
async def test_real_sandbox_exec_uv_rpc_imports_venv_site_packages_preserving_isolated_mode(tmp_path: Path) -> None:
    code = tmp_path / "code" / "uv_venv_rpc"
    code.mkdir(parents=True)
    venv_sp = code / ".venv" / "lib" / "python3.12" / "site-packages"
    venv_sp.mkdir(parents=True)
    (venv_sp / "my_venv_dep.py").write_text("VALUE = 'from_uv_venv'\n", encoding="utf-8")
    (code / "main.py").write_text(
        """
import os
import sys
import my_venv_dep
from cplug_sdk import Plugin

plugin = Plugin()

@plugin.tool("echo", "Echo", {"type": "object"}, gate="read")
async def echo(args, caller):
    return {
        "dep": my_venv_dep.VALUE,
        "isolated": bool(sys.flags.isolated),
        "env_leaked": "CARNIVORE_EXTRA_SITE" in os.environ,
    }
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "uvvenvrpc"
name = "UV Venv RPC"
version = "1.0.0"
kind = "plugin"
description = "uv rpc .venv import"
author = "Tester"

[run]
cmd = ["uv", "run", "main.py"]
mode = "rpc"

[mcp]
[[mcp.tools]]
name = "echo"
description = "Echo"
gate = "read"
inputSchema = { type = "object" }
""",
        encoding="utf-8",
    )
    res = await _run_plugin_tool(tmp_path, "uvvenvrpc", code, set(), {})
    assert res == {"dep": "from_uv_venv", "isolated": True, "env_leaked": False}


def test_resolve_runtime_rejects_escaping_venv_symlink_and_linux_build_command_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not DARWIN_SANDBOX:
        monkeypatch.setattr(sandbox, "find_interpreter", lambda: Path(sys.executable))

    outside_sp = tmp_path / "outside_sp"
    outside_sp.mkdir()
    code = tmp_path / "escape_plug"
    (code / ".venv" / "lib" / "python3.12").mkdir(parents=True)
    (code / ".venv" / "lib" / "python3.12" / "site-packages").symlink_to(outside_sp)

    rt = sandbox.resolve_runtime(["uv", "run", "main.py"], code)
    assert rt.pythonpath_extra == ()

    interp = tmp_path / "custom_py" / "bin" / "python3"
    interp.parent.mkdir(parents=True)
    interp.write_text("#!/bin/sh\n", encoding="utf-8")
    extra_bin = tmp_path / "tools" / "helper"
    extra_bin.parent.mkdir(parents=True)
    extra_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    rt_dir = tmp_path / "rt"
    rt_dir.mkdir()
    data_dir = tmp_path / "data"
    (data_dir / "files").mkdir(parents=True)
    cbin = tmp_path / "bin" / "carnivore"
    cbin.parent.mkdir(parents=True)
    cbin.write_text("#!/bin/sh\n", encoding="utf-8")
    sock = tmp_path / "run" / "p.sock"
    sock.parent.mkdir(parents=True)
    sock.write_text("", encoding="utf-8")

    layout = sandbox.Layout(
        interpreter=interp,
        stdlib_root=tmp_path / "stdlib",
        runtime_dir=rt_dir,
        code_dir=code,
        data_dir=data_dir,
        runtime_kind="node",
        exec_paths=(extra_bin,),
        socket_path=sock,
        carnivore_bin=cbin,
        plugin_id="linuxplug",
        run_mode="rpc",
    )
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
    monkeypatch.setattr(sandbox, "_python_runtime", lambda: (interp, tmp_path / "stdlib"))

    ll = sandbox.landlock_ruleset(layout)
    assert str(interp) in ll["ro"]
    assert str(extra_bin) in ll["ro"]

    linux_cmd = sandbox.build_command(layout, tmp_path / "unused.sb", "main", 1024)
    assert linux_cmd[0] == "/usr/bin/bwrap"
    assert "--ro-bind" in linux_cmd and str(interp) in linux_cmd
    assert str(extra_bin) in linux_cmd
    assert str(rt_dir / "runner.py") in linux_cmd

    unrestricted = sandbox.build_unrestricted_command(layout, "main", 1024)
    assert unrestricted[0] == str(interp)
    assert str(rt_dir / "runner.py") in unrestricted
