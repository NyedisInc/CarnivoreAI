
import asyncio
import os
import ssl
import stat
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, Request

from src.api import auth as auth_module
from src.api import peer_auth
from src.config.relay import RelayConfig
from src.core.federation import peer_token
from src.core.phone_link import acme, boot, certs, frames, manager as mgr_mod
from src.core.phone_link import tunnel_client as tc
from src.core.phone_link.gate import LinkStream, StreamTable
from src.core.relay_identity import device_key as dk
from tests.phone_link.test_acme import BASE, HOST, FakeCa, FakeDns, make_client, manager as cert_manager
from tests.phone_link.test_routes_and_manager import Manager, make_app



def _down_client():
    def boom(request):
        raise httpx.ConnectError("network down")

    http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    return acme.AcmeClient(directory_url=f"{BASE}/dir", account_key=acme.new_ec_key(), dns=FakeDns(), http=http)


@pytest.mark.asyncio
async def test_every_network_failure_is_an_acme_error():
    with pytest.raises(acme.AcmeError):
        await _down_client().obtain(HOST, acme.new_ec_key())
    client = _down_client()
    client._directory = {"newNonce": f"{BASE}/nonce"}
    with pytest.raises(acme.AcmeError):
        await client._fresh_nonce()


@pytest.mark.asyncio
async def test_a_malformed_directory_is_an_acme_error_not_a_keyerror():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"no": "urls"})))
    client = acme.AcmeClient(directory_url=f"{BASE}/dir", account_key=acme.new_ec_key(), dns=FakeDns(), http=http)
    with pytest.raises(acme.AcmeError):
        await client.obtain(HOST, acme.new_ec_key())


@pytest.mark.asyncio
async def test_the_app_boots_with_the_network_down_and_the_link_enabled(tmp_path):
    app = FastAPI()
    cfg = RelayConfig(control_url="http://127.0.0.1:1", link_tunnel_url="ws://127.0.0.1:1/t",
                      link_acme_directory="http://127.0.0.1:1/dir")
    with mock.patch.object(mgr_mod.PhoneLinkManager, "_start", autospec=True) as start:
        async def dead_network(self):
            try:
                raise httpx.ConnectError("down")
            except httpx.HTTPError as exc:
                self.error = type(exc).__name__

        start.side_effect = dead_network
        boot.start(app, cfg, tmp_path, tmp_path / "c.db", "1.0.0")
        manager = app.state.phone_link
        manager.pairing.set_enabled(True)
        manager.pairing.open_window()
        await asyncio.wait_for(manager._boot_task, 5)
        assert manager.error == "ConnectError"
        await boot.stop(app)


@pytest.mark.asyncio
async def test_a_crashing_boot_reconcile_is_contained(tmp_path):
    app = FastAPI()
    with mock.patch.object(mgr_mod.PhoneLinkManager, "reconcile", side_effect=KeyError("x")):
        boot.start(app, RelayConfig(), tmp_path, tmp_path / "c.db", "1")
        await asyncio.wait_for(app.state.phone_link._boot_task, 5)
        assert app.state.phone_link.error == "KeyError"
        await boot.stop(app)


def test_boot_leaves_no_manager_when_the_relay_is_off(tmp_path):
    app = FastAPI()
    boot.start(app, RelayConfig(enabled=False), tmp_path, tmp_path / "c.db", "1")
    assert app.state.phone_link is None



@pytest.mark.asyncio
async def test_the_renewal_loop_survives_any_exception_and_retries_after_retry_seconds(tmp_path, monkeypatch):
    m = cert_manager(tmp_path, FakeCa(), FakeDns())
    m.hostname = HOST
    calls, sleeps = [], []
    monkeypatch.setattr(m, "needs_renewal", lambda h: True)

    async def renew(h):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("anything at all")
        raise asyncio.CancelledError

    monkeypatch.setattr(m, "renew", renew)
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        sleeps.append(s)
        await real_sleep(0)

    monkeypatch.setattr(certs.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await m._renew_loop()
    assert len(calls) == 2 and sleeps == [certs.CHECK_INTERVAL_SECONDS, certs.RETRY_SECONDS]


@pytest.mark.asyncio
async def test_ensure_serves_a_still_valid_stored_cert_when_renewal_fails(tmp_path):
    ca, dns = FakeCa(days=90), FakeDns()
    await cert_manager(tmp_path, ca, dns).ensure(HOST)
    later = datetime.now(timezone.utc) + timedelta(days=70)
    m = cert_manager(tmp_path, FakeCa(), dns, clock=lambda: later)

    async def failing(hostname, key):
        raise acme.AcmeError("the CA could not be reached")

    m._obtain = failing
    assert isinstance(await m.ensure(HOST), ssl.SSLContext)
    expired = datetime.now(timezone.utc) + timedelta(days=100)
    m2 = cert_manager(tmp_path, FakeCa(), dns, clock=lambda: expired)
    m2._obtain = failing
    with pytest.raises(acme.AcmeError):
        await m2.ensure(HOST)


@pytest.mark.asyncio
async def test_the_context_reloads_on_the_event_loop_thread(tmp_path):
    m = cert_manager(tmp_path, FakeCa(), FakeDns())
    await m.ensure(HOST)
    threads = []
    real = m.context
    m.context = lambda: (threads.append(threading.current_thread()), real())[1]
    await m.renew(HOST)
    assert threads == [threading.current_thread()]


def test_write_private_is_excl_0600_and_leaves_no_temp(tmp_path):
    target = tmp_path / "k"
    certs.write_private(target, b"one")
    certs.write_private(target, b"two")
    assert target.read_bytes() == b"two" and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["k"]



@pytest.mark.asyncio
async def test_a_failed_start_then_a_retry_still_stops_at_the_window_expiry(tmp_path):
    class Flaky(Manager):
        attempts = 0

        async def _start(self):
            Flaky.attempts += 1
            if Flaky.attempts == 1:
                self.error = "AcmeError"
                self._reconcile_later(0.05)
                return
            await super()._start()

    m = Flaky(app=None, config=RelayConfig(), state_dir=tmp_path, db_path=tmp_path / "c.db", version="1")
    m.pairing.set_enabled(True)
    with mock.patch.object(mgr_mod, "WINDOW_SECONDS", 0.3):
        with mock.patch("src.core.phone_link.pairing.WINDOW_SECONDS", 0.3):
            await m.open_window()
            await asyncio.sleep(0.15)
            assert m.status()["running"]
            await asyncio.sleep(1.4)
            assert not m.status()["running"] and m.stopped >= 1
    m.pairing.close()



def _forged_request(via_link):
    scope = {"type": "http", "client": ("203.0.113.9", 4000), "headers": [(b"x-forwarded-for", b"1.2.3.4")],
             "method": "GET", "path": "/", "query_string": b""}
    if via_link:
        scope["via_link"] = True
    return Request(scope)


def test_forged_xff_never_picks_the_limiter_key_on_the_link(monkeypatch):
    cfg = SimpleNamespace(auth_rate_limits=SimpleNamespace(trust_proxy_headers=True))
    monkeypatch.setattr(type(auth_module.settings), "load_auth_config", lambda self: cfg)
    assert auth_module._rate_limit_key(_forged_request(False)) == "1.2.3.4"
    assert auth_module._rate_limit_key(_forged_request(True)) == "203.0.113.9"


def _peer_jwt():
    return jwt.encode({"typ": peer_token.PEER_TYP}, "k", algorithm="HS256")


@pytest.mark.asyncio
async def test_a_peer_token_is_refused_over_the_link_and_ws_handshake_closes():
    app = FastAPI()
    dep = peer_auth.require_peer("sessions")

    @app.get("/x")
    async def x(_=Depends(dep)):
        return {"ok": 1}

    async def tag(scope, receive, send):
        scope["via_link"] = True
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tag), base_url="http://t") as c:
        r = await c.get("/x", headers={"authorization": f"Bearer {_peer_jwt()}"})
    assert r.status_code == 403
    from src.api import peer_ws_auth
    ws = mock.MagicMock()
    ws.headers = {"sec-websocket-protocol": f"{peer_ws_auth.SUBPROTOCOL_MARKER}, {_peer_jwt()}"}
    ws.scope = {"via_link": True}
    ws.close = mock.AsyncMock()
    with mock.patch.object(peer_auth, "_authorize_peer", side_effect=AssertionError("must not verify")):
        assert await peer_ws_auth.try_peer(ws) is False
    ws.close.assert_awaited_once()



def test_a_device_key_file_is_ignored_outside_a_test_slot(tmp_path, monkeypatch):
    monkeypatch.delenv(dk.TEST_SLOT_ENV, raising=False)
    assert dk.key_loader_for(str(tmp_path / "k")) is dk.load_or_create
    monkeypatch.setenv(dk.TEST_SLOT_ENV, "/slot/.env")
    assert dk.key_loader_for(str(tmp_path / "k")) is not dk.load_or_create


def test_a_key_file_must_be_absolute_private_and_ours(tmp_path):
    path = tmp_path / "k"
    dk.load_or_create_file("i", str(path))
    os.chmod(path, 0o640)
    with pytest.raises(dk.DeviceKeyUnavailable):
        dk.load_or_create_file("i", str(path))
    os.chmod(path, 0o600)
    dk.load_or_create_file("i", str(path))
    with pytest.raises(dk.DeviceKeyUnavailable):
        dk.load_or_create_file("i", "relative/key")



@pytest.mark.parametrize("ip,ok", [("8.8.8.8", True), ("2001:4860:4860::8888", True), ("127.0.0.1", False),
                                   ("::1", False), ("10.1.2.3", False), ("192.168.0.4", False),
                                   ("169.254.1.1", False), ("0.0.0.0", False), ("::", False),
                                   ("::ffff:127.0.0.1", False), ("fe80::1", False), ("junk", False)])
def test_only_public_client_addresses_are_accepted(ip, ok):
    assert (tc.public_client_ip(ip) is not None) is ok


def _client():
    c = tc.TunnelClient(url="ws://x", session=mock.MagicMock(), local_port=lambda: 1, streams=StreamTable())
    c._out = asyncio.Queue()
    return c


def _stream(sid=1):
    info = LinkStream(stream_id=sid, client_ip="203.0.113.9", client_port=1)
    writer = mock.MagicMock()
    return tc._Stream(sid, info, mock.MagicMock(), writer, 40000 + sid)


def _closes(c):
    out = []
    while not c._out.empty():
        kind, sid, payload = frames.unpack(c._out.get_nowait())
        out.append((kind, sid, payload))
    return out


@pytest.mark.asyncio
async def test_data_beyond_the_granted_credit_ends_the_stream():
    c = _client()
    s = _stream()
    c._streams[1] = s
    await c._on_frame(frames.pack(frames.DATA, 1, b"x" * frames.MAX_PAYLOAD))
    assert s.recv_credit == frames.INITIAL_WINDOW - frames.MAX_PAYLOAD and 1 in c._streams
    for _ in range(3):
        await c._on_frame(frames.pack(frames.DATA, 1, b"x" * frames.MAX_PAYLOAD))
    assert 1 in c._streams and s.recv_credit == 0
    await c._on_frame(frames.pack(frames.DATA, 1, b"y"))
    assert 1 not in c._streams
    assert _closes(c)[-1] == (frames.CLOSE, 1, bytes([frames.REASON_ERROR]))


@pytest.mark.asyncio
async def test_the_relay_cannot_open_more_than_64_streams_or_a_loopback_phone():
    c = _client()
    for n in range(tc.MAX_STREAMS):
        c._streams[n + 100] = _stream(n + 100)
    await c._on_frame(frames.pack(frames.OPEN, 7, b'{"client_ip": "8.8.8.8", "client_port": 5}'))
    assert _closes(c) == [(frames.CLOSE, 7, bytes([frames.REASON_LIMIT]))]
    c._streams.clear()
    await c._on_frame(frames.pack(frames.OPEN, 8, b'{"client_ip": "127.0.0.1", "client_port": 5}'))
    assert _closes(c) == [(frames.CLOSE, 8, bytes([frames.REASON_ERROR]))]


@pytest.mark.asyncio
async def test_small_reads_coalesce_so_a_full_credit_is_at_most_64_frames():
    c = _client()
    s = _stream()
    s.reader = asyncio.StreamReader()
    total = frames.INITIAL_WINDOW

    async def feed():
        for _ in range(total // 64):
            s.reader.feed_data(b"a" * 64)
            await asyncio.sleep(0)
        s.reader.feed_eof()

    feeder = asyncio.create_task(feed())
    count = got = 0
    while got < total:
        data = await c._read_coalesced(s)
        if not data:
            break
        count += 1
        got += len(data)
        s.credit = frames.INITIAL_WINDOW
    await feeder
    assert got == total and count <= 64


@pytest.mark.asyncio
async def test_the_reauth_loop_restarts_after_an_error():
    c = _client()
    calls = []

    async def loop():
        calls.append(1)
        if len(calls) == 1:
            raise KeyError("boom")
        raise asyncio.CancelledError

    async def sleep(s):
        return None

    c._reauth_loop, c._sleep = loop, sleep
    with pytest.raises(asyncio.CancelledError):
        await c._reauth_supervised()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_the_real_start_with_the_network_down_ends_as_a_named_error(tmp_path, monkeypatch):
    monkeypatch.setenv(dk.TEST_SLOT_ENV, "/slot/.env")
    app = FastAPI()
    cfg = RelayConfig(control_url="http://127.0.0.1:1", link_tunnel_url="ws://127.0.0.1:1/t",
                      link_acme_directory="http://127.0.0.1:1/dir", device_key_file=str(tmp_path / "dev.key"))
    boot.start(app, cfg, tmp_path, tmp_path / "c.db", "1.0.0")
    manager = app.state.phone_link
    manager.pairing.set_enabled(True)
    manager.pairing.open_window()
    await asyncio.wait_for(manager._boot_task, 20)
    assert manager.error and not manager.status()["running"]
    await boot.stop(app)



def test_a_garbage_phone_link_db_does_not_stop_the_boot(tmp_path):
    from src.config.relay import RelayConfig
    from src.core.phone_link import boot

    (tmp_path / "phone_link.db").write_bytes(b"this is not a sqlite file" * 100)
    app = FastAPI()
    boot.start(app, RelayConfig(), tmp_path, tmp_path / "c.db", "1.0.0")
    assert app.state.phone_link is None


def test_the_miss_table_sweeps_expired_addresses_and_is_capped(tmp_path):
    from src.core.phone_link import pairing

    now = [1000.0]
    store = pairing.PairingStore(path=tmp_path / "p.db", clock=lambda: now[0])
    store.open_window()
    for i in range(30):
        store.claim_code("WRONGONE", f"198.51.100.{i}")
    assert len(store._misses) == 30
    now[0] += pairing.IP_MISS_INTERVAL_SECONDS + 1
    store.claim_code("WRONGONE", "203.0.113.1")
    assert list(store._misses) == ["203.0.113.1"]
    store.close()


def test_the_miss_table_never_exceeds_its_cap(tmp_path, monkeypatch):
    from src.core.phone_link import pairing

    monkeypatch.setattr(pairing, "IP_TABLE_MAX", 5)
    now = [1000.0]
    store = pairing.PairingStore(path=tmp_path / "p.db", clock=lambda: now[0])
    for i in range(12):
        now[0] += 1
        store.claim_code("WRONGONE", f"198.51.100.{i}")
    assert len(store._misses) == 5 and "198.51.100.11" in store._misses and "198.51.100.0" not in store._misses
    store.close()


@pytest.mark.asyncio
async def test_the_route_guard_refuses_a_peer_token_over_the_link():
    from starlette.requests import HTTPConnection
    from fastapi import HTTPException
    from src.api import peer_route_guard

    conn = HTTPConnection({"type": "http", "via_link": True, "headers": [], "path": "/", "query_string": b""})
    with mock.patch.object(peer_auth, "_authorize_peer", side_effect=AssertionError("must not verify")):
        with pytest.raises(HTTPException) as exc:
            await peer_route_guard._authenticate(conn, _peer_jwt())
    assert exc.value.status_code == 403
