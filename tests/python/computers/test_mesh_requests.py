
from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mreq_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mreq_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from src.api import federation_mesh_routes, peer_auth  # noqa: E402
from src.core.computers import mesh, mesh_link  # noqa: E402
from src.core.computers.mux import frames as mf  # noqa: E402
from src.core.computers.mux.session import MuxError  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import mesh_client, mesh_listener  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402
from src.main import app  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _pair, _wait, root  # noqa: E402,F401
from tests.python.pack import test_settings_signing as ss  # noqa: E402

HELLO = "/api/v1/federation/hello"


class Probe:

    def __init__(self, inner) -> None:
        self.inner, self.seen, self.routes = inner, [], inner.routes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            self.seen.append(scope)
        await self.inner(scope, receive, send)


async def _raw_get(port: int, path: str, headers: str = "") -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n{headers}\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(4096), 5)
    writer.close()
    return data


def test_requests_ride_the_mesh_session_and_every_other_door_is_shut(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    db = db_path_for(state)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(db, create=False))
    monkeypatch.setattr(peer_auth, "read_install_id", lambda conn: C)
    monkeypatch.setattr(federation_mesh_routes, "_WINDOWS", federation_mesh_routes.pairing.KeyedWindows(60, 60.0))

    async def scenario() -> None:
        probe = Probe(app)
        async with _pair(root, tmp_path, attach=("c",)) as p:
            await mesh_listener.start(probe)
            try:
                await _wait(lambda: C in p.links["b"]._sessions and B in p.links["c"]._sessions)
                sb, sc = p.links["b"]._sessions[C], p.links["c"]._sessions[B]
                port = mesh_listener.port()
                assert port > 0
                assert sb.own_sha == p.idents["b"].cert.cert_sha256 and sc.own_sha == p.idents["c"].cert.cert_sha256
                transport = mesh_client.MeshTransport(sb, B, root)
                route = await transport.establish()
                client = mesh_client.MeshPeerClient(route, session=sb, self_iid=B, sign=ss.KEYS["b"].sign, trusted=p.links["b"].trusted)
                reply = await client.request("GET", "/federation/hello")
                assert reply.status_code == 200 and reply.json()["install_id"] == C
                tagged = [s for s in probe.seen if s["path"] == HELLO]
                assert tagged and all(s["mesh_peer"] == B and s["client"] is None and s["via_peer_link"] is True for s in tagged)
                before = len(probe.seen)
                await client.request("GET", "/federation/hello", headers={"mesh_peer": C, "X-Mesh-Peer": C})
                assert probe.seen[before:] and all(s["mesh_peer"] == B for s in probe.seen[before:])
                raw = await client.public("POST", "/federation/mesh/token", json={"ts": 1, "nonce": "x", "signature": "y", "mesh_peer": C})
                assert raw.status_code == 401
                seen = len(probe.seen)
                assert (await _raw_get(port, HELLO)).startswith(b"HTTP/1.1 403")
                ws = await _raw_get(port, "/ws/events", "Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: " + base64.b64encode(os.urandom(16)).decode() + "\r\n")
                assert ws.startswith(b"HTTP/1.1 403")
                assert len(probe.seen) == seen
                sent = []

                async def send(msg) -> None:
                    sent.append(msg)

                await mesh_listener.MeshTag(None, mesh_listener.MeshPortTable())({"type": "websocket", "client": ("127.0.0.1", 1)}, None, send)
                assert sent == [{"type": "websocket.close", "code": 4403}]
                assert (await client.public("POST", "/federation/token", json={})).status_code == 404
                assert (await client.public("POST", "/federation/prove", json={})).status_code == 404
                denied = await client.request("GET", "/api/v1/sessions/list")
                assert denied.status_code == 403 and denied.json()["detail"]["code"] == "mesh_power_refused"
                resets = []
                stale = SimpleNamespace(service=mesh_link.PEER_API, session=sb.mux, reset=lambda why: resets.append(why))
                await p.links["c"]._handler(B)(stale)
                assert resets == [mf.RST_UNAVAILABLE]
                table = mesh_listener._LISTENER.table
                table.add(7, B, sb.mux)
                sent.clear()
                await mesh_listener.MeshTag(None, table)({"type": "http", "client": ("127.0.0.1", 7)}, None, send)
                assert sent[0]["status"] == 403
                await sb.mux.close(mf.GO_NORMAL)
                await _wait(lambda: sc.mux.closed.is_set())
                with pytest.raises(MuxError):
                    await sb.mux.open(mesh_link.PEER_API)
                assert p.links["c"].current_mux(B) is not sc.mux
                table.add(8, B, sc.mux)
                sent.clear()
                await mesh_listener.MeshTag(None, table)({"type": "http", "client": ("127.0.0.1", 8)}, None, send)
                assert sent[0]["status"] == 403
                await transport.close()
                assert not os.path.exists(transport.path)
            finally:
                await mesh_listener.stop()

    asyncio.run(scenario())
    assert mesh_listener.port() == 0


def test_hello_seen_echo_is_validated_and_optional():
    ok = mesh_link.build_hello("a", None, "ab" * 32)
    assert mesh_link.check_hello(ok, "a") is None and ok["seen"] == "ab" * 32
    assert mesh_link.check_hello(mesh_link.build_hello("a", None), "a") is None and "seen" not in mesh_link.build_hello("a", None)
    for bad in ("AB" * 32, "ab" * 31, 5, None):
        assert mesh_link.check_hello({**ok, "seen": bad}, "a") == mf.GO_PROTOCOL
