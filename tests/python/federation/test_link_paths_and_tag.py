
from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import tempfile
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
import httpx
from fastapi.testclient import TestClient

from src.api import federation_routes
from src.core.federation import back_route, fed_key, pair_socket, pairing, peer_prove
from src.core.federation.back_route import BackRouteInvalid
from src.core.federation.pairing import PairingOffers
from src.core.federation.pair_socket import PairSocket
from src.core.federation.peer_listener import PeerLinkTag, PeerListener
from src.core.relay_identity.device_key import DeviceKey
from src.core.hosts import ssh_exec, ssh_forward
from src.main import app

GRANT = "g1"


@pytest.fixture()
def fed():
    root = Path(tempfile.mkdtemp(prefix="fd"))
    os.chmod(root, 0o700)
    made = []

    def bind(directory: Path, name: str) -> Path:
        path = directory / name
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(path))
        made.append(sock)
        return path

    yield root, bind
    for sock in made:
        sock.close()
    for path in sorted(root.rglob("*"), reverse=True):
        path.unlink() if not path.is_dir() else path.rmdir()
    root.rmdir()


def test_a_socket_inside_the_dir_with_the_grants_name_is_accepted(fed):
    root, bind = fed
    path = bind(root, f"in-{GRANT}-ab12.sock")
    assert back_route.validate(root, GRANT, "unix", str(path), None) == ("unix", os.path.realpath(path), "")


def test_a_path_outside_the_dir_is_refused(fed):
    root, bind = fed
    other = Path(tempfile.mkdtemp(prefix="ot"))
    try:
        path = bind(other, f"in-{GRANT}-ab12.sock")
        with pytest.raises(BackRouteInvalid):
            back_route.validate(root, GRANT, "unix", str(path), None)
    finally:
        path.unlink()
        other.rmdir()


def test_a_symlink_out_of_the_dir_is_refused(fed):
    root, bind = fed
    other = Path(tempfile.mkdtemp(prefix="ot"))
    try:
        target = bind(other, f"in-{GRANT}-ab12.sock")
        link = root / f"in-{GRANT}-cd34.sock"
        link.symlink_to(target)
        with pytest.raises(BackRouteInvalid):
            back_route.validate(root, GRANT, "unix", str(link), None)
    finally:
        target.unlink()
        other.rmdir()


def test_a_non_socket_is_refused(fed):
    root, _ = fed
    path = root / f"in-{GRANT}-ab12.sock"
    path.write_text("x")
    with pytest.raises(BackRouteInvalid):
        back_route.validate(root, GRANT, "unix", str(path), None)


def test_a_foreign_uid_is_refused(fed, monkeypatch):
    root, bind = fed
    path = bind(root, f"in-{GRANT}-ab12.sock")
    mine = os.getuid()
    monkeypatch.setattr(back_route.os, "getuid", lambda: mine + 1)
    with pytest.raises(BackRouteInvalid):
        back_route.validate(root, GRANT, "unix", str(path), None)


def test_a_wide_dir_or_another_grants_name_is_refused(fed):
    root, bind = fed
    path = bind(root, f"in-{GRANT}-ab12.sock")
    with pytest.raises(BackRouteInvalid):
        back_route.validate(root, "g2", "unix", str(path), None)
    os.chmod(root, 0o750)
    with pytest.raises(BackRouteInvalid):
        back_route.validate(root, GRANT, "unix", str(path), None)
    os.chmod(root, 0o700)


def test_a_tcp_route_needs_a_port():
    assert back_route.validate(Path("/nope"), GRANT, "tcp", None, 5000, "r" * 32) == ("tcp", 5000, "r" * 32)
    for port, route_id in ((None, "r" * 32), (5000, None), (5000, "short")):
        with pytest.raises(BackRouteInvalid):
            back_route.validate(Path("/nope"), GRANT, "tcp", None, port, route_id)



@pytest.fixture()
def offers(tmp_path, monkeypatch):
    monkeypatch.setattr(federation_routes, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(pairing, "OFFERS", PairingOffers())
    monkeypatch.setattr(federation_routes, "_TOKEN_GRANT_WINDOWS", pairing.KeyedWindows(60, 60.0))
    monkeypatch.setattr(federation_routes, "_TOKEN_STRANGER_WINDOWS", pairing.KeyedWindows(20, 60.0))


def test_the_peer_ingress_serves_only_peer_routes(offers):
    plain = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))
    tagged = TestClient(PeerLinkTag(app), raise_server_exceptions=False, client=("127.0.0.1", 50000))
    for method, path in (("POST", "/api/v1/federation/pair/begin"), ("POST", "/api/v1/auth/verify"),
                         ("GET", "/api/v1/federation/grants"), ("GET", "/api/v1/setup/status"),
                         ("GET", "/api/v1/sessions/list-not-a-route"), ("GET", "/")):
        assert tagged.request(method, path).status_code == 404, path
    assert plain.post("/api/v1/federation/pair/begin").status_code == 401
    assert tagged.get("/api/v1/federation/hello").status_code == 401
    assert tagged.get("/api/v1/sessions/list").status_code == 401
    assert tagged.post("/api/v1/federation/token", json={}).status_code in (400, 422)
    assert tagged.post("/api/v1/federation/prove", json={}).status_code in (400, 422)


def test_the_real_listener_is_a_0600_socket_serving_only_peer_routes(offers):
    root = Path(tempfile.mkdtemp(prefix="pl"))
    path = str(root / "peer-x.sock")

    async def run():
        listener = PeerListener(app, path)
        await listener.start()
        try:
            mode = stat.S_IMODE(os.lstat(path).st_mode)
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=path),
                                         base_url="http://127.0.0.1") as http:
                return mode, await http.post("/api/v1/federation/pair/begin"), await http.get(
                    "/api/v1/federation/hello")
        finally:
            await listener.stop()

    try:
        mode, begin, hello = asyncio.run(run())
    finally:
        for p in root.iterdir():
            p.unlink()
        root.rmdir()
    assert mode == 0o600 and begin.status_code == 404 and hello.status_code == 401


def test_the_pair_socket_serves_our_uid_only(tmp_path):
    root = Path(tempfile.mkdtemp(prefix="ps"))
    path = str(root / "pair-x.sock")
    begun = []

    async def ask():
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(b"BEGIN\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        writer.close()
        return line

    async def run(uid):
        sock = PairSocket(path, tmp_path, begin=lambda d: begun.append(d) or "0123456789abcdef")
        await sock.start()
        try:
            if uid is not None:
                pair_socket.peer_uid = lambda _s: uid
            return mode_of(path), await ask()
        finally:
            await sock.stop()

    def mode_of(p):
        return stat.S_IMODE(os.lstat(p).st_mode)

    real = pair_socket.peer_uid
    try:
        mode, line = asyncio.run(run(None))
        assert mode == 0o600 and json.loads(line) == {"nonce": "0123456789abcdef",
                                                        "file": str(tmp_path / "federation" / "pair-0123456789abcdef")} and begun == [tmp_path]
        assert pair_socket.peer_uid(socket.socket(socket.AF_UNIX)) is None or True
        _, refused = asyncio.run(run(os.getuid() + 1))
        assert refused == b"" and len(begun) == 1
    finally:
        pair_socket.peer_uid = real
        for p in root.iterdir():
            p.unlink()
        root.rmdir()


def test_a_prove_signature_is_checked_against_the_pinned_key():
    key, other = DeviceKey.from_seed(bytes([1]) * 32), DeviceKey.from_seed(bytes([2]) * 32)
    pinned, nonce = fed_key.public_key_b64(key), b"n" * 16
    good = key.sign(peer_prove.prove_message(nonce, "iid"))
    assert peer_prove.verify(pinned, nonce, "iid", good)
    assert not peer_prove.verify(pinned, nonce, "iid", other.sign(peer_prove.prove_message(nonce, "iid")))
    assert not peer_prove.verify(pinned, b"m" * 16, "iid", good)
    assert not peer_prove.verify(pinned, nonce, "other-iid", good)
    assert not peer_prove.verify(pinned, nonce, "iid", "not-a-signature")



def test_forward_argv_clears_no_forwardings_but_the_master_keeps_clearing_them():
    dest = ssh_exec.SshDestination("studio")
    argv = ssh_forward.forward_argv(dest, "/tmp/cm/x-1a2b3c4d-0", "-L", "/tmp/a.sock:127.0.0.1:8000")
    assert "ClearAllForwardings=no" in argv and "ClearAllForwardings=yes" not in argv
    assert argv[argv.index("-O") + 1] == "forward" and argv[-2:] == ["--", "studio"]
    assert "ClearAllForwardings=yes" in ssh_exec.master_argv(dest, "/tmp/cm/x-1a2b3c4d-0")


def test_forward_paths_over_103_bytes_are_refused():
    ssh_forward._path("/" + "a" * 102)
    with pytest.raises(ssh_forward.ForwardError):
        ssh_forward._path("/" + "a" * 103)
