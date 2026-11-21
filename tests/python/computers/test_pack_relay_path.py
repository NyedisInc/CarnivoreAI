
from __future__ import annotations

import asyncio
import json
import os
from typing import Dict

import pytest

from src.core.computers import store
from src.core.computers.link_listener import LinkListener, Member
from src.core.computers.link_transport import TlsInitiatorTransport, _back_path
from src.core.computers.member_listener import Rendezvous
from src.core.computers.member_relay_dial import MemberRelayDialer
from src.core.computers.mux import frames as mf
from src.core.computers.mux.session import MuxSession
from src.core.computers.tls_identity import client_link_ctx
from src.core.federation.peer_client import Route
from src.core.phone_link import frames, tunnel_client as tc
from src.core.phone_link.pack_relay import PACK_ALPN, PackRelay
from tests.python.computers.test_tls_link import GRANT, MAIN_IID, MEMBER_IID, _Client, _stub_listener, _wait, world  # noqa: F401

LINK = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"
RELAY_ID = "abc234"


class FakeRelay:

    def __init__(self, client: tc.TunnelClient) -> None:
        self.client, self.sid, self.writers, self.servers = client, 0, {}, []
        self.pump = asyncio.get_running_loop().create_task(self._pump_out())

    async def listen(self, ip: str) -> int:
        async def handle(reader, writer):
            self.sid += 1
            sid = self.sid
            self.writers[sid] = writer
            await self.client._on_frame(frames.pack(frames.OPEN, sid, json.dumps({"client_ip": ip, "client_port": 4000 + sid, "sni": LINK}).encode()))
            try:
                while chunk := await reader.read(16384):
                    await self.client._on_frame(frames.pack(frames.DATA, sid, chunk))
            except (ConnectionError, OSError):
                pass
            await self.client._on_frame(frames.pack(frames.CLOSE, sid, bytes([frames.REASON_NORMAL])))

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def _pump_out(self) -> None:
        while True:
            kind, sid, payload = frames.unpack(await self.client._out.get())
            writer = self.writers.get(sid)
            if writer is None:
                continue
            if kind == frames.DATA:
                writer.write(payload)
                await writer.drain()
                await self.client._on_frame(frames.pack(frames.WINDOW, sid, frames.window_payload(len(payload))))
            elif kind == frames.CLOSE:
                writer.close()

    async def stop(self) -> None:
        self.pump.cancel()
        await asyncio.gather(self.pump, return_exceptions=True)
        for server in self.servers:
            server.close()
        for writer in self.writers.values():
            writer.close()


async def _closed(reader: asyncio.StreamReader, seconds: float = 3.0) -> bool:
    try:
        return await asyncio.wait_for(reader.read(1), seconds) == b""
    except (ConnectionError, OSError):
        return True


async def _raw_member(world, port: int):
    _root, _dirs, idents = world
    ctx = client_link_ctx(idents["member"], [idents["main"].cert])
    ctx.set_alpn_protocols([PACK_ALPN])
    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=ctx, server_hostname=LINK)
    session = MuxSession(reader, writer, dialer=True)
    await session.start({"v": mf.PROTOCOL_VERSION, "proto": 1, "addresses": [], "listen_port": None})
    return session, await asyncio.wait_for(session.hello(), 5)


@pytest.mark.asyncio
async def test_the_relayed_pinned_link_comes_up_and_strangers_budget_and_old_parsers_behave(world, monkeypatch):
    root, dirs, idents = world
    monkeypatch.setattr(tc, "PEEK_SECONDS", 0.5)
    advertises = {"on": False}
    seen: list = []
    stubs = [await _stub_listener(str(root / "main.sock"), "main", seen), await _stub_listener(str(root / "member.sock"), "member", seen)]
    holder: Dict[str, PackRelay] = {}
    hub = LinkListener(identity=idents["main"], fed_dir=dirs["main"], listener_path=str(root / "main.sock"), addresses=lambda: ["10.1.2.3"],
                       hello_extras=lambda iid: {"relay_id": RELAY_ID} if advertises["on"] else {},
                       app_streams_ok=lambda: not holder["relay"].budget.exhausted)
    relay = holder["relay"] = PackRelay(identity=idents["main"], hub=hub, config_path=root / "config.json", budget_path=root / "budget.json")
    member = Member(MEMBER_IID, GRANT, idents["member"].cert)
    await hub.set_members([member])
    await relay.set_members([member])
    await relay.acceptor.start()
    client = tc.TunnelClient(url="ws://unused", session=None, local_port=lambda: None, streams=relay.table, client_ip_check=lambda ip: ip)
    client._out = asyncio.Queue()
    client.attach_pack(relay)
    fake = FakeRelay(client)
    port_a, port_b = await fake.listen("203.0.113.66"), await fake.listen("198.51.100.7")
    transport = None
    try:
        session, hello = await _raw_member(world, port_b)
        assert set(hello) == {"v", "back_path", "addresses", "link_port"} and _back_path(hello).endswith(".sock")
        await _wait(lambda: hub.relayed() == [MEMBER_IID])
        await session.close()
        await _wait(lambda: not hub.connected())

        stalled_r, stalled_w = await asyncio.open_connection("127.0.0.1", port_a)
        for _ in range(12):
            r, w = await asyncio.open_connection("127.0.0.1", port_a)
            w.write(b"GET / HTTP/1.1\r\n\r\n")
            assert await _closed(r)
            w.close()
        assert await _closed(stalled_r)
        refused_r, refused_w = await asyncio.open_connection("127.0.0.1", port_a)
        assert await _closed(refused_r)
        stalled_w.close(), refused_w.close()

        advertises["on"] = True
        rendezvous, learned = Rendezvous(), []
        main_cert = idents["main"].cert
        main_row = store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=main_cert.der, cert_sha256=main_cert.cert_sha256, link_fid=main_cert.link_fid)

        async def connect(host, ctx):
            assert host == LINK
            return await asyncio.open_connection("127.0.0.1", port_b, ssl=ctx, server_hostname=host)

        dialer = MemberRelayDialer(identity=idents["member"], rendezvous=rendezvous, main=lambda: main_row, relay_host=lambda: LINK,
                                   enabled=lambda: True, linked=lambda: False, connect=connect, unlinked_after=0.0)
        transport = TlsInitiatorTransport(
            install_id=MEMBER_IID, host_key="peer-main", rendezvous=rendezvous, get_link=lambda: main_row, listener_path=str(root / "member.sock"),
            make_client=_Client, addresses=lambda: ["member.local"], listen_port=lambda: None,
            hello_extras=lambda: {"device_id": "dev234"}, on_relay_id=learned.append, control_dir=root)
        dialer.tick()
        await asyncio.wait_for(transport.settle(), 5)
        assert rendezvous._slot_relay is True
        route = await transport.establish()
        assert route == Route("unix", transport.out_path) and hub.relayed() == [MEMBER_IID] and learned == [RELAY_ID]
        assert (await _Client(route).request("GET", "/api/v1/federation/hello")).json() == {"who": "main", "len": 0}
        back_path = json.loads(next(s for s in seen if s[1] == "/federation/link")[2])["path"]

        relay.budget.limit = relay.budget.used + 1
        relay.budget.add(10)
        assert relay.budget.exhausted
        for client_route in (route, Route("unix", back_path)):
            with pytest.raises(Exception):
                await asyncio.wait_for(_Client(client_route).request("GET", "/api/v1/federation/hello"), 3)
        assert hub.connected() == [MEMBER_IID]
        before = transport._session._last_rx
        transport._session._control(mf.PING, 0, os.urandom(8))
        await _wait(lambda: transport._session._last_rx > before)

        async def accept(reader, writer):
            await reader.read()

        direct = await asyncio.start_server(accept, "127.0.0.1", 0)
        dr, dw = await asyncio.open_connection("127.0.0.1", direct.sockets[0].getsockname()[1])
        rendezvous.offer(dr, dw)
        await _wait(lambda: not hub.connected())
        dw.close()
        direct.close()
    finally:
        if transport is not None:
            await transport.close()
        await fake.stop()
        await relay.stop()
        await hub.stop()
        for stub in stubs:
            stub.close()
