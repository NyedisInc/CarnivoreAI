
from __future__ import annotations

import asyncio
import socket

import pytest

from src.core.computers import beacon, link_dialer, store
from src.core.computers.link_listener import LINKED, Member
from src.core.computers.link_dialer import LinkDialer
from tests.python.computers.test_tls_link import world  # noqa: F401

T0 = 1_760_000_000.0
DAY = 86400.0


class Clock:

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class StubHub:

    async def serve(self, reader, writer) -> str:
        return LINKED

    def connected(self):
        return []

    def relayed(self):
        return []


def _packet(member_cert, when: float = T0) -> bytes:
    return beacon.encode(member_cert.cert_sha256, when)


@pytest.mark.asyncio
async def test_beacon_from_hint_to_candidate_dial(world):  # noqa: F811
    _root, _dirs, idents = world
    cert, next_cert, evil = idents["member"].cert, idents["evil"].cert, idents["main"].cert
    member = Member("member-iid", "g1", cert, next_cert)
    other = Member("other-iid", "g2", evil)
    kicks, connected, mono, wall = [], [], Clock(100.0), Clock(T0)
    listener = beacon.BeaconListener(members=lambda: [member, other], connected=lambda: connected, kick=lambda i, s: kicks.append((i, s)),
                                     host="127.0.0.1", port=0, clock=mono, wall=wall)

    assert listener.handle(_packet(cert, T0), "192.168.1.9") == "kicked"
    mono.now += 11
    assert listener.handle(_packet(cert, T0 - DAY), "10.0.0.7") == "kicked"
    mono.now += 11
    assert listener.handle(_packet(cert, T0 + DAY), "172.16.5.5") == "kicked"
    mono.now += 11
    assert listener.handle(_packet(cert, T0 + 2 * DAY), "192.168.1.9") == "unknown"
    assert listener.handle(_packet(cert, T0 - 2 * DAY), "192.168.1.9") == "unknown"
    assert listener.handle(_packet(next_cert), "192.168.1.9") == "kicked"
    mono.now += 11
    assert listener.handle(beacon.encode(_FOREIGN, T0), "192.168.1.9") == "unknown"
    assert [i for i, _ in kicks] == ["member-iid"] * 4 and kicks[0][1] == "192.168.1.9"

    for bad in (b"", b"CCPB", beacon.MAGIC + bytes([2]) + b"x" * 8, b"XXXX" + bytes([1]) + b"x" * 8, _packet(cert) + b"!"):
        assert listener.handle(bad, "192.168.1.9") == "malformed"
    for source in ("8.8.8.8", "100.64.0.5", "169.254.1.1", "127.0.0.1", "air.local"):
        assert listener.handle(_packet(cert), source) == "not_lan"
    assert len(kicks) == 4

    connected.append("member-iid")
    mono.now += 11
    assert listener.handle(_packet(cert), "192.168.1.9") == "connected" and len(kicks) == 4
    connected.clear()

    assert listener.handle(_packet(cert), "192.168.1.9") == "kicked"
    assert listener.handle(_packet(cert), "192.168.1.9") == "throttled"
    listener.throttle.refund("member-iid")
    assert listener.handle(_packet(cert), "192.168.1.9") == "kicked"
    mono.now += 11
    assert listener.handle(_packet(evil), "192.168.1.10") == "kicked"
    clock = Clock(0.0)
    throttle = beacon.KickThrottle(clock)
    assert [throttle.allow(f"m{i}") for i in range(7)] == [True] * 6 + [False]
    throttle.refund("m0")
    assert throttle.allow("m7")
    clock.now = 61.0
    assert throttle.allow("m8")

    sent, addrs, linked = [], ["192.168.1.20", "10.5.5.5", "100.64.0.9", "air.local", "8.8.8.8"], [False]
    sender = beacon.BeaconSender(cert_sha256=lambda: cert.cert_sha256, addresses=lambda: addrs, subnets=lambda: ["192.168.1.0/24", "bogus"],
                                 linked=lambda: linked[0], enabled=lambda: True, send=lambda a, p: sent.append((a, p)), wall=wall)
    assert sender.eligible() == ["192.168.1.20"]
    assert [sender.step() for _ in range(5)] == [2.0, 2.0, 60.0, 60.0, 60.0]
    assert {a for a, _ in sent} == {"192.168.1.20"} and all(beacon.parse(p) == beacon.hint_for(cert.cert_sha256, beacon.day_number(T0)) for _, p in sent)
    sent.clear()
    addrs[0] = "192.168.1.21"
    assert sender.step() == 2.0 and sent[0][0] == "192.168.1.21"
    sent.clear()
    linked[0] = True
    assert sender.step() == beacon.IDLE_POLL and not sent
    linked[0] = False
    assert sender.step() == 2.0 and len(sent) == 1
    sent.clear()
    addrs[:] = ["172.20.10.2", "100.64.0.9"]
    assert sender.step() == beacon.IDLE_POLL and not sent

    row = store.LinkRow("member-iid", "member", "tls", "", cert_der=cert.der, cert_sha256=cert.cert_sha256, link_fid=cert.link_fid,
                        addresses=(), link_port=47110)
    wins, targets = [], []
    dialer = LinkDialer(identity=idents["main"], hub=StubHub(), rows=lambda iid: row, backoff=lambda _a: 1000, on_candidate_win=wins.append)
    dialer.set_members([Member("member-iid", "g1", cert)])
    dial = dialer._dials["member-iid"]
    dialer._dials["member-iid"].task.cancel()
    await asyncio.gather(dial.task, return_exceptions=True)
    for bad in ("127.0.0.1", "air.local", "not an ip", "::1", "8.8.8.8"):
        dialer.kick("member-iid", bad)
    assert not dial.candidates or list(dial.candidates) == ["8.8.8.8"]
    dial.candidates.clear()
    for ip in ("192.168.1.9", "192.168.1.9", "192.168.1.10", "192.168.1.11", "192.168.1.12"):
        dialer.kick("member-iid", ip)
    assert list(dial.candidates) == ["192.168.1.10", "192.168.1.11", "192.168.1.12"] or list(dial.candidates) == ["192.168.1.9", "192.168.1.10", "192.168.1.11"]
    dial.candidates.clear()
    dialer.kick("member-iid", "192.168.1.9")

    async def fake_dial(tgts, ctx, shas):
        targets.append(list(tgts))
        reader, writer = asyncio.StreamReader(), _Writer()
        return (tgts[0][0], tgts[0][1], reader, writer), []

    dialer._dial = fake_dial
    assert await dialer._round("member-iid", dial) == link_dialer.LINKED_STATE
    assert targets == [[("192.168.1.9", 47110)]] and wins == ["member-iid"] and not dial.candidates
    row2 = store.LinkRow("member-iid", "member", "tls", "", cert_der=cert.der, cert_sha256=cert.cert_sha256, link_fid=cert.link_fid, addresses=(), link_port=None)
    dialer._rows = lambda iid: row2
    dialer.kick("member-iid", "192.168.1.9")
    assert await dialer._round("member-iid", dial) == link_dialer.UNREACHABLE and len(targets) == 1

    rounds = []

    async def fake_round(iid, d):
        rounds.append(1)
        d.candidates.clear()
        if len(rounds) == 1:
            dialer.kick(iid, "192.168.1.30")
        return link_dialer.UNREACHABLE

    dialer._rows = lambda iid: row
    dialer._round = fake_round
    dial.kick.clear()
    dial.task = asyncio.get_running_loop().create_task(dialer._run("member-iid"))
    await asyncio.sleep(0.3)
    assert len(rounds) == 2, "the pending candidate must wake the next round at once"
    await asyncio.sleep(0.3)
    assert len(rounds) == 2, "with no candidate the round waits out its backoff"
    dial.task.cancel()
    await asyncio.gather(dial.task, return_exceptions=True)

    outcomes = []
    real = beacon.BeaconListener(members=lambda: [member], connected=lambda: [], kick=lambda i, s: outcomes.append(("kick", i)), host="127.0.0.1", port=0, wall=wall)
    original = real.handle
    real.handle = lambda data, source: (outcomes.append(original(data, source)), outcomes[-1])[1]
    assert await real.start() and real.running and await real.start()
    port = real._transport.get_extra_info("sockname")[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(_packet(cert), ("127.0.0.1", port))
    for _ in range(50):
        if outcomes:
            break
        await asyncio.sleep(0.05)
    assert outcomes == ["not_lan"] and real.last_heard is None
    await real.stop()
    assert not real.running


@pytest.mark.asyncio
async def test_listener_falls_back_to_the_second_port_and_the_member_sends_to_both(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as spare:
            spare.bind(("127.0.0.1", 0))
            free = spare.getsockname()[1]
        listener = beacon.BeaconListener(members=lambda: [], connected=lambda: [], kick=lambda i, s: None, host="127.0.0.1",
                                         port=taken, fallback_port=free)
        assert await listener.start() and listener.bound_port == free
        await listener.stop()
        assert listener.bound_port is None
        both = beacon.BeaconListener(members=lambda: [], connected=lambda: [], kick=lambda i, s: None, host="127.0.0.1", port=taken, fallback_port=taken)
        assert await both.start() is False and not both.running

    sent = []

    class _Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def setsockopt(self, *a): pass
        def settimeout(self, *a): pass
        def bind(self, *a): pass
        def sendto(self, packet, dest): sent.append(dest)

    monkeypatch.setattr(beacon.socket, "socket", lambda *a, **k: _Sock())
    sender = beacon.BeaconSender(cert_sha256=lambda: "ab" * 32, addresses=lambda: [], subnets=lambda: [], linked=lambda: False, enabled=lambda: True)
    sender._broadcast("192.168.1.2", b"x")
    assert sent == [(beacon.BROADCAST, beacon.BEACON_UDP_PORT), (beacon.BROADCAST, beacon.BEACON_FALLBACK_PORT)]


_FOREIGN = "ab" * 32


class _Writer:

    def close(self) -> None:
        pass


def test_rendezvous_records_the_local_address_the_link_came_in_on() -> None:
    import asyncio
    from src.core.computers.member_listener import Rendezvous

    class W:
        def get_extra_info(self, name):
            return ("192.168.7.9", 47110) if name == "sockname" else None

        def close(self) -> None:
            pass

    async def run() -> None:
        rv = Rendezvous()
        rv.offer(object(), W())
        assert rv.take() is not None
        assert rv.taken_local_address == "192.168.7.9"
        assert rv.take() is None and rv.taken_local_address is None

    asyncio.run(run())
