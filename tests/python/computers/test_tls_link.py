
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytest

from src.core.computers import link_listener as ll
from src.core.computers import store
from src.core.computers.link_dialer import LOCAL_NETWORK_BLOCKED, LinkDialer
from src.core.computers.link_listener import LinkListener, Member
from src.core.computers.link_transport import TlsInitiatorTransport, tls_transport_factory
from src.core.computers.member_listener import MemberListener, Rendezvous
from src.core.computers.tls_identity import ensure_link_identity
from src.core.federation import grants, pair_driver, peer_hosts, peer_http, peer_links
from src.core.federation.peer_client import Route
from src.core.federation.peer_link import LinkDown
from src.core.relay_identity.device_key import DeviceKey
from tests.python.federation.test_pairing_routes import macs  # noqa: F401

MAIN_IID, MEMBER_IID, GRANT = "main-install-aaaa", "member-install-bbbb", "g1"


@pytest.fixture()
def world():
    root = Path(tempfile.mkdtemp(prefix="tl"))
    dirs = {}
    for name in ("main", "member", "evil"):
        d = root / name
        d.mkdir(mode=0o700)
        dirs[name] = d
    seeds = {"main": 1, "member": 2, "evil": 3}
    ids = {"main": MAIN_IID, "member": MEMBER_IID, "evil": "evil-install-cccc"}
    idents = {n: ensure_link_identity(DeviceKey.from_seed(bytes([seeds[n]]) * 32), ids[n], dirs[n]) for n in dirs}
    yield root, dirs, idents
    shutil.rmtree(root, ignore_errors=True)


async def _stub_listener(path: str, name: str, seen: list, delay: float = 0.0):
    async def handle(r, w):
        try:
            head = (await r.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            hdrs = {ln.split(":", 1)[0].lower(): ln.split(":", 1)[1].strip() for ln in head[1:] if ":" in ln}
            body = await r.readexactly(int(hdrs.get("content-length", "0")))
            seen.append((name, head[0].split()[1], body))
            data = json.dumps({"who": name, "len": len(body)}).encode()
            w.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: %d\r\n\r\n" % len(data) + data)
            await w.drain()
        finally:
            w.close()
    return await asyncio.start_unix_server(handle, path=path)


class _Client:

    def __init__(self, route: Route) -> None:
        self.route = route

    async def request(self, method: str, path: str, json=None, **kw):
        reader, writer = await peer_http.open_connection(self.route.kind, self.route.target)
        try:
            return await peer_http.exchange(reader, writer, method, path, body=json, content=kw.get("content"))
        finally:
            writer.close()


@dataclass
class Up:

    hub: LinkListener
    dialer: LinkDialer
    listener: MemberListener
    rendezvous: Rendezvous
    transport: TlsInitiatorTransport
    seen: list
    linked: List[str]
    hellos: list
    first: list
    stubs: list


def _rows(idents, port: int, *, main_pin=None, member_pin=None):
    mc, nc = member_pin or idents["member"].cert, main_pin or idents["main"].cert
    member_row = store.LinkRow(MEMBER_IID, "member", "tls", "", cert_der=mc.der, cert_sha256=mc.cert_sha256, link_fid=mc.link_fid,
                               addresses=("127.0.0.1",), link_port=port)
    main_row = store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=nc.der, cert_sha256=nc.cert_sha256, link_fid=nc.link_fid)
    return member_row, main_row


async def _up(world, *, dialer_ident="main", main_pin=None, member_pin=None, dial=True, backoff=lambda _a: 0) -> Up:
    root, dirs, idents = world
    seen: list = []
    stubs = [await _stub_listener(str(root / "main.sock"), "main", seen), await _stub_listener(str(root / "member.sock"), "member", seen)]
    rendezvous = Rendezvous()
    listener = MemberListener(identity=idents["member"], rendezvous=rendezvous, host="127.0.0.1")
    assert await listener.bind(0)
    await listener.set_pins([main_pin or idents["main"].cert])
    member_row, main_row = _rows(idents, listener.port, main_pin=main_pin, member_pin=member_pin)
    cache = store.LinkCache()
    cache.replace([member_row])
    linked: List[str] = []
    hellos: list = []
    holder: dict = {}
    hub = LinkListener(identity=idents["main"], fed_dir=dirs["main"], listener_path=str(root / "main.sock"), addresses=lambda: ["main.local", "198.51.100.15"],
                       on_link=lambda iid: _record(linked, iid), on_member_hello=lambda iid, a, p: _record(hellos, (iid, a, p)),
                       on_members=lambda members: holder["dialer"].set_members(members))
    dialer = holder["dialer"] = LinkDialer(identity=idents[dialer_ident], hub=hub, rows=cache.get, backoff=backoff, stagger=0.05)
    first: list = []
    transport = TlsInitiatorTransport(
        install_id=MEMBER_IID, host_key="peer-main", rendezvous=rendezvous, get_link=lambda: main_row, listener_path=str(root / "member.sock"),
        make_client=_Client, addresses=lambda: ["member.local"], listen_port=lambda: listener.port,
        on_first_link=lambda: _record(first, "first"), control_dir=root)
    if dial:
        await hub.set_members([Member(MEMBER_IID, GRANT, idents["member"].cert)])
    return Up(hub, dialer, listener, rendezvous, transport, seen, linked, hellos, first, stubs)


async def _record(bucket: list, item) -> None:
    bucket.append(item)


async def _down(up: Up) -> None:
    await up.transport.close()
    await up.dialer.stop()
    await up.hub.stop()
    await up.listener.stop()
    for s in up.stubs:
        s.close()


async def _linked(up: Up):
    await asyncio.wait_for(up.transport.settle(), 5)
    return await up.transport.establish()


@pytest.mark.asyncio
async def test_both_directions_hello_addresses_and_first_link(world):
    up = await _up(world)
    try:
        route = await _linked(up)
        assert route == Route("unix", up.transport.out_path) and oct(os.stat(up.transport.out_path).st_mode & 0o777) == "0o600"
        link_post = next(s for s in up.seen if s[1] == "/federation/link")
        back_path = json.loads(link_post[2])["path"]
        assert link_post[0] == "main" and Path(back_path).name.startswith(f"in-{GRANT}-") and back_path.endswith(".sock")
        assert up.linked == [MEMBER_IID] and up.first == ["first"] and up.hub.connected() == [MEMBER_IID]
        assert up.hellos == [(MEMBER_IID, ["member.local"], up.listener.port)]
        out = await _Client(route).request("GET", "/api/v1/federation/hello")
        assert out.json() == {"who": "main", "len": 0}
        back = await _Client(Route("unix", back_path)).request("GET", "/api/v1/federation/hello")
        assert back.json() == {"who": "member", "len": 0}
        await up.transport.close()
        for _ in range(50):
            if not up.hub.connected():
                break
            await asyncio.sleep(0.05)
        assert not up.hub.connected() and not os.path.exists(back_path) and not os.path.exists(up.transport.out_path)
    finally:
        await _down(up)


@pytest.mark.asyncio
async def test_a_swapped_main_cert_is_refused_by_the_member(world):
    up = await _up(world, dialer_ident="evil")
    try:
        await asyncio.sleep(0.6)
        assert up.rendezvous.take() is None and up.linked == [] and up.hub.connected() == [] and up.first == []
        with pytest.raises(LinkDown, match="waiting for main"):
            await up.transport.establish()
    finally:
        await _down(up)


@pytest.mark.asyncio
async def test_a_member_that_is_not_the_pinned_one_is_refused_by_main(world):
    up = await _up(world, member_pin=world[2]["evil"].cert, dial=False, backoff=lambda _a: 3600)
    try:
        await up.hub.set_members([Member(MEMBER_IID, GRANT, world[2]["evil"].cert)])
        await _wait(lambda: (up.dialer.dial_state(MEMBER_IID) or {}).get("state") == "cert_mismatch")
        assert up.linked == [] and up.rendezvous.take() is None
    finally:
        await _down(up)


async def _wait(predicate, seconds: float = 5.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_one_mib_blob_fits_the_five_second_deadline_with_a_slow_link(world):
    up = await _up(world)
    try:
        route = await _linked(up)

        def slow(session):
            real = session._w.drain

            async def drain():
                await asyncio.sleep(0.05)
                await real()
            session._w.drain = drain

        slow(up.transport._session)
        slow(up.hub._conns[MEMBER_IID].session)
        blob = os.urandom(1024 * 1024)
        started = time.monotonic()
        reply = await asyncio.wait_for(_Client(route).request("PUT", "/blob", content=blob), 5.0)
        assert reply.json() == {"who": "main", "len": len(blob)} and time.monotonic() - started < 5.0
    finally:
        await _down(up)


@pytest.mark.asyncio
async def test_a_newer_connection_replaces_the_older_and_removal_closes_it(world):
    up = await _up(world)
    try:
        await _linked(up)
        old = up.transport._session
        await up.transport.close()
        await _linked(up)
        assert old.closed.is_set() and up.hub.connected() == [MEMBER_IID]
        await up.hub.set_members([])
        for _ in range(50):
            if not up.hub.connected():
                break
            await asyncio.sleep(0.05)
        assert up.hub.connected() == [] and up.hub.state == ll.STOPPED and up.dialer.dial_state(MEMBER_IID) is None
    finally:
        await _down(up)


def test_handshake_gate_caps_per_source_and_total():
    gate = ll._HandshakeGate(4, 32)
    assert [gate.enter("a") for _ in range(5)] == [True] * 4 + [False]
    gate.leave("a")
    assert gate.enter("a")
    gate = ll._HandshakeGate(4, 6)
    assert [gate.enter(f"s{i % 3}") for i in range(8)] == [True] * 6 + [False] * 2


def test_a_source_that_keeps_failing_handshakes_is_closed_before_tls_for_a_minute():
    now = [100.0]
    gate = ll._HandshakeGate(4, 32, clock=lambda: now[0])
    for _ in range(ll.FAILURE_LIMIT - 1):
        gate.note_failure("a")
    assert gate.enter("a") and gate.enter("b")
    gate.leave("a")
    gate.note_failure("a")
    assert not gate.enter("a") and gate.enter("b")
    now[0] += ll.FAILURE_WINDOW + 1
    assert gate.enter("a")


def test_a_blocked_private_address_is_named_local_network_blocked():
    import errno
    from src.core.computers.link_dialer import _failure_state
    blocked = [OSError(errno.EHOSTUNREACH, "No route to host")]
    assert _failure_state(blocked, [("192.0.2.14", 1), ("air.local", 1)]) == LOCAL_NETWORK_BLOCKED
    assert _failure_state(blocked, [("8.8.8.8", 1)]) == "unreachable"
    assert _failure_state([ConnectionRefusedError()], [("192.0.2.14", 1)]) == "unreachable"


@pytest.mark.asyncio
async def test_the_factory_returns_tls_only_for_a_tls_main_row(world):
    root, dirs, idents = world
    cache = store.LinkCache()
    cache.replace([store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=idents["main"].cert.der), store.LinkRow("ssh-peer", "main", "ssh", "")])
    factory = tls_transport_factory(install_id=MEMBER_IID, listener_path=str(root / "m.sock"), rendezvous=Rendezvous(),
                                    on_first_link=lambda iid: _record([], iid), addresses=lambda: [], listen_port=lambda: None,
                                    cache=cache, control_dir=root)
    def peer(iid):
        return peer_hosts.PeerRow(key="peer-" + iid, label=iid, ssh_target="", ssh_port=None, peer_install_id=iid,
                                  peer_grant_id="g", peer_fid="f", peer_protocol=None, peer_state=None, initiator=True,
                                  peer_port=None, back_kind="unix")
    assert isinstance(factory(peer(MAIN_IID), _Client), TlsInitiatorTransport)
    assert factory(peer("ssh-peer"), _Client) is None and factory(peer("nobody"), _Client) is None


@pytest.mark.asyncio
async def test_peer_links_uses_the_factory_and_set_initiator_keeps_the_ssh_target(macs, monkeypatch):  # noqa: F811
    acceptor, initiator = macs
    with closing(initiator.conn()) as c:
        grants.create_grant(c, peer_install_id=acceptor.install_id, public_key=pair_driver.fed_key.public_key_b64(acceptor.key),
                            label="a", remote_grant_id="theirs")
        peer_hosts.upsert(c, install_id=acceptor.install_id, label="a", grant_id="theirs", fid="f", initiator=False,
                         ssh_target="hosta", ssh_port=2201)
        assert peer_hosts.set_initiator(c, acceptor.install_id, True)
        after = peer_hosts.get(c, acceptor.install_id)
        assert after.initiator and after.ssh_target == "hosta" and after.ssh_port == 2201
        assert not peer_hosts.set_initiator(c, "no-such-peer", True)

    class Stub:
        out_path = "/x"
        settle = None
        async def establish(self):
            raise LinkDown("stub")
        async def renew(self, client): ...
        async def close(self): ...

    class FakeSsh(Stub):
        def __init__(self, **kw) -> None:
            self.kw = kw

    monkeypatch.setattr(peer_links, "InitiatorTransport", FakeSsh)
    stub = Stub()
    links = peer_links.PeerLinks(open_db=initiator.conn, listener_path="/tmp/x.sock")
    links.use_key(initiator.key)
    links.transport_factory = lambda r, make: stub if r.peer_install_id == acceptor.install_id else None
    try:
        await links.start_initiator(after)
        assert links._transports[acceptor.install_id] is stub
        links.transport_factory = lambda r, make: None
        await links.start_initiator(after)
        assert isinstance(links._transports[acceptor.install_id], FakeSsh) and links._transports[acceptor.install_id].kw["dest"].target == "hosta"
    finally:
        await links.shutdown()
