
from __future__ import annotations

import asyncio
import os
import socket
import ssl
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.python.computers.test_computers_runtime import _runtime
from tests.python.computers.test_join_commit import JOIN, MAIN, _join_prov, _main_prov, world  # noqa: F401

# ruff: noqa: E402
from src.core.computers import link_rotate, membership, runtime, store
from src.core.computers import link_dialer, link_listener
from src.core.computers.mux import frames as f
from src.core.computers.mux import session as mux_session
from src.core.federation import fed_key, peer_link
from src.core.federation.peer_links import PeerLinks
from src.core.notifications import contracts
from src.core.relay_identity.device_key import DeviceKey
from tests.python.computers.test_mux import _pair


@pytest.fixture()
def sink(monkeypatch):
    got = []
    monkeypatch.setattr(contracts, "_sink", got.append)
    return got


@pytest.mark.asyncio
async def test_a_peer_that_never_reads_cannot_grow_the_control_queue():
    d, m = await _pair()
    for _ in range(mux_session.MAX_CONTROL_QUEUE * 4):
        m._control(f.PING, 0, b"12345678")
    assert len(m._ctl) <= mux_session.MAX_CONTROL_QUEUE
    await asyncio.wait_for(m.closed.wait(), 3)
    assert m.close_reason == "control backlog"
    await d.close()


@pytest.mark.asyncio
async def test_a_write_that_stalls_ends_the_session(monkeypatch):
    monkeypatch.setattr(mux_session, "WRITE_STALL_TIMEOUT", 0.2)
    d, m = await _pair()

    async def never() -> None:
        await asyncio.sleep(60)

    m._w.drain = never
    m._control(f.PING, 0, b"12345678")
    await asyncio.wait_for(m.closed.wait(), 3)
    assert "write failed" in m.close_reason
    await d.close()


@pytest.mark.asyncio
async def test_persisting_addresses_never_rolls_back_a_rotation(world, monkeypatch):
    main, join = world
    res = await _main_prov(main, join, "new")
    rt = _runtime(main, monkeypatch)
    stale = main.query(lambda c: store.get(c, JOIN))
    main.query(lambda c: store.set_next_cert(c, JOIN, b"next-der", "nextsha"))
    monkeypatch.setattr(store, "get", lambda conn, iid: stale)
    await rt._on_member_hello(JOIN, ["10.9.9.9"], 4711)
    monkeypatch.undo()
    row = main.query(lambda c: store.get(c, JOIN))
    assert row.next_cert_sha256 == "nextsha" and row.addresses == ("10.9.9.9",) and row.link_port == 4711
    assert res is not None


def test_the_ports_bind_the_configured_address():
    assert runtime.bind_host("192.168.1.20") == "192.168.1.20"
    assert runtime.bind_host("0.0.0.0") == runtime.ALL_BIND
    assert runtime.bind_host("127.0.0.1") == runtime.LOOPBACK_BIND and runtime.bind_host("localhost") == runtime.LOOPBACK_BIND


@pytest.mark.asyncio
async def test_wrong_codes_reach_the_owner(world, monkeypatch, sink):
    main, _join = world
    rt = _runtime(main, monkeypatch)
    rt._on_notice("burned", "10.0.0.7")
    assert [(e.type_id, e.kind) for e in sink] == [("computer.wrong_code", "computer_wrong_code")]
    assert "10.0.0.7" in sink[0].details


@pytest.mark.asyncio
async def test_alerts_count_to_refused_and_anything_else_resets(monkeypatch):
    outcomes = [link_listener.ALERTED, link_listener.ALERTED, link_listener.ALERTED, link_listener.NO_HELLO]

    class Hub:
        def connected(self):
            return []

        async def serve(self, reader, writer):
            return outcomes.pop(0)

    class Writer:
        def close(self):
            pass

    monkeypatch.setattr(link_dialer, "client_link_ctx", lambda identity, pins: None)
    dialer = link_dialer.LinkDialer(identity=None, hub=Hub(), rows=lambda iid: store.LinkRow(iid, "member", "tls", "", addresses=("10.0.0.2",), link_port=47110))

    async def fake_dial(targets, ctx, shas):
        return ("10.0.0.2", 47110, None, Writer()), []

    monkeypatch.setattr(dialer, "_dial", fake_dial)
    member = SimpleNamespace(cert=object(), next_cert=None, shas=lambda: frozenset())
    dialer._dials["m"] = dial = link_dialer._Dial(task=None, kick=asyncio.Event(), member=member)
    states = [await dialer._round("m", dial) for _ in range(4)]
    assert states == ["unreachable", "unreachable", link_dialer.REFUSED, "unreachable"] and dial.alerts == 0


@pytest.mark.asyncio
async def test_a_refused_link_shows_refused_and_slows_down():
    states = []

    async def establish():
        raise peer_link.LinkRefused("main refuses this computer's certificate")

    link = peer_link.PeerLink(peer_install_id="p" * 16, establish=establish, make_client=lambda r: None,
                              on_state=lambda s, _p: states.append(s), delay=lambda _a: 0.0)
    link.start()
    await asyncio.sleep(0.1)
    await link.stop()
    assert peer_link.REFUSED in states


@pytest.mark.asyncio
async def test_a_provisional_joiner_opens_no_join_port(world, monkeypatch):
    main, join = world
    res = await _main_prov(main, join, "new")
    await _join_prov(main, join, res, "new")
    monkeypatch.setattr(membership, "is_member", lambda: False)
    store.CACHE.replace(join.query(lambda c: store.list_rows(c)))
    rt = _runtime(join, monkeypatch)
    assert rt.is_joiner()
    store.CACHE.replace([])
    assert not rt.is_joiner()


@pytest.mark.asyncio
async def test_a_rekey_while_down_and_a_waiting_rotation_tell_the_owner(world, monkeypatch, sink):
    main, join = world
    await _main_prov(main, join, "new")
    first = _runtime(main, monkeypatch)
    await first.prepare(PeerLinks(open_db=main.open_db, listener_path=first._listener_path))
    assert not first._rekeyed
    other = DeviceKey.from_seed(bytes([9]) * 32)
    rt = _runtime(main, monkeypatch)
    monkeypatch.setattr(fed_key, "load_key", lambda _iid: other)
    await rt.prepare(PeerLinks(open_db=main.open_db, listener_path=rt._listener_path))
    assert rt._rekeyed
    await rt.start()
    try:
        assert [(e.type_id, e.details) for e in sink] == [("computer.link_cert", "rekeyed")]
        sink.clear()

        async def waiting(**_kw):
            return link_rotate.WAITING

        monkeypatch.setattr(link_rotate, "run_step", waiting)
        monkeypatch.setattr(link_rotate, "read_staged", lambda _d, _i: link_rotate.Staged("abc", 0.0))
        await rt.link_rotation_step()
        await rt.link_rotation_step()
        assert [(e.type_id, e.details) for e in sink] == [("computer.link_cert", "rotation_waiting")]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_the_join_port_caps_connections_before_the_handshake(world, monkeypatch):
    main, _join = world
    rt = _runtime(main, monkeypatch)
    await rt.prepare(PeerLinks(open_db=main.open_db, listener_path=rt._listener_path))
    await rt.start()
    held = []
    try:
        rt.invites.mint()
        await rt.join_server.sync()
        port = rt.join_server.port
        for _ in range(2):
            held.append(await asyncio.open_connection("127.0.0.1", port))
        await asyncio.sleep(0.2)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        held.append((reader, writer))
        try:
            data = await asyncio.wait_for(reader.read(1), 1.0)
        except (ConnectionError, ssl.SSLError):
            data = b""
        assert data == b""
    finally:
        for _r, w in held:
            w.close()
        await rt.stop()
