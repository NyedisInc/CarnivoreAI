import asyncio
import socket
import subprocess

import pytest

from src.core.computers import link_addresses, link_dialer
from src.core.computers.join_server import JoinServer
from src.core.computers.link_listener import _HandshakeGate
from src.core.computers.member_listener import MEMBER_HANDSHAKE_TIMEOUT, MemberListener, Rendezvous, _port_free


def test_a_full_gate_evicts_the_oldest_handshake_and_counts_it_against_its_source():
    gate = _HandshakeGate(2, 2)
    dropped = []
    for name in ("a", "b"):
        assert gate.enter(name)
        gate.track(name, lambda n=name: (dropped.append(n), gate.note_failure(n), gate.leave(n), gate.untrack(n)))
    assert gate.full() and not gate.enter("c")
    assert gate.evict_oldest() and dropped == ["a"] and not gate.full() and gate.enter("c")
    assert gate._recent("a") == 1


def test_the_member_listener_evicts_and_times_out_fast():
    assert MemberListener.EVICT_OLDEST is True and MemberListener.HANDSHAKE_TIMEOUT == MEMBER_HANDSHAKE_TIMEOUT <= 2.0


@pytest.mark.asyncio
async def test_silent_connections_never_lock_the_member_listener(monkeypatch):
    from src.core.computers import tls_identity
    ml = MemberListener(identity=object(), rendezvous=Rendezvous(), host="127.0.0.1")
    ml._gate = _HandshakeGate(100, 3)
    ml._ctx = object()
    started = []

    async def fake_handshake(self, factory, sock, **kw):
        started.append(sock)
        await asyncio.sleep(30)

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(type(loop), "connect_accepted_socket", fake_handshake, raising=False)
    assert await ml.bind(0)
    socks = [socket.create_connection(("127.0.0.1", ml.port)) for _ in range(5)]
    try:
        await asyncio.sleep(0.4)
        assert ml._gate._count == 3 and len(ml._gate._inflight) == 3
        assert ml._gate._recent("127.0.0.1") == 2
    finally:
        for s in socks:
            s.close()
        await ml.stop()


def test_cert_mismatch_backs_off_normally_and_refused_stays_slow(monkeypatch):
    src = open(link_dialer.__file__).read()
    assert "if outcome == REFUSED:" in src and "(REFUSED, CERT_MISMATCH)" not in src


@pytest.mark.asyncio
async def test_a_local_name_is_expanded_to_every_address_it_resolves_to(monkeypatch):
    d = link_dialer.LinkDialer.__new__(link_dialer.LinkDialer)
    d._timeout = 1.0

    async def fake(self, host, port, **kw):
        return [(2, 1, 6, "", ("198.51.100.14", 0)), (2, 1, 6, "", ("198.51.100.13", 0))]

    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", fake)
    assert await d._expand(["air.local", "192.0.2.13", "198.51.100.13"]) == ["198.51.100.14", "198.51.100.13", "192.0.2.13"]

    async def boom(self, host, port, **kw):
        raise socket.gaierror("no")

    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", boom)
    assert await d._expand(["air.local"]) == ["air.local"]


def test_the_member_port_probe_uses_the_configured_host():
    assert _port_free(0, "127.0.0.1") is True
    assert _port_free(0, "203.0.113.1") is False


def test_runtime_binds_the_member_listener_with_the_join_port_rule():
    from src.core.computers import runtime
    assert runtime.bind_host("203.0.113.13") == "203.0.113.13"
    src = open(runtime.__file__).read()
    assert "host=ALL_BIND if bind == LOOPBACK_BIND else bind" in src


def test_observed_address_sits_right_after_the_names(monkeypatch):
    monkeypatch.setattr(JoinServer, "port", property(lambda self: 47111))
    js = JoinServer.__new__(JoinServer)
    js._lan_only = True
    body = {"listen": {"addresses": ["192.0.2.13", "air.local", "192.0.2.17"], "port": 47110}}
    addresses, _ = js._member_listen(body, "198.51.100.13")
    assert addresses == ["air.local", "198.51.100.13", "192.0.2.13", "192.0.2.17"]


def test_member_hello_addresses_pass_the_join_rules():
    got = link_addresses.learned_listen(["a.b.local", "bad name.local", "air.local", "127.0.0.1", "192.0.2.13"], 47110, join_port=47111)
    assert got == (["air.local", "192.0.2.13"], 47110)


def test_a_fallback_host_name_that_fails_validation_is_left_out(monkeypatch):
    def fake_run(argv):
        return "" if "scutil" in argv[0] else "\tinet 192.0.2.13 netmask 0xff"
    monkeypatch.setattr(link_addresses, "_run", fake_run)
    monkeypatch.setattr(socket, "gethostname", lambda: "my_mac.local")
    assert link_addresses.local_addresses() == ["192.0.2.13"]
    monkeypatch.setattr(socket, "gethostname", lambda: "air.local")
    assert link_addresses.local_addresses() == ["air.local", "192.0.2.13"]


def test_a_direction_change_kicks_the_dialer():
    from src.api import computers_routes
    src = open(computers_routes.__file__).read()
    assert "rt.dialer.kick(install_id)" in src
