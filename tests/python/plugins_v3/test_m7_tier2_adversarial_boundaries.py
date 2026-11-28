
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.plugins.cli import checker
from src.plugins.host import (
    egress_log,
    install_gates,
    sideload,
    sideload_copy,
    state as owner_state,
    ui_doc,
    ui_slots,
)
from src.plugins.host.fetch_transport import RawResponse, StdlibTransport
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.runtime import Host
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime import frames, sandbox, socket_server
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.sdk import cplug_validate, manifest_v2
from tests.helpers.plugins_v3_e2e_world import (
    DARWIN_SANDBOX,
    PluginsV3E2EWorld,
    build_plugins_v3_world,
    serve_http_probe,
)
from tests.helpers.plugins_v3_polyglot_fixtures import (
    DEFAULT_MIT_LICENSE,
    build_bash_plugin,
    build_python_plugin,
    has_node,
    write_plugin_files,
)
from tests.python.api_keys.conftest import key_store, owner_jwt  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATE_TS = REPO_ROOT / "web" / "src" / "lib" / "cplug-ui" / "validate.ts"
JITI_MJS = REPO_ROOT / "web" / "node_modules" / "jiti" / "lib" / "jiti.mjs"
SDK_TS_DIST = REPO_ROOT / "src" / "plugins" / "sdk_ts" / "dist" / "index.js"


def _minimal_v2_toml(plugin_id: str = "capplug", *, version: str = "1.0.0", tier: str = "catalog") -> str:
    return (
        f'schema = 2\nid = "{plugin_id}"\nname = "{plugin_id.title()}"\nversion = "{version}"\n'
        f'kind = "plugin"\ndescription = "Boundary test plugin"\nauthor = "Tester"\nlicense = "MIT"\n'
        f'tier = "{tier}"\ndefault_enabled = false\n[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n'
    )


def _enable_sideload_switch(w: PluginsV3E2EWorld) -> None:
    r = w.client.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers)
    assert r.status_code == 200 and r.json()["enabled"] is True, r.text


def _make_tier0_def(code_dir: Path, plugin_id: str) -> SidecarDefinition:
    doc = {
        "schema": 2,
        "id": plugin_id,
        "name": f"Plugin {plugin_id}",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Slot boundary fixture",
        "author": "Tester",
        "permissions": {"reasons": {"ui.slot:session.badges": "Render badges"}},
        "ui": {"slots": ["session.badges"], "contribute": {"session.badges": [{"id": "init", "badge": "ok"}]}},
    }
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    manifest = load_sidecar_manifest(code_dir, plugin_id)
    return SidecarDefinition(
        manifest=manifest,
        item_id=f"test/{plugin_id}",
        install_key=f"inst-{plugin_id}",
        code_root=code_dir,
        folder=code_dir.parent / "data" / plugin_id,
    )




def test_package_500_file_2mib_single_and_3mib_total_caps_across_validators(tmp_path: Path) -> None:
    pid = "capplug"
    toml_b = _minimal_v2_toml(pid).encode("utf-8")
    main_b = b"from cplug_sdk import Plugin\nplugin = Plugin()\n"
    lic_b = DEFAULT_MIT_LICENSE.encode("utf-8")

    members_500: Dict[str, bytes] = {"carnivore.toml": toml_b, "main.py": main_b, "LICENSE.md": lic_b}
    for i in range(497):
        members_500[f"assets/f_{i:03d}.txt"] = b"x\n"
    assert len(members_500) == 500

    cplug_validate.validate_cplug_members(pid, members_500, handle="acme", version="1.0.0")
    dir_500 = write_plugin_files(tmp_path / "dir_500", members_500)
    kept, errs = cplug_validate.validate_v2_folder_files(dir_500)
    assert len(kept) == 500 and errs == []
    assert len(install_gates.check_files(dir_500)) == 500
    assert checker.check_folder(dir_500).ok is True

    members_501 = {**members_500, "assets/f_497.txt": b"x\n"}
    with pytest.raises(cplug_validate.CplugValidationError) as exc_501:
        cplug_validate.validate_cplug_members(pid, members_501, handle="acme", version="1.0.0")
    assert exc_501.value.code == "cplug_invalid"

    dir_501 = write_plugin_files(tmp_path / "dir_501", members_501)
    assert cplug_validate.validate_v2_folder_files(dir_501)[1][0][0] == "cplug_too_large"
    with pytest.raises(install_gates.CplugGateRefusal) as gate_501:
        install_gates.check_files(dir_501)
    assert gate_501.value.code == install_gates.TOO_LARGE
    assert any("500" in e for e in checker.check_folder(dir_501).errors)

    two_mib = 2 * 1024 * 1024
    ok_2m = {"carnivore.toml": toml_b, "main.py": main_b, "big.txt": b"a" * two_mib}
    cplug_validate.validate_cplug_members(pid, ok_2m, handle="acme", version="1.0.0")
    bad_2m = {"carnivore.toml": toml_b, "main.py": main_b, "big.txt": b"a" * (two_mib + 1)}
    with pytest.raises(cplug_validate.CplugValidationError) as exc_2m:
        cplug_validate.validate_cplug_members(pid, bad_2m, handle="acme", version="1.0.0")
    assert exc_2m.value.code == "cplug_not_safe"
    dir_bad_2m = write_plugin_files(tmp_path / "dir_bad_2m", bad_2m)
    with pytest.raises(install_gates.CplugGateRefusal) as gate_2m:
        install_gates.check_files(dir_bad_2m)
    assert gate_2m.value.code == install_gates.TOO_LARGE
    assert checker.check_folder(dir_bad_2m).ok is False

    three_mib, half = 3 * 1024 * 1024, 1536 * 1024
    rem_ok = three_mib - (len(toml_b) + len(main_b) + half)
    ok_3m = {"carnivore.toml": toml_b, "main.py": main_b, "p1.txt": b"b" * half, "p2.txt": b"c" * rem_ok}
    dir_ok_3m = write_plugin_files(tmp_path / "dir_ok_3m", ok_3m)
    assert install_gates.check_files(dir_ok_3m) and checker.check_folder(dir_ok_3m).ok is True

    bad_3m = {**ok_3m, "p2.txt": b"c" * (rem_ok + 1)}
    with pytest.raises(cplug_validate.CplugValidationError) as exc_3m:
        cplug_validate.validate_cplug_members(pid, bad_3m, handle="acme", version="1.0.0")
    assert exc_3m.value.code == "cplug_not_safe"
    dir_bad_3m = write_plugin_files(tmp_path / "dir_bad_3m", bad_3m)
    with pytest.raises(install_gates.CplugGateRefusal) as gate_3m:
        install_gates.check_files(dir_bad_3m)
    assert gate_3m.value.code == install_gates.TOO_LARGE
    assert any("3 MiB" in e for e in checker.check_folder(dir_bad_3m).errors)


def test_symlink_fifo_noise_and_dual_manifest_refusal_across_validators(tmp_path: Path) -> None:
    pid = "symplug"
    base = {
        "carnivore.toml": _minimal_v2_toml(pid),
        "main.py": "from cplug_sdk import Plugin\nplugin = Plugin()\n",
        "LICENSE.md": DEFAULT_MIT_LICENSE,
    }

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    sym_dir = write_plugin_files(tmp_path / "sym_dir", base)
    (sym_dir / "leak.txt").symlink_to(outside)
    assert cplug_validate.validate_v2_folder_files(sym_dir)[1][0][0] == "cplug_not_safe"
    with pytest.raises(install_gates.CplugGateRefusal) as g_sym:
        install_gates.check_files(sym_dir)
    assert g_sym.value.code == install_gates.NOT_SAFE
    assert checker.check_folder(sym_dir).ok is False
    with pytest.raises(sideload.SideloadRefused) as s_sym:
        sideload.stage(tmp_path / "st_sym", pid, sym_dir)
    assert s_sym.value.code == "source_unsafe"

    fifo_dir = write_plugin_files(tmp_path / "fifo_dir", base)
    os.mkfifo(fifo_dir / "pipe.txt")
    assert cplug_validate.validate_v2_folder_files(fifo_dir)[1][0][0] == "cplug_not_safe"
    with pytest.raises(install_gates.CplugGateRefusal) as g_fifo:
        install_gates.check_files(fifo_dir)
    assert g_fifo.value.code == install_gates.NOT_SAFE
    assert checker.check_folder(fifo_dir).ok is False
    with pytest.raises(sideload.SideloadRefused) as s_fifo:
        sideload.stage(tmp_path / "st_fifo", pid, fifo_dir)
    assert s_fifo.value.code == "source_unsafe"

    noise_dir = write_plugin_files(tmp_path / "noise_dir", base)
    (noise_dir / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    (noise_dir / "mod.pyc").write_bytes(b"\x00compiled")
    assert checker.check_folder(noise_dir).ok is True
    kept_ign, errs_ign = cplug_validate.validate_v2_folder_files(noise_dir, ignore_junk=True)
    assert errs_ign == [] and not any(p.name in (".DS_Store", "mod.pyc") for p in kept_ign)
    copied = sideload_copy.copy_tree(noise_dir, tmp_path / "copied_noise")
    assert ".DS_Store" not in copied and "mod.pyc" not in copied
    with pytest.raises(install_gates.CplugGateRefusal) as g_noise:
        install_gates.check_files(noise_dir)
    assert g_noise.value.code == install_gates.NOT_SAFE

    dual_json = json.dumps({"schema": 2, "id": pid, "name": "Dual", "version": "1.0.0", "kind": "plugin", "description": "d", "author": "a"})
    dual_dir = write_plugin_files(tmp_path / "dual_dir", {**base, "carnivore.json": dual_json})
    with pytest.raises(cplug_validate.CplugValidationError) as c_dual:
        cplug_validate.validate_cplug_members(
            pid,
            {"carnivore.toml": base["carnivore.toml"].encode(), "carnivore.json": dual_json.encode(), "main.py": base["main.py"].encode()},
            handle="acme",
            version="1.0.0",
        )
    assert c_dual.value.code == "cplug_invalid"
    with pytest.raises(manifest_v2.ManifestV2Error):
        manifest_v2.load_manifest_v2(dual_dir)
    with pytest.raises(install_gates.CplugGateRefusal) as g_dual:
        install_gates.evaluate(f"acme/{pid}", dual_dir)
    assert g_dual.value.code == install_gates.MANIFEST_INVALID
    assert checker.check_folder(dual_dir).ok is False




@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_sandbox_exec_symlink_escape_to_ssh_db_config_blocked(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as w:
        _enable_sideload_switch(w)
        ssh_dir = Path(os.environ["HOME"]) / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        ssh_key = ssh_dir / "id_rsa"
        ssh_key.write_text("PRIVATE-SSH-KEY-SECRET", encoding="utf-8")
        db_file = w.state / "carnivore.db"
        if not db_file.exists():
            db_file.write_text("SQLITE-DB-SECRET", encoding="utf-8")
        w.config_path.write_text('{"api_key":"CONFIG-SECRET"}\n', encoding="utf-8")

        plug_dir = build_python_plugin(
            tmp_path / "src_plug",
            plugin_id="symescape",
            tier="local",
            main_py=f"""
                import os
                from pathlib import Path
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.tool("probe_escapes", "Try symlink escapes", {{"type": "object"}}, gate="read")
                async def probe_escapes(_args, _caller):
                    files_dir = Path(os.environ["CARNIVORE_DATA_DIR"])
                    (files_dir / "own.txt").write_text("ok-own", encoding="utf-8")
                    targets = {{"ssh": Path({str(ssh_key)!r}), "db": Path({str(db_file)!r}), "config": Path({str(w.config_path)!r})}}
                    results = {{"own": (files_dir / "own.txt").read_text(encoding="utf-8")}}
                    for label, target in targets.items():
                        link = files_dir / f"escape_{{label}}"
                        if link.is_symlink() or link.exists():
                            link.unlink()
                        os.symlink(target, link)
                        try:
                            _ = link.read_bytes()
                            results[label] = "LEAKED"
                        except OSError as exc:
                            results[label] = f"blocked:{{type(exc).__name__}}"
                    return results
            """,
        )
        toml_txt = (
            (plug_dir / "carnivore.toml")
            .read_text(encoding="utf-8")
            .replace('name = "ping"', 'name = "probe_escapes"')
            .replace('description = "Ping tool"', 'description = "Try symlink escapes"')
            .replace('inputSchema = { type = "object", properties = { msg = { type = "string" } } }', 'inputSchema = { type = "object" }')
        )
        (plug_dir / "carnivore.toml").write_text(toml_txt, encoding="utf-8")

        assert w.sideload_and_enable(plug_dir, "symescape")["enabled"] is True
        resp = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "symescape", "tool": "probe_escapes", "args": {}}, headers=w.owner_headers)
        assert resp.status_code == 200, resp.text
        parsed = json.loads(resp.json()["text"].splitlines()[-1])
        assert parsed["own"] == "ok-own"
        for label in ("ssh", "db", "config"):
            assert parsed[label].startswith("blocked:"), f"{label} leaked: {parsed}"


def test_linux_bwrap_and_unshare_command_shape_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_dir, code_dir, data_dir = tmp_path / "runtime", tmp_path / "code", tmp_path / "data"
    sock, carnivore_bin = tmp_path / "plugin.sock", tmp_path / "bin" / "carnivore"
    for d in (runtime_dir, code_dir, data_dir / "files", carnivore_bin.parent):
        d.mkdir(parents=True, exist_ok=True)
    sock.write_text("", encoding="utf-8")
    carnivore_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_interp = tmp_path / "bin" / "runtime_exe"
    fake_interp.write_text("#!/bin/sh\n", encoding="utf-8")
    stdlib = tmp_path / "stdlib"
    stdlib.mkdir()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("bwrap", "unshare") else None)

    for kind, allow_fork in (("python", False), ("node", False), ("bun", False), ("bash", True), ("binary", False)):
        layout = sandbox.Layout(
            interpreter=fake_interp, stdlib_root=stdlib, runtime_dir=runtime_dir, code_dir=code_dir, data_dir=data_dir,
            runtime_kind=kind, exec_paths=(fake_interp,), allow_fork=allow_fork, socket_path=sock,
            carnivore_bin=carnivore_bin, plugin_id="linplug", run_mode="rpc",
        )
        argv = sandbox.build_polyglot_command(layout, None, [str(fake_interp), "entry"])
        assert argv[0] == "/usr/bin/bwrap"
        assert {"--unshare-net", "--unshare-pid", "--die-with-parent", "--new-session"} <= set(argv)
        assert "--ro-bind" in argv and str(code_dir) in argv and str(layout.files_dir) in argv
        assert argv[-3:] == ["--", str(fake_interp), "entry"]
        rs = sandbox.landlock_ruleset(layout)
        assert str(code_dir) in rs["ro"] and str(layout.files_dir) in rs["rw"] and str(sock.resolve()) in rs["rw"]

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/unshare" if name == "unshare" else None)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: subprocess.CompletedProcess([], 0))
    layout_py = sandbox.Layout(interpreter=fake_interp, stdlib_root=stdlib, runtime_dir=runtime_dir, code_dir=code_dir, data_dir=data_dir)
    assert sandbox.build_polyglot_command(layout_py, None, [str(fake_interp), "main.py"]) == ["/usr/bin/unshare", "-rn", str(fake_interp), "main.py"]


@pytest.mark.asyncio
async def test_socket_peer_uid_spoof_sibling_isolation_and_frame_hardening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "st"
    state_dir.mkdir(parents=True)
    ctx_a = PluginContext(plugin_id="plug_a", install_key="key-a", data_dir=tmp_path / "da", granted=frozenset(), tier="local")
    dispatcher = HostDispatcher(HostServices(activity=lambda _e: None), OwnerTokens())

    spoof_sock = socket_server.socket_path_for(state_dir, "spoof")
    srv_spoof = socket_server.PluginSocketServer(ctx_a, dispatcher, spoof_sock, allowed_peer_uid=os.getuid())
    real_spoof = await srv_spoof.start()
    try:
        with monkeypatch.context() as mp:
            mp.setattr(socket_server, "peer_uid", lambda _sock: os.getuid() + 999)
            r, wr = await asyncio.open_unix_connection(str(real_spoof))
            wr.write(b'{"jsonrpc":"2.0","id":1,"method":"storage.get","params":{"key":"x"}}\n')
            await wr.drain()
            assert await asyncio.wait_for(r.read(1024), timeout=2.0) == b""
            wr.close()
    finally:
        await srv_spoof.stop()

    sock_a = socket_server.socket_path_for(state_dir, "key-a")
    srv_a = socket_server.PluginSocketServer(ctx_a, dispatcher, sock_a)
    real_a = await srv_a.start()
    try:
        for bad_line, expected_slug in (
            (b"{not json\n", "bad_json"),
            (b'{"jsonrpc":"2.0","jsonrpc":"2.0","id":1,"method":"storage.get","params":{}}\n', "duplicate_key"),
            (b'{"jsonrpc":"2.0","id":1,"method":"storage.get","params":{}}\n{"jsonrpc":"2.0","id":1,"method":"storage.get","params":{}}\n', "id_not_increasing"),
            (b'{"jsonrpc":"2.0","id":1,"method":"storage.get","params":{"pad":"' + (b"x" * (frames.MAX_FRAME_BYTES + 64)) + b'"}}\n', "frame_too_large"),
        ):
            r, wr = await asyncio.open_unix_connection(str(real_a))
            wr.write(bad_line)
            await wr.drain()
            raw = await asyncio.wait_for(r.readuntil(b"\n"), timeout=2.0)
            if expected_slug == "id_not_increasing":
                raw = await asyncio.wait_for(r.readuntil(b"\n"), timeout=2.0)
            reply = json.loads(raw.decode("utf-8"))
            assert reply["error"]["code"] == frames.INVALID_REQUEST
            assert expected_slug in reply["error"]["message"]
            wr.close()

        if DARWIN_SANDBOX:
            rt_dir = sandbox.copy_runtime(state_dir, "9.9.9")
            code_b, data_b = tmp_path / "code_b", tmp_path / "data_b"
            code_b.mkdir()
            (data_b / "files").mkdir(parents=True)
            sock_b = socket_server.socket_path_for(state_dir, "key-b")
            srv_b = socket_server.PluginSocketServer(
                PluginContext(plugin_id="plug_b", install_key="key-b", data_dir=data_b, granted=frozenset(), tier="local"),
                dispatcher,
                sock_b,
            )
            real_b = await srv_b.start()
            try:
                interp = sandbox.find_interpreter()
                layout_b = sandbox.Layout(
                    interpreter=interp, stdlib_root=sandbox.stdlib_root(interp), runtime_dir=rt_dir,
                    code_dir=code_b, data_dir=data_b, socket_path=real_b, plugin_id="plug_b",
                )
                profile_b = sandbox.write_profile(layout_b)
                probe_py = (
                    "import json, socket, sys\nout = {}\n"
                    "for k, p in (('own', sys.argv[1]), ('sibling', sys.argv[2])):\n"
                    "  s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
                    "  try:\n    s.connect(p); out[k] = 'connected'\n  except OSError as e:\n    out[k] = type(e).__name__\n"
                    "  finally:\n    s.close()\n"
                    "print(json.dumps(out))\n"
                )
                done = subprocess.run(
                    ["/usr/bin/sandbox-exec", "-f", str(profile_b), str(interp), "-I", "-B", "-c", probe_py, str(real_b), str(real_a)],
                    capture_output=True, text=True, env=sandbox.allow_env(layout_b), timeout=10, check=False,
                )
                assert done.returncode == 0, done.stderr
                seen = json.loads(done.stdout.strip().splitlines()[-1])
                assert seen["own"] == "connected" and seen["sibling"] == "PermissionError"
            finally:
                await srv_b.stop()
    finally:
        await srv_a.stop()


@pytest.mark.skipif(not has_node(), reason="Node.js required for @carnivore/plugin-sdk tests")
def test_ts_sdk_socket_host_malformed_disconnect_and_oneshot_timeout(tmp_path: Path) -> None:
    node_exe = sandbox._find_node()
    sock_dir = Path(tempfile.mkdtemp(prefix="ts-", dir="/tmp"))
    try:
        script = f"""
import assert from "node:assert/strict";
import net from "node:net";
import {{ PassThrough }} from "node:stream";
import {{ HostError, Plugin, connectSocket }} from {json.dumps(str(SDK_TS_DIST))};

const sockPath = {json.dumps(str(sock_dir / "t.sock"))};
let mode = "malformed";
let activeConn = null;
const srv = net.createServer((conn) => {{
  activeConn = conn;
  conn.on("data", () => {{
    if (mode === "malformed") conn.write("not-valid-json\\n");
    else if (mode === "disconnect") conn.destroy();
  }});
}});

await new Promise((r) => srv.listen(sockPath, r));
try {{
  const s1 = await connectSocket(sockPath);
  await assert.rejects(() => s1.call("projects.list", {{}}));
  s1.close();

  mode = "disconnect";
  const s2 = await connectSocket(sockPath);
  await assert.rejects(() => s2.call("projects.list", {{}}), /socket closed/);
  s2.close();

  mode = "hang";
  const s3 = await connectSocket(sockPath, {{ timeoutMs: 60 }});
  await assert.rejects(
    () => s3.call("projects.list", {{}}),
    (err) => err instanceof HostError && err.code === -32006 && err.reason === "timeout",
  );
  s3.close();

  const plugin = new Plugin().tool("boom", "Fails", async () => {{ throw new Error("oneshot boom"); }});
  const inp = new PassThrough();
  const out = new PassThrough();
  const chunks = [];
  out.on("data", (c) => chunks.push(c));
  const done = plugin.serve({{ input: inp, output: out, mode: "oneshot", sockPath }});
  inp.end(JSON.stringify({{ jsonrpc: "2.0", id: 5, method: "tools/call", params: {{ name: "boom", arguments: {{}} }} }}) + "\\n");
  await done;
  const reply = JSON.parse(Buffer.concat(chunks).toString("utf8").trim());
  assert.equal(reply.id, 5);
  assert.equal(reply.error.code, -32603);
  console.log(JSON.stringify({{ ok: true }}));
}} finally {{
  if (activeConn) activeConn.destroy();
  srv.close();
}}
"""
        script_path = tmp_path / "check_ts_sdk.mjs"
        script_path.write_text(script, encoding="utf-8")
        proc = subprocess.run([str(node_exe), str(script_path)], capture_output=True, text=True, timeout=15, check=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"ok": True}
    finally:
        shutil.rmtree(sock_dir, ignore_errors=True)


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_sandbox_exec_local_http_probe_ssrf_redirect_and_secret_echo_redaction(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    secret_val = "sk-e2e-" + "live-secret-99887766"
    with serve_http_probe() as probe, build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as w:
        _enable_sideload_switch(w)
        probe_ip, probe_port = probe.host_port
        probe.set_route("/echo", status=200, body=json.dumps({"echo": secret_val, "ok": True}).encode("utf-8"), headers={"Content-Type": "application/json", "X-Leak": f"Bearer {secret_val}", "X-Safe": "yes"})
        probe.set_route("/redir", status=302, body=b"", headers={"Location": f"http://127.0.0.1:{probe_port}/steal"})
        probe.set_route("/steal", status=200, body=b'{"stolen":true}')

        orig_gai = socket.getaddrinfo

        def _fake_gai(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            if host == "api.example.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", int(port or 443)))]
            return orig_gai(host, port, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", _fake_gai)
        orig_send = StdlibTransport.send

        def _routed_send(self_tr: StdlibTransport, *, ip: str, port: int, tls: bool, host: str, method: str, target: str, headers: Any, body: Any, deadline: float, max_bytes: int) -> RawResponse:
            if ip == "93.184.216.34" and host == "api.example.com":
                return orig_send(self_tr, ip=probe_ip, port=probe_port, tls=False, host=host, method=method, target=target, headers=headers, body=body, deadline=deadline, max_bytes=max_bytes)
            return orig_send(self_tr, ip=ip, port=port, tls=tls, host=host, method=method, target=target, headers=headers, body=body, deadline=deadline, max_bytes=max_bytes)

        monkeypatch.setattr(StdlibTransport, "send", _routed_send)

        plug_dir = build_bash_plugin(
            tmp_path / "src_fetch",
            plugin_id="fetchsec",
            mode="rpc",
            read_sessions=False,
            extra_toml="""
            [permissions]
            network = [{ host = "api.example.com", methods = ["GET", "POST"], paths = ["/"] }]
            secrets = [{ key = "api_token", label = "API Token" }]

            [permissions.reasons]
            "network:api.example.com" = "Reach test API"
            """,
            main_sh=f"""#!/bin/bash
while IFS= read -r line; do
  id="${{line##*\\"id\\":}}"; id="${{id%%,*}}"; id="${{id%%\\}}*}}"; id="${{id//[!0-9]/}}"
  if [[ "$line" == *'"initialize"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"api_version":1,"capabilities":{{"tools":true}},"subscriptions":[]}}}}\\n' "$id"
  elif [[ "$line" == *'"tools/list"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"tools":[{{"name":"ping","description":"Ping tool","gate":"read","inputSchema":{{"type":"object","properties":{{"msg":{{"type":"string"}}}}}}}}]}}}}\\n' "$id"
  elif [[ "$line" == *'"tools/call"'* ]]; then
    set +e
    SSRF_IP=$("$CARNIVORE_BIN" fetch "http://127.0.0.1:{probe_port}/steal" 2>&1); SSRF_IP_RC=$?
    SSRF_META=$("$CARNIVORE_BIN" fetch "http://169.254.169.254/latest/meta-data" 2>&1); SSRF_META_RC=$?
    REDIR_OUT=$("$CARNIVORE_BIN" fetch "https://api.example.com/redir" 2>&1); REDIR_RC=$?
    ECHO_OUT=$("$CARNIVORE_BIN" fetch "https://api.example.com/echo" -X POST -H 'Authorization: Bearer $SECRET:api_token' --json '{{"ok":1}}' 2>&1); ECHO_RC=$?
    set -e
    RES=$(A="$SSRF_IP_RC" B="$SSRF_META_RC" C="$REDIR_RC" D="$ECHO_RC" E="$ECHO_OUT" F="$REDIR_OUT" "$CARNIVORE_SOCK_PYTHON" -c '
import json, os
print(json.dumps({{
  "ssrf_ip_rc": int(os.environ["A"]), "ssrf_meta_rc": int(os.environ["B"]),
  "redir_rc": int(os.environ["C"]), "redir_err": os.environ["F"],
  "echo_rc": int(os.environ["D"]), "echo": json.loads(os.environ["E"]),
}}, separators=(",", ":")))
')
    printf '{{"jsonrpc":"2.0","id":%s,"result":%s}}\\n' "$id" "$RES"
  elif [[ "$line" == *'"shutdown"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"ok":true}}}}\\n' "$id"; exit 0
  fi
done
""",
        )

        assert w.sideload_and_enable(plug_dir, "fetchsec", secrets={"api_token": secret_val})["enabled"] is True
        resp = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "fetchsec", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["result"]
        assert data["ssrf_ip_rc"] == 1 and data["ssrf_meta_rc"] == 1 and data["redir_rc"] == 1
        assert "ip_literal" in data["redir_err"] or "permission_denied" in data["redir_err"]
        echo = data["echo"]
        assert data["echo_rc"] == 0 and echo["status"] == 200
        assert "x-leak" not in echo["headers"] and echo["headers"].get("x-safe") == "yes"
        assert secret_val not in echo["body"] and "[redacted]" in echo["body"]

        assert [r.path for r in probe.seen()] == ["/redir", "/echo"]
        assert probe.seen()[-1].headers.get("authorization") == f"Bearer {secret_val}"
        assert any(r["outcome"] == "credential_echo" for r in egress_log.EgressLog(w.state).recent(w.host.install_key("fetchsec"), 10))




def test_ui_slots_multi_plugin_128kib_isolation_and_cap(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    host = Host(state_dir)
    def_a = _make_tier0_def(tmp_path / "plugins" / "slota", "slota")
    def_b = _make_tier0_def(tmp_path / "plugins" / "slotb", "slotb")
    for d in (def_a, def_b):
        owner_state.update(
            state_dir,
            d.manifest,
            None,
            lambda st, m=d.manifest: replace(
                st, enabled=True, grants=tuple(m.permissions), ui_slot_grants=("session.badges",), digest=m.code_digest
            ),
        )

    reg = ui_slots.UiSlotRegistry(state_dir)
    frag_6k = {
        "schema": 2,
        "root": {"type": "column", "children": [{"type": "text", "value": "x" * 1900}, {"type": "text", "value": "y" * 1900}, {"type": "text", "value": "z" * 1900}]},
    }
    reg.publish("slota", "session.badges", [frag_6k for _ in range(12)], host=host, definitions=[def_a, def_b])
    with pytest.raises(ui_slots.UiSlotError) as exc_b:
        reg.publish("slotb", "session.badges", [frag_6k for _ in range(25)], host=host, definitions=[def_a, def_b])
    assert exc_b.value.code == "slot_payload_too_large"
    resolved_after_b_fail = reg.resolve(host=host, definitions=[def_a, def_b])
    assert [e["plugin_id"] for e in resolved_after_b_fail["slots"]["session.badges"]] == ["slota"] * 12 + ["slotb"]

    reg.publish("slotb", "session.badges", [frag_6k for _ in range(12)], host=host, definitions=[def_a, def_b])
    resolved_both = reg.resolve(host=host, definitions=[def_a, def_b])
    assert len(resolved_both["slots"]["session.badges"]) == 24


@pytest.mark.skipif(not has_node(), reason="Node.js required to execute web/src/lib/cplug-ui/validate.ts")
def test_ui_doc_py_and_validate_ts_differential_parity(tmp_path: Path) -> None:
    node_exe = sandbox._find_node()
    declared = {"routes": ["refresh"], "tools": ["ping"]}

    def _nest(levels: int) -> Dict[str, Any]:
        node: Dict[str, Any] = {"type": "text", "value": "leaf"}
        for _ in range(levels):
            node = {"type": "column", "children": [node]}
        return node

    def _many_nodes(count: int) -> Dict[str, Any]:
        return {"type": "column", "children": [{"type": "text", "value": "n"} for _ in range(count - 1)]}

    cases: List[Dict[str, Any]] = [
        {"name": "bidi_rlo", "doc": {"schema": 2, "root": {"type": "text", "value": "hi\u202ebye"}}, "ok": False, "code": "invisible_character"},
        {"name": "zero_width_space", "doc": {"schema": 2, "root": {"type": "text", "value": "a\u200bb"}}, "ok": False, "code": "invisible_character"},
        {"name": "zero_width_bom", "doc": {"schema": 2, "root": {"type": "text", "value": "a\ufeffb"}}, "ok": False, "code": "invisible_character"},
        {"name": "scheme_javascript", "doc": {"schema": 2, "root": {"type": "text", "value": "javascript:alert(1)"}}, "ok": False, "code": "link_not_allowed"},
        {"name": "scheme_https", "doc": {"schema": 2, "root": {"type": "section", "title": "go https://evil.example", "children": []}}, "ok": False, "code": "link_not_allowed"},
        {"name": "nodes_500_ok", "doc": {"schema": 2, "root": _many_nodes(500)}, "ok": True, "code": None},
        {"name": "nodes_501_fail", "doc": {"schema": 2, "root": _many_nodes(501)}, "ok": False, "code": "too_many_nodes"},
        {"name": "depth_12_ok", "doc": {"schema": 2, "root": _nest(12)}, "ok": True, "code": None},
        {"name": "depth_13_fail", "doc": {"schema": 2, "root": _nest(13)}, "ok": False, "code": "too_deep"},
        {"name": "bytes_over_64kib", "doc": {"schema": 2, "root": {"type": "column", "children": [{"type": "text", "value": "a" * 1900} for _ in range(36)]}}, "ok": False, "code": "too_large"},
        {
            "name": "valid_v2_sample",
            "doc": {
                "schema": 2,
                "root": {
                    "type": "form",
                    "action": {"call": "route", "route": "refresh"},
                    "children": [{"type": "input", "name": "q", "label": "Query"}, {"type": "markdown_safe", "value": "**bold** `code`"}, {"type": "sparkline", "values": [1, 2, 3], "label": "Rate"}],
                },
            },
            "ok": True,
            "code": None,
        },
    ]

    py_results: List[Dict[str, Any]] = []
    for case in cases:
        try:
            ui_doc.validate(case["doc"], routes=declared["routes"], tools=declared["tools"])
            py_results.append({"name": case["name"], "ok": True, "code": None, "path": None})
        except ui_doc.UiDocError as exc:
            py_results.append({"name": case["name"], "ok": False, "code": exc.code, "path": exc.path})

    corpus_path = tmp_path / "parity_corpus.json"
    corpus_path.write_text(json.dumps([{"name": c["name"], "doc": c["doc"]} for c in cases]), encoding="utf-8")
    ts_runner = tmp_path / "run_validate_ts.mjs"
    ts_runner.write_text(
        f"""
import fs from "node:fs";
import {{ createJiti }} from {json.dumps(str(JITI_MJS))};
const jiti = createJiti(import.meta.url);
const {{ validateDocument }} = await jiti.import({json.dumps(str(VALIDATE_TS))});
const corpus = JSON.parse(fs.readFileSync({json.dumps(str(corpus_path))}, "utf8"));
const declared = {json.dumps(declared)};
console.log(JSON.stringify(corpus.map((item) => {{
  const v = validateDocument(item.doc, declared);
  return v.ok ? {{ name: item.name, ok: true, code: null, path: null }} : {{ name: item.name, ok: false, code: v.code, path: v.path }};
}})));
""",
        encoding="utf-8",
    )
    proc = subprocess.run([str(node_exe), str(ts_runner)], capture_output=True, text=True, timeout=15, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ts_results = json.loads(proc.stdout.strip().splitlines()[-1])

    for case, py_r, ts_r in zip(cases, py_results, ts_results):
        assert py_r["ok"] is case["ok"] and py_r["code"] == case["code"], (case["name"], py_r)
        assert ts_r == py_r, f"parity mismatch for {case['name']}: py={py_r} ts={ts_r}"


def test_view_asset_route_path_traversal_and_symlink_rejection(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as w:
        _enable_sideload_switch(w)
        plug_dir = write_plugin_files(
            tmp_path / "viewplug",
            {
                "carnivore.toml": _minimal_v2_toml("viewplug", tier="local").replace(
                    '[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n',
                    '[[ui.views]]\nname = "main"\nsurfaces = ["panel"]\nfiles = ["index.html", "app.js"]\n',
                ),
                "views/main/index.html": "<html><head></head><body><h1>View</h1></body></html>\n",
                "views/main/app.js": "console.log('ok');\n",
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )
        w.sideload_and_enable(plug_dir, "viewplug")

        r_ticket = w.client.post("/api/v1/cplugs/viewplug/view/main/ticket", headers=w.owner_headers)
        assert r_ticket.status_code == 200, r_ticket.text
        index_path = r_ticket.json()["path"]
        base_url = index_path.rsplit("/", 1)[0]

        r_ok = w.client.get(index_path)
        assert r_ok.status_code == 200 and "carnivore-frame.css" in r_ok.text
        assert w.client.get(f"{base_url}/app.js").status_code == 200

        for bad_rest in ("..%2f..%2fcarnivore.toml", "../index.html", "../../main.py", "undeclared.js"):
            assert w.client.get(f"{base_url}/{bad_rest}").status_code == 404

        secret_file = tmp_path / "host_secret.js"
        secret_file.write_text("SECRET=1;", encoding="utf-8")
        installed_js = w.state / "plugins" / "viewplug" / "views" / "main" / "app.js"
        installed_js.unlink()
        installed_js.symlink_to(secret_file)
        assert w.client.get(f"{base_url}/app.js").status_code == 404


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="macOS sandbox-exec required")
def test_real_sandbox_3_strike_crash_loop_auto_pause_inspector_and_restart(
    tmp_path: Path, owner_jwt: str, key_store: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as w:
        _enable_sideload_switch(w)

        async def _fast_sleep(_delay: float) -> None:
            await asyncio.sleep(0.01)

        w.rt.supervisor._sleep = _fast_sleep
        plug_dir = build_python_plugin(
            tmp_path / "src_crash",
            plugin_id="crash3",
            tier="local",
            extra_toml="""
            [permissions]
            events = ["crash3:boot"]

            [permissions.reasons]
            "events:crash3:boot" = "Trigger eager start"

            [events]
            on = ["crash3:boot"]
            """,
            main_py="""
                import asyncio, os
                from pathlib import Path
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.on("crash3:boot")
                async def on_boot(_seq, _payload):
                    return None

                @plugin.tool("ping", "Ping tool", {"type": "object", "properties": {"msg": {"type": "string"}}}, gate="read")
                async def ping(_args, _caller):
                    return {"ok": True}

                _orig_serve = plugin.serve
                async def _serve(*args, **kwargs):
                    if (Path(os.environ["CARNIVORE_DATA_DIR"]) / "crash.flag").exists():
                        asyncio.get_running_loop().call_later(0.06, os._exit, 1)
                    return await _orig_serve(*args, **kwargs)
                plugin.serve = _serve
            """,
        )

        w.sideload_and_enable(plug_dir, "crash3")
        crash_flag = w.state / "plugin-data" / w.host.install_key("crash3") / "files" / "crash.flag"
        crash_flag.parent.mkdir(parents=True, exist_ok=True)
        crash_flag.write_text("crash", encoding="utf-8")

        assert w.client.post("/api/v1/cplugs/crash3/restart", headers=w.owner_headers).status_code == 200
        deadline, row_now = time.monotonic() + 15.0, {}
        while time.monotonic() < deadline:
            row_now = w.client.get("/api/v1/cplugs/crash3", headers=w.owner_headers).json()
            if row_now.get("process") == "crash_loop":
                break
            time.sleep(0.05)

        assert row_now["process"] == "crash_loop" and row_now["state"] == "unavailable"
        assert row_now["watchdog"]["crash_loop_paused"] is True and row_now["watchdog"]["strikes"] == 3

        insp = w.client.get("/api/v1/cplugs/crash3/inspector", headers=w.owner_headers).json()
        assert insp["state"] == "crash_loop" and insp["watchdog"]["crash_loop_paused"] is True and insp["watchdog"]["strikes"] == 3

        crash_flag.unlink()
        r_res = w.client.post("/api/v1/cplugs/crash3/restart", headers=w.owner_headers)
        assert r_res.status_code == 200, r_res.text
        rec = r_res.json()
        assert rec["state"] == "active" and rec["process"] == "running"
        assert rec["watchdog"]["crash_loop_paused"] is False and rec["watchdog"]["strikes"] == 0

        r_tool = w.client.post("/api/v1/cplug-owner/tool", json={"cplug_id": "crash3", "tool": "ping", "args": {}}, headers=w.owner_headers)
        assert r_tool.status_code == 200 and json.loads(r_tool.json()["text"].splitlines()[-1]) == {"ok": True}
