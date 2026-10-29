
import asyncio
import json

import pytest

from src.core.phone_link import frames, gate as g
from src.core.phone_link import tunnel_client as tc
from tests.phone_link.test_custom_domain_tls import DOMAIN, client_hello_bytes

LINK = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"


class Routing:

    def __init__(self, challenge_port=None, ready=True):
        self.port, self.is_ready = challenge_port, ready

    def name(self):
        return DOMAIN

    def ready(self):
        return self.is_ready

    def challenge_port(self):
        return self.port


class Sink:

    def __init__(self):
        self.data, self.connections = b"", 0

    async def start(self):
        async def handle(reader, writer):
            self.connections += 1
            while chunk := await reader.read(65536):
                self.data += chunk
            writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


async def rig(routing):
    app, challenge = await Sink().start(), await Sink().start()
    routing.port = challenge.port if routing.port == "open" else routing.port
    table = g.StreamTable()
    client = tc.TunnelClient(url="ws://unused", session=None, local_port=lambda: app.port, streams=table,
                             custom=routing, client_ip_check=lambda ip: ip)
    client._out = asyncio.Queue()
    return client, table, app, challenge


def open_frame(sid, sni):
    return frames.pack(frames.OPEN, sid, json.dumps({"client_ip": "203.0.113.9", "client_port": 4000 + sid, "sni": sni}).encode())


def data_frame(sid, payload):
    return frames.pack(frames.DATA, sid, payload)


async def settle(sink, want, tries=100):
    for _ in range(tries):
        if len(sink.data) >= want:
            return
        await asyncio.sleep(0.01)


def queued(client):
    out = []
    while not client._out.empty():
        out.append(frames.unpack(client._out.get_nowait())[0])
    return out


async def finish(client, *sinks):
    for stream in list(client._streams.values()):
        client._end(stream, frames.REASON_NORMAL, notify=False)
    for sink in sinks:
        await sink.stop()


@pytest.mark.asyncio
async def test_acme_tls_1_goes_to_the_challenge_responder_and_nothing_reaches_the_app():
    client, table, app, challenge = await rig(Routing("open"))
    hello = client_hello_bytes(DOMAIN, ["acme-tls/1"])
    await client._on_frame(open_frame(1, DOMAIN))
    await client._on_frame(data_frame(1, hello))
    await settle(challenge, len(hello))
    assert challenge.data == hello and app.connections == 0
    await finish(client, app, challenge)


@pytest.mark.asyncio
async def test_any_other_alpn_goes_to_the_app_listener_and_is_registered_for_the_gate():
    client, table, app, challenge = await rig(Routing("open"))
    hello = client_hello_bytes(DOMAIN, ["http/1.1"])
    await client._on_frame(open_frame(2, DOMAIN))
    await client._on_frame(data_frame(2, hello[:7]))
    await client._on_frame(data_frame(2, hello[7:]))
    await settle(app, len(hello))
    assert app.data == hello and challenge.connections == 0
    (stream,) = client._streams.values()
    assert table.lookup(stream.port) is stream.info and stream.info.sni == DOMAIN
    await finish(client, app, challenge)


@pytest.mark.asyncio
async def test_a_challenge_with_no_open_authorization_closes_the_stream():
    client, table, app, challenge = await rig(Routing(None))
    await client._on_frame(open_frame(3, DOMAIN))
    await client._on_frame(data_frame(3, client_hello_bytes(DOMAIN, ["acme-tls/1"])))
    await asyncio.sleep(0.1)
    assert 3 not in client._streams and frames.CLOSE in queued(client)
    assert app.connections == 0 and challenge.connections == 0
    await finish(client, app, challenge)


@pytest.mark.asyncio
async def test_an_app_stream_without_a_valid_custom_certificate_is_closed():
    client, table, app, challenge = await rig(Routing("open", ready=False))
    await client._on_frame(open_frame(4, DOMAIN))
    await client._on_frame(data_frame(4, client_hello_bytes(DOMAIN, ["http/1.1"])))
    await asyncio.sleep(0.1)
    assert 4 not in client._streams and frames.CLOSE in queued(client) and app.connections == 0
    await finish(client, app, challenge)


@pytest.mark.asyncio
async def test_a_hello_naming_another_host_than_the_open_frame_is_closed():
    client, table, app, challenge = await rig(Routing("open"))
    await client._on_frame(open_frame(5, DOMAIN))
    await client._on_frame(data_frame(5, client_hello_bytes("other.example.com", ["http/1.1"])))
    await asyncio.sleep(0.1)
    assert 5 not in client._streams and app.connections == 0
    await finish(client, app, challenge)


@pytest.mark.asyncio
async def test_garbage_on_a_custom_stream_is_closed():
    client, table, app, challenge = await rig(Routing("open"))
    await client._on_frame(open_frame(6, DOMAIN))
    await client._on_frame(data_frame(6, b"GET / HTTP/1.1\r\n\r\n"))
    await asyncio.sleep(0.1)
    assert 6 not in client._streams and app.connections == 0
    await finish(client, app, challenge)


@pytest.mark.asyncio
async def test_the_link_name_still_connects_at_once_without_inspecting_bytes():
    client, table, app, challenge = await rig(Routing("open"))
    await client._on_frame(open_frame(7, LINK))
    for _ in range(100):
        if app.connections:
            break
        await asyncio.sleep(0.01)
    assert app.connections == 1 and challenge.connections == 0
    (stream,) = client._streams.values()
    assert stream.info.sni == LINK
    await finish(client, app, challenge)
