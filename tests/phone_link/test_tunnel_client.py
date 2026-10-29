
import asyncio
import json
import threading
import time
from contextlib import contextmanager

import pytest
import pytest_asyncio
import uvicorn

from src.core.phone_link import frames, gate as g
from src.core.phone_link import tunnel_client as tc
from src.core.relay_identity.session import REFRESH_MARGIN_SECONDS, RelayAuthError, RelayToken
from relay.app import create_app
from tests.relay_link.support import DOMAIN, Phone, client_hello, host_for
from tests.relay_v2_support import Device, Issuer, _payload
from tests.test_relay_sockets import RecordingFactory, build_settings
from src.core.relay_identity import device_key as dk


class FakeSession:

    def __init__(self, device, issuer, ttl=900):
        self.device, self.issuer, self.ttl, self.tokens = device, issuer, ttl, 0
        self._token = None

    async def token(self):
        if self._token is None or self._token.exp - REFRESH_MARGIN_SECONDS <= time.time():
            raw = self.issuer.token(self.device, exp=int(time.time()) + self.ttl)
            self._token = RelayToken(raw, json.loads(_payload(raw))["jti"], json.loads(_payload(raw))["exp"])
            self.tokens += 1
        return self._token

    def drop_token(self):
        self._token = None

    def _sign(self, message):
        return dk.b64url(self.device.key.sign(message))

    async def pop_headers(self, token, *, tunnel=False):
        assert tunnel
        ts = int(time.time())
        return {"Authorization": f"Bearer {token.token}", "Carnivore-Relay-Client": "1.8.1",
                "Carnivore-Relay-PoP-Ts": str(ts),
                "Carnivore-Relay-PoP": self._sign(dk.link_tunnel_pop_message(token.jti, ts))}

    async def tunnel_reauth_payload(self, token):
        ts = int(time.time())
        return {"token": token.token, "pop_ts": ts, "pop": self._sign(dk.link_tunnel_pop_message(token.jti, ts))}


@contextmanager
def live_relay(issuer):
    app = create_app(build_settings(issuer_keys=issuer.pins, link_enabled=True, link_port=0),
                     redactor_factory=RecordingFactory())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        yield (app, server.servers[0].sockets[0].getsockname()[1],
               app.state.link.server.sockets[0].getsockname()[1])
    finally:
        server.should_exit = True
        thread.join(10)


class Rig:

    def __init__(self, app, http_port, router_port, session, device):
        self.app, self.router_port, self.device, self.session = app, router_port, device, session
        self.table = g.StreamTable()
        self.seen = []
        self.trust_all = False
        self.client = None
        self.url = f"ws://127.0.0.1:{http_port}/v1/link/tunnel"

    async def start(self):
        async def echo(reader, writer):
            port = writer.get_extra_info("peername")[1]
            info = self.table.lookup(port)
            self.seen.append((port, info))
            if info is not None and self.trust_all:
                info.request_seen = True
                self.client.trust(info.stream_id)
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            except ConnectionError:
                pass
            writer.close()

        self.server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.client = tc.TunnelClient(url=self.url, session=self.session, local_port=lambda: port,
                                      streams=self.table, client_ip_check=lambda ip: ip)
        self.client.start()
        for _ in range(300):
            if self.app.state.link.online(self.device.device_id) is not None:
                return
            await asyncio.sleep(0.02)
        raise AssertionError("the tunnel never registered")

    async def stop(self):
        await self.client.stop()
        self.server.close()

    def phone(self):
        return Phone(self.router_port)


@pytest_asyncio.fixture
async def rig():
    issuer, device = Issuer(), Device()
    session = FakeSession(device, issuer)
    with live_relay(issuer) as (app, http_port, router_port):
        r = Rig(app, http_port, router_port, session, device)
        await r.start()
        yield r
        await r.stop()


def read_all(phone, count):
    return phone.recv_exact(count)


@pytest.mark.asyncio
async def test_bytes_round_trip_through_both_windows_and_the_real_address_is_recorded(rig):
    rig.trust_all = True
    hello = client_hello(host_for(rig.device))
    payload = bytes(range(256)) * 2400
    phone = await asyncio.to_thread(rig.phone)
    phone_port = phone.sock.getsockname()[1]
    phone.send(hello)
    sender = asyncio.to_thread(phone.send, payload)
    got = await asyncio.gather(sender, asyncio.to_thread(read_all, phone, len(hello) + len(payload)))
    assert got[1] == hello + payload
    (_, info), = rig.seen
    assert (info.client_ip, info.client_port) == ("127.0.0.1", phone_port)
    assert rig.app.state.link.online(rig.device.device_id) is not None
    assert rig.client.connected


@pytest.mark.asyncio
async def test_trust_reaches_the_relay_only_for_a_stream_the_gate_vouched_for(rig):
    tunnel = rig.app.state.link.online(rig.device.device_id)
    phone = await asyncio.to_thread(rig.phone)
    phone.send(client_hello(host_for(rig.device)))
    await asyncio.sleep(0.5)
    assert not tunnel.meter.is_trusted("127.0.0.1")
    (_, info), = rig.seen
    rig.client.trust(info.stream_id)
    for _ in range(100):
        if tunnel.meter.is_trusted("127.0.0.1"):
            break
        await asyncio.sleep(0.02)
    assert tunnel.meter.is_trusted("127.0.0.1")


@pytest.mark.asyncio
async def test_a_stream_with_no_complete_request_is_closed_at_the_pre_auth_deadline(rig, monkeypatch):
    monkeypatch.setattr(tc, "PRE_AUTH_SECONDS", 0.4)
    hello = client_hello(host_for(rig.device))
    phone = await asyncio.to_thread(rig.phone)
    phone.send(hello)
    assert await asyncio.to_thread(phone.recv_exact, len(hello)) == hello
    assert await asyncio.to_thread(phone.is_closed) is True
    assert rig.table.lookup(rig.seen[0][0]) is None


@pytest.mark.asyncio
async def test_a_stream_that_saw_a_request_is_not_closed_and_the_table_is_cleaned_on_close(rig, monkeypatch):
    monkeypatch.setattr(tc, "PRE_AUTH_SECONDS", 0.3)
    rig.trust_all = True
    hello = client_hello(host_for(rig.device))
    phone = await asyncio.to_thread(rig.phone)
    phone.send(hello)
    await asyncio.to_thread(phone.recv_exact, len(hello))
    await asyncio.sleep(0.8)
    phone.send(b"still here")
    assert await asyncio.to_thread(phone.recv_exact, 10) == b"still here"
    port = rig.seen[0][0]
    phone.close()
    for _ in range(100):
        if rig.table.lookup(port) is None:
            break
        await asyncio.sleep(0.02)
    assert rig.table.lookup(port) is None


@pytest.mark.asyncio
async def test_close_device_ends_only_that_devices_streams(rig):
    rig.trust_all = True
    phone = await asyncio.to_thread(rig.phone)
    hello = client_hello(host_for(rig.device))
    phone.send(hello)
    await asyncio.to_thread(phone.recv_exact, len(hello))
    info = rig.seen[0][1]
    info.device = "dev-a"
    rig.client.close_device("dev-b")
    await asyncio.sleep(0.2)
    assert rig.table.lookup(rig.seen[0][0]) is info
    rig.client.close_device("dev-a")
    assert await asyncio.to_thread(phone.is_closed) is True


@pytest.mark.asyncio
async def test_reauth_moves_the_relays_deadline_before_the_token_expires():
    issuer, device = Issuer(), Device()
    session = FakeSession(device, issuer, ttl=REFRESH_MARGIN_SECONDS + 2)
    with live_relay(issuer) as (app, http_port, router_port):
        r = Rig(app, http_port, router_port, session, device)
        await r.start()
        try:
            tunnel = app.state.link.online(device.device_id)
            first = tunnel.principal.deadline
            for _ in range(150):
                if tunnel.principal.deadline > first:
                    break
                await asyncio.sleep(0.1)
            assert tunnel.principal.deadline > first and session.tokens >= 2
            assert app.state.link.online(device.device_id) is tunnel
        finally:
            await r.stop()


@pytest.mark.asyncio
async def test_reconnects_back_off_with_jitter_and_a_terminal_refusal_stops_for_good():
    delays = []

    async def sleep(seconds):
        delays.append(seconds)
        if len(delays) >= 4:
            raise asyncio.CancelledError

    async def refuse(*args, **kwargs):
        raise OSError("down")

    session = FakeSession(Device(), Issuer())
    client = tc.TunnelClient(url="ws://x/y", session=session, local_port=lambda: 1,
                             streams=g.StreamTable(), connect=refuse, sleep=sleep)
    client.start()
    await asyncio.gather(client._task, return_exceptions=True)
    assert delays[0] >= 2.0 and delays[1] >= 4.0 and delays[2] >= 8.0 and len(set(delays)) == 4

    class Revoked(FakeSession):
        async def token(self):
            raise RelayAuthError("revoked")

    stopped = tc.TunnelClient(url="ws://x/y", session=Revoked(Device(), Issuer()), local_port=lambda: 1,
                              streams=g.StreamTable(), connect=refuse)
    stopped.start()
    await asyncio.wait_for(stopped._task, 2)
    assert stopped.status == "revoked"


@pytest.mark.asyncio
async def test_the_writer_never_exceeds_the_frame_rate(monkeypatch):
    monkeypatch.setattr(tc, "MAX_FRAMES_PER_SECOND", 40)
    sent = []

    class Ws:
        async def send(self, frame):
            sent.append(time.monotonic())

    client = tc.TunnelClient(url="ws://x", session=None, local_port=lambda: 1, streams=g.StreamTable())
    client._out = asyncio.Queue()
    for _ in range(100):
        client._out.put_nowait(frames.pack(frames.WINDOW, 1, frames.window_payload(1)))
    task = asyncio.create_task(client._writer(Ws()))
    await asyncio.sleep(1.5)
    task.cancel()
    assert 40 <= len(sent) <= 90
    assert max(sum(1 for t in sent if start <= t < start + 1.0) for start in sent) <= 40
