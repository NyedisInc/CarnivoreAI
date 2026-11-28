
from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.plugins.host.egress_log import EgressLog
from src.plugins.host.fetch_proxy import FetchRefused, PluginFetch, RateLimiter
from src.plugins.host.fetch_transport import RawResponse
from src.plugins.host.secret_store import SecretStore
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_spec import build_spec
from src.plugins.runtime import sandbox, socket_server
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.supervisor import Supervisor
from src.plugins.sdk.manifest_v2 import load_manifest_v2


class _FakeKeychain:
    def __init__(self) -> None:
        self.items: Dict[tuple, str] = {}

    def read(self, service: str, account: str):
        return self.items.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class _MockTransport:
    def __init__(self, handler):
        self._handler = handler

    def send(self, **kw):
        return self._handler(SimpleNamespace(**kw))


def _rpc_roundtrip(sock_path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = bytearray()
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\n" in buf:
                line, _, _ = buf.partition(b"\n")
                return json.loads(line.decode("utf-8"))
    raise AssertionError("No JSON-RPC response received")


def test_socket_path_for_long_state_dir_falls_back_under_104_bytes(tmp_path: Path) -> None:
    short = socket_server.socket_path_for(tmp_path, "abc123")
    assert len(str(short).encode("utf-8")) <= socket_server.SOCKET_PATH_MAX

    deep = tmp_path / ("very_long_segment_" * 8)
    deep.mkdir(parents=True, exist_ok=True)
    fb = socket_server.socket_path_for(deep, "plugin_install_key_abcdef123456")
    assert len(str(fb).encode("utf-8")) <= socket_server.SOCKET_PATH_MAX
    assert (stat.S_IMODE(fb.parent.stat().st_mode) & 0o777) == 0o700


@pytest.mark.asyncio
async def test_socket_server_binds_0600_verifies_uid_ignores_spoof_and_parity(tmp_path: Path) -> None:
    activity_rows: List[Dict[str, Any]] = []
    emitted: List[tuple] = []

    async def _perm_mode(ref: str) -> str:
        return f"auto:{ref}"

    async def _svc_call(ctx: PluginContext, service: str, method: str, args: Any) -> Dict[str, Any]:
        return {"caller": ctx.plugin_id, "service": service, "method": method, "args": args}

    async def _events_emit(ctx: PluginContext, name: str, payload: Any) -> Dict[str, Any]:
        emitted.append((ctx.plugin_id, name, payload))
        return {"ok": True}

    svc = HostServices(
        activity=activity_rows.append,
        list_sessions=lambda: asyncio.sleep(0, result=[{"ref": "s1", "name": "pane1"}]),
        permission_mode=_perm_mode,
        service_call=_svc_call,
        events_emit=_events_emit,
    )
    ctx = PluginContext(
        plugin_id="real-plugin",
        install_key="k1",
        data_dir=tmp_path / "data",
        granted=frozenset({"sessions.read", "sessions.paste", "services:acme.kv", "events:status.changed"}),
        services_consumes=("acme.kv",),
        events_emit=("status.changed",),
    )
    disp = HostDispatcher(svc, OwnerTokens(b"k" * 32))
    mgr = socket_server.PluginSocketManager()
    sock_path = await mgr.ensure(tmp_path / "state", ctx, disp)
    try:
        assert sock_path.exists()
        assert (stat.S_IMODE(sock_path.stat().st_mode) & 0o777) == 0o600

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.connect(str(sock_path))
            assert socket_server.peer_uid(probe) == os.geteuid()

        resp = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "service.call",
                "plugin_id": "forged-admin",
                "granted": ["sessions.control"],
                "params": {"service": "acme.kv", "method": "get", "args": {"k": "v"}, "plugin_id": "forged"},
            },
        )
        assert resp["result"]["caller"] == "real-plugin"

        bad_svc = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 2, "method": "service.call", "params": {"service": "other.svc", "method": "get", "args": {}}},
        )
        assert bad_svc["error"]["message"] == "not_granted"

        pm = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 3, "method": "sessions.permission_mode", "params": {"ref": "s1"}},
        )
        assert pm["result"] == {"mode": "auto:s1"}

        ev_ok = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 4, "method": "events.emit", "params": {"event": "status.changed", "payload": {"n": 1}}},
        )
        assert ev_ok["result"] == {"ok": True}
        assert emitted == [("real-plugin", "status.changed", {"n": 1})]

        ev_bad = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 5, "method": "events.emit", "params": {"event": "rogue.ev", "payload": {}}},
        )
        assert ev_bad["error"]["message"] == "not_granted"

        denied = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 6, "method": "sessions.create", "params": {"project": 1, "prompt": "hi"}},
        )
        assert denied["error"]["code"] == -32002

        assert any(row.get("plugin") == "real-plugin" and row.get("method") == "sessions.permission_mode" for row in activity_rows)
        assert any(row.get("plugin") == "real-plugin" and row.get("method") == "events.emit" for row in activity_rows)

        for idx in range(25):
            r = await asyncio.to_thread(
                _rpc_roundtrip,
                sock_path,
                {"jsonrpc": "2.0", "id": 100 + idx, "method": "sessions.list", "params": {}},
            )
            if "error" in r:
                assert r["error"]["message"] == "rate_limited"
                break
        else:
            pytest.fail("Expected rate_limited over socket dispatcher")

        await mgr.stop("real-plugin")
        assert not sock_path.exists()

        stale = tmp_path / "state" / socket_server.SOCKET_DIR_NAME / "orphan.sock"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            stale_sock.bind(str(stale))
        except OSError:
            stale = socket_server.socket_path_for(tmp_path / "state", "orphan_stale")
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.unlink(missing_ok=True)
            stale_sock.bind(str(stale))
        finally:
            stale_sock.close()
        assert mgr.sweep_stale(tmp_path / "state") >= 1
        assert not stale.exists()
    finally:
        await mgr.stop_all()


@pytest.mark.asyncio
async def test_v2_secret_placeholder_expansion_shorthand_binding_and_redaction(tmp_path: Path) -> None:
    code = tmp_path / "code" / "secplug"
    code.mkdir(parents=True, exist_ok=True)
    (code / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "secplug"
name = "Secret Plug"
version = "1.0.0"
kind = "plugin"
description = "Tests $SECRET expansion"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[permissions]
network = ["api.example.com", "other.example.org"]
secrets = ["api_token"]
""",
        encoding="utf-8",
    )
    m2 = load_manifest_v2(code)
    kc = _FakeKeychain()
    secrets = SecretStore(tmp_path / "state", keychain=kc)
    secrets.set("inst-sec", m2, "api_token", "sk_live_SUPERSECRET_9999")

    seen_headers: List[tuple] = []

    def _handler(req):
        seen_headers.append(tuple(req.headers))
        return RawResponse(
            status=200,
            headers=[("content-type", "application/json"), ("authorization", "Bearer sk_live_SUPERSECRET_9999")],
            body=b'{"echo":"sk_live_SUPERSECRET_9999","ok":true}',
        )

    from src.plugins.host import netguard

    egress = EgressLog(tmp_path / "state")
    fetcher = PluginFetch(
        m2,
        "inst-sec",
        lambda: ("network_hosts:api.example.com", "network_hosts:other.example.org"),
        secrets,
        egress,
        RateLimiter(per_minute=60),
        peers=lambda: netguard.Peers(frozenset()),
        resolver=lambda host, port: ["93.184.216.34"],
        transport=_MockTransport(_handler),
        is_own=lambda ip: False,
    )
    resp = await fetcher.fetch(
        "GET",
        "https://api.example.com/v1/items",
        headers={"X-Api-Key": "Token $SECRET:api_token", "X-Other": "plain"},
    )
    assert resp.status == 200
    hdr_map = dict((k.lower(), v) for k, v in seen_headers[0])
    assert hdr_map["x-api-key"] == "Token sk_live_SUPERSECRET_9999"
    assert b"sk_live_SUPERSECRET_9999" not in resp.body
    assert b"[redacted]" in resp.body
    assert "authorization" not in resp.headers
    assert any(row.get("outcome") == "credential_echo" for row in egress.recent("inst-sec"))

    with pytest.raises(FetchRefused) as exc_unknown:
        await fetcher.fetch(
            "GET",
            "https://api.example.com/v1/items",
            headers={"Authorization": "Bearer $SECRET:missing_key"},
        )
    assert exc_unknown.value.code == "secret_missing"

    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "secplug"
name = "Secret Plug"
version = "1.0.0"
kind = "plugin"
description = "Tests host mismatch"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[permissions]
network = ["api.example.com", "rogue.example.net"]
secrets = ["api_token"]
""",
        encoding="utf-8",
    )
    m2_changed = load_manifest_v2(code)
    fetcher_changed = PluginFetch(
        m2_changed,
        "inst-sec",
        lambda: ("network_hosts:api.example.com",),
        secrets,
        EgressLog(tmp_path / "state"),
        RateLimiter(per_minute=60),
        peers=lambda: netguard.Peers(frozenset()),
        resolver=lambda host, port: ["93.184.216.34"],
        transport=_MockTransport(_handler),
        is_own=lambda ip: False,
    )
    with pytest.raises(FetchRefused) as exc_mismatch:
        await fetcher_changed.fetch(
            "GET",
            "https://api.example.com/v1/items",
            headers={"Authorization": "Bearer $SECRET:api_token"},
        )
    assert exc_mismatch.value.code == "secret_missing"


@pytest.mark.asyncio
async def test_real_sandbox_exec_carnivore_bin_uses_sock_and_blocks_sibling_and_loopback(tmp_path: Path) -> None:
    try:
        sandbox.find_interpreter()
    except sandbox.SandboxUnavailable:
        pytest.skip("needs framework Python for sandbox-exec")
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        pytest.skip("needs macOS sandbox-exec")

    from src.core.cli_command import service as cli_service

    code = tmp_path / "code" / "binplug"
    code.mkdir(parents=True, exist_ok=True)
    sibling_sock = socket_server.socket_path_for(tmp_path / "state", "sibling_other")
    sibling_sock.parent.mkdir(parents=True, exist_ok=True)
    sibling_sock.unlink(missing_ok=True)
    srv_sib = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv_sib.bind(str(sibling_sock))
    srv_sib.listen(1)

    shim_path = tmp_path / "state" / "bin" / "carnivore"
    shim_path.parent.mkdir(parents=True, exist_ok=True)
    shim_path.write_text(cli_service.shim_content(Path("/nonexistent/repo"), sys.executable), encoding="utf-8")
    shim_path.chmod(0o755)

    (code / "main.py").write_text(
        """
import json
import os
import socket
import subprocess

from cplug_sdk import Plugin

plugin = Plugin()

@plugin.tool("probe_sock", "Probe socket CLI", {"type": "object"}, gate="read")
async def probe_sock(args, caller):
    bin_path = os.environ["CARNIVORE_BIN"]
    proc = subprocess.run([bin_path, "sessions", "list"], capture_output=True, text=True, check=False)
    cli_ok = proc.returncode == 0
    cli_out = json.loads(proc.stdout) if cli_ok and proc.stdout.strip() else proc.stderr

    sib_denied = False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(args["sibling_sock"])
        s.close()
    except PermissionError:
        sib_denied = True
    except OSError as exc:
        sib_denied = exc.errno in (1, 13)

    tcp_denied = False
    try:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.settimeout(1.0)
        s2.connect(("127.0.0.1", int(args["tcp_port"])))
        s2.close()
    except PermissionError:
        tcp_denied = True
    except OSError as exc:
        tcp_denied = exc.errno in (1, 13)

    outside_denied = False
    try:
        with open("/etc/hosts", "r", encoding="utf-8") as fh:
            fh.read()
    except PermissionError:
        outside_denied = True

    return {
        "cli_ok": cli_ok,
        "cli_out": cli_out,
        "sib_denied": sib_denied,
        "tcp_denied": tcp_denied,
        "outside_denied": outside_denied,
    }
""",
        encoding="utf-8",
    )
    (code / "carnivore.toml").write_text(
        """
schema = 2
id = "binplug"
name = "Bin Plug"
version = "1.0.0"
kind = "plugin"
description = "Uses CARNIVORE_BIN over CARNIVORE_PLUGIN_SOCK"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[permissions]
read = ["sessions"]

[mcp]
[[mcp.tools]]
name = "probe_sock"
description = "Probe socket CLI"
gate = "read"
inputSchema = { type = "object" }
""",
        encoding="utf-8",
    )

    tcp_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_srv.bind(("127.0.0.1", 0))
    tcp_srv.listen(1)
    tcp_port = tcp_srv.getsockname()[1]

    sm = load_sidecar_manifest(code, "binplug")
    d = SidecarDefinition(
        manifest=sm,
        item_id="local/binplug",
        install_key="binplug",
        code_root=code,
        folder=tmp_path / "data" / "binplug",
    )
    spec = build_spec(
        d,
        frozenset({"sessions.read"}),
        {},
        consent_owed=False,
    )
    svc = HostServices(
        activity=lambda _row: None,
        list_sessions=lambda: asyncio.sleep(0, result=[{"id": "s-live", "label": "demo", "host_key": "local"}]),
    )
    disp = HostDispatcher(svc, OwnerTokens(b"z" * 32))
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
        sock_p = mgr.path_for("binplug")
        assert sock_p is not None and sock_p.exists()

        proc = await sup.ensure("binplug")
        assert proc is not None
        res_raw = await proc.request(
            "tools/call",
            {"name": "probe_sock", "arguments": {"sibling_sock": str(sibling_sock), "tcp_port": tcp_port}, "caller": {"kind": "owner"}},
        )
        res = json.loads(res_raw["content"][0]["text"]) if "content" in res_raw else res_raw
        assert res["cli_ok"] is True, res
        assert res["cli_out"] == {"sessions": [{"id": "s-live", "label": "demo"}]}
        assert res["sib_denied"] is True
        assert res["tcp_denied"] is True
        assert res["outside_denied"] is True

        await sup.disable("binplug")
        assert not sock_p.exists()
    finally:
        await sup.shutdown()
        await mgr.stop_all()
        srv_sib.close()
        sibling_sock.unlink(missing_ok=True)
        tcp_srv.close()


@pytest.mark.asyncio
async def test_socket_server_refuses_declared_service_and_event_when_not_granted(tmp_path: Path) -> None:
    svc = HostServices(
        activity=lambda _row: None,
        service_call=lambda _ctx, s, m, a: asyncio.sleep(0, result={"s": s, "m": m, "a": a}),
        events_emit=lambda _ctx, e, p: asyncio.sleep(0, result={"e": e, "p": p}),
    )
    ctx_ungranted = PluginContext(
        plugin_id="ungranted-plugin",
        install_key="k-ungranted",
        data_dir=tmp_path / "data",
        granted=frozenset(),
        services_consumes=("acme.kv",),
        events_emit=("status.changed",),
    )
    disp = HostDispatcher(svc, OwnerTokens(b"u" * 32))
    mgr = socket_server.PluginSocketManager()
    sock_path = await mgr.ensure(tmp_path / "state", ctx_ungranted, disp)
    try:
        svc_denied = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 1, "method": "service.call", "params": {"service": "acme.kv", "method": "get", "args": {}}},
        )
        assert svc_denied["error"]["code"] == -32002
        assert svc_denied["error"]["message"] == "not_granted"

        ev_denied = await asyncio.to_thread(
            _rpc_roundtrip,
            sock_path,
            {"jsonrpc": "2.0", "id": 2, "method": "events.emit", "params": {"event": "status.changed", "payload": {}}},
        )
        assert ev_denied["error"]["code"] == -32002
        assert ev_denied["error"]["message"] == "not_granted"
    finally:
        await mgr.stop_all()


@pytest.mark.asyncio
async def test_socket_server_default_uid_remains_strict_and_allowed_peer_uid_overrides(tmp_path: Path) -> None:
    svc = HostServices(activity=lambda _row: None)
    ctx = PluginContext(plugin_id="uid-check", install_key="uid-k", data_dir=tmp_path / "data", granted=frozenset())
    disp = HostDispatcher(svc, OwnerTokens(b"z" * 32))
    mgr = socket_server.PluginSocketManager()
    await mgr.ensure(tmp_path / "state", ctx, disp)
    try:
        assert mgr._servers["uid-check"]._allowed_peer_uid == os.getuid()
    finally:
        await mgr.stop_all()

    mismatch_uid = os.getuid() + 1
    sock_path2 = socket_server.socket_path_for(tmp_path / "strict", "uid-k-strict")
    bound = socket_server.PluginSocketServer(ctx, disp, sock_path2)
    real_sock = await bound.start()
    bound._allowed_peer_uid = mismatch_uid
    try:
        def _probe_refused() -> bytes:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(str(real_sock))
                s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"sessions.list","params":{}}\n')
                return s.recv(1024)

        assert await asyncio.to_thread(_probe_refused) == b""
    finally:
        await bound.stop()
