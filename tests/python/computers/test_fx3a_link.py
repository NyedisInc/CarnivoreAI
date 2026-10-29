
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import ssl
import stat
import tempfile
import threading
import time
from pathlib import Path

import pytest
import structlog
import uvloop

from src.core.computers import link_listener as ll
from src.core.computers.tls_identity import client_link_ctx, ensure_link_identity, server_link_ctx
from src.core.federation import back_route
from src.core.relay_identity.device_key import DeviceKey


class _SlowAdmitGate(ll._HandshakeGate):

    def enter(self, source: str) -> bool:
        time.sleep(0.3)
        return super().enter(source)


class _Listener:

    def __init__(self, ctx, done: "asyncio.Future[bytes]") -> None:
        self._ctx, self._gate, self._done = ctx, _SlowAdmitGate(2, 8), done

    async def _on_tls_connection(self, reader, writer) -> None:
        self._done.set_result(await reader.readexactly(2))
        writer.close()


def _late_client(port: int, ctx: ssl.SSLContext, delay: float, out: list) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            time.sleep(delay)
            with ctx.wrap_socket(raw, server_hostname="x") as tls:
                tls.sendall(b"ok")
                out.append(tls.version())
    except OSError as exc:
        out.append(exc)


@pytest.mark.parametrize("make_loop", [asyncio.new_event_loop, uvloop.new_event_loop], ids=["asyncio", "uvloop"])
def test_the_tls_gate_handshakes_a_client_hello_that_arrives_after_the_accept(make_loop):
    root = Path(tempfile.mkdtemp(prefix="b1"))
    ids = {}
    for n in ("a", "b"):
        (root / n).mkdir(mode=0o700)
        ids[n] = ensure_link_identity(DeviceKey.from_seed(n.encode() * 32), f"{n}-install-{n * 8}", root / n)
    server_ctx = server_link_ctx(ids["a"], [ids["b"].cert])
    client_ctx = client_link_ctx(ids["b"], [ids["a"].cert])

    async def run() -> bytes:
        loop = asyncio.get_running_loop()
        done: "asyncio.Future[bytes]" = loop.create_future()
        listener = _Listener(server_ctx, done)
        server = await ll._TlsGate.open(listener, loop, "127.0.0.1", 0)
        out: list = []
        port = server.sockets[0].getsockname()[1]
        t = threading.Thread(target=_late_client, args=(port, client_ctx, 0.0, out))
        t.start()
        try:
            return await asyncio.wait_for(done, 4)
        finally:
            await asyncio.to_thread(t.join)
            server.close()
            assert out == ["TLSv1.3"], out

    loop = make_loop()
    try:
        assert loop.run_until_complete(run()) == b"ok"
    finally:
        loop.close()


GRANT = "g" * 32


def _long_fed(root: Path) -> Path:
    fed = root / ("deep" * 12) / ".carnivore" / "fed"
    fed.mkdir(parents=True, mode=0o700)
    assert len(str(fed / f"in-{GRANT}-abcd1234.sock")) > back_route.SOCKET_PATH_MAX
    return fed


@pytest.fixture()
def fallback_root(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="b2", dir="/tmp"))
    monkeypatch.setattr(back_route, "FALLBACK_ROOT", str(root))
    monkeypatch.setattr(back_route, "_user_temp_dir", lambda: None)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_a_short_fed_dir_is_used_as_it_is_and_a_long_one_gets_a_working_socket(tmp_path, fallback_root):
    short = fallback_root / "f"
    short.mkdir(mode=0o700)
    assert back_route.socket_dir(short, GRANT) == short
    fed = _long_fed(tmp_path)
    where = back_route.socket_dir(fed, GRANT)
    assert where == fallback_root / f"carnivore-{os.getuid()}" and stat.S_IMODE(os.lstat(where).st_mode) == 0o700
    assert back_route.socket_dir(fed, GRANT) == where
    path = where / f"in-{GRANT}-abcd1234.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        os.chmod(path, 0o600)
        assert back_route.validate(fed, GRANT, "unix", str(path), None)[0] == "unix"
    finally:
        server.close()


def test_the_fallback_directory_refuses_a_symlink_a_loose_mode_and_a_foreign_owner(tmp_path, fallback_root, monkeypatch):
    fed = _long_fed(tmp_path)
    fallback = fallback_root / f"carnivore-{os.getuid()}"
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    fallback.symlink_to(target)
    with pytest.raises(back_route.BackRouteInvalid, match="private directory"):
        back_route.socket_dir(fed, GRANT)
    fallback.unlink()
    fallback.mkdir(mode=0o755)
    fallback.chmod(0o755)
    with pytest.raises(back_route.BackRouteInvalid, match="private directory"):
        back_route.socket_dir(fed, GRANT)
    fallback.chmod(0o700)
    assert back_route.socket_dir(fed, GRANT) == fallback
    other = os.getuid() + 1
    monkeypatch.setattr(back_route.os, "getuid", lambda: other)
    (fallback_root / f"carnivore-{other}").mkdir(mode=0o700)
    with pytest.raises(back_route.BackRouteInvalid, match="private directory"):
        back_route.socket_dir(fed, GRANT)


@pytest.mark.asyncio
async def test_a_failed_link_is_logged_with_the_exception_type_and_message(monkeypatch):
    hub = ll.LinkListener(identity=None, fed_dir=Path("/x"), listener_path="/y", addresses=lambda: [])

    async def boom(reader, writer):
        raise OSError("AF_UNIX path too long")

    monkeypatch.setattr(hub, "_serve", boom)

    class W:
        def close(self):
            pass

    with structlog.testing.capture_logs() as logs:
        assert await hub.serve(None, W()) == ll.NO_HELLO
    rec = next(r for r in logs if r["event"] == "link_connection_failed")
    assert rec["error"] == "OSError" and "AF_UNIX path too long" in rec["detail"]


def test_the_users_own_temp_dir_is_preferred_over_a_shared_tmp_name(tmp_path, fallback_root, monkeypatch):
    fed = _long_fed(tmp_path)
    user_tmp = Path(tempfile.mkdtemp(prefix="ut", dir="/tmp"))
    try:
        user_tmp.chmod(0o700)
        (fallback_root / f"carnivore-{os.getuid()}").mkdir(mode=0o755)
        monkeypatch.setattr(back_route, "_user_temp_dir", lambda: str(user_tmp) + "/")
        assert back_route.socket_dir(fed, GRANT) == user_tmp
        user_tmp.chmod(0o755)
        with pytest.raises(back_route.BackRouteInvalid, match="private directory"):
            back_route.socket_dir(fed, GRANT)
    finally:
        shutil.rmtree(user_tmp, ignore_errors=True)


class _StubGate:

    def full(self): return False
    def enter(self, source): return True
    def track(self, pending, evict): pass
    def untrack(self, pending): pass
    def leave(self, source): pass
    def note_failure(self, source): pass


class _StubListener:
    _ctx = object()
    _gate = _StubGate()


@pytest.mark.asyncio
async def test_a_handshake_cancelled_before_it_ran_still_closes_its_socket():
    loop = asyncio.get_running_loop()
    gate = await ll._TlsGate.open(_StubListener(), loop, "127.0.0.1", 0)
    a, b = socket.socketpair()
    try:
        gate._admit(a, "203.0.113.16")
        (pending,) = gate._pending
        gate._drop(pending)
        for _ in range(3):
            await asyncio.sleep(0)
        assert a.fileno() == -1
    finally:
        b.close()
        gate.close()
        await gate.wait_closed()


@pytest.mark.asyncio
async def test_an_admit_error_is_logged_and_the_accept_loop_keeps_serving(monkeypatch):
    loop = asyncio.get_running_loop()
    gate = await ll._TlsGate.open(_StubListener(), loop, "127.0.0.1", 0)
    port = gate.sockets[0].getsockname()[1]
    seen = []

    def boom(conn, source):
        seen.append(conn)
        raise RuntimeError("admit exploded")

    monkeypatch.setattr(gate, "_admit", boom)
    try:
        for _ in range(2):
            _r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            await asyncio.sleep(0.05)
        assert len(seen) == 2 and all(c.fileno() == -1 for c in seen)
        assert not gate._accepting.done()
    finally:
        gate.close()
        await gate.wait_closed()
