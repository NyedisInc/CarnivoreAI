
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import ssl
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from src.core.computers import link_rotate, store
from src.core.computers.ddl import apply_computer_links
from src.core.computers.link_dialer import LinkDialer
from src.core.computers.link_listener import LinkListener, Member
from src.core.computers.link_transport import TlsInitiatorTransport
from src.core.computers.member_listener import MemberListener, Rendezvous
from src.core.computers.tls_identity import LinkIdentity, client_link_ctx, ensure_link_identity, pinned_certs
from src.core.federation import fed_key, key_rotate
from src.core.federation.grants import Grant
from src.core.relay_identity.device_key import DeviceKey
from tests.python.computers.test_tls_link import GRANT, MAIN_IID, MEMBER_IID, _Client, _stub_listener

OLD_SEEDS = {"main": 1, "member": 2}
NEW_SEEDS = {"main": 11, "member": 12}


@pytest.fixture()
def world(tmp_path):
    root = Path(tempfile.mkdtemp(prefix="lr"))
    dirs = {n: root / n for n in ("main", "member", "legacy")}
    for d in dirs.values():
        d.mkdir(mode=0o700)
    ids = {"main": MAIN_IID, "member": MEMBER_IID}
    keys = {n: DeviceKey.from_seed(bytes([OLD_SEEDS[n]]) * 32) for n in ids}
    idents = {n: ensure_link_identity(keys[n], ids[n], dirs[n]) for n in ids}
    db_path = tmp_path / "t.db"
    seed = sqlite3.connect(db_path, isolation_level=None)
    apply_computer_links(seed)
    seed.close()
    store.CACHE.replace([])

    def open_db() -> sqlite3.Connection:
        return sqlite3.connect(db_path, isolation_level=None)

    yield SimpleNamespace(root=root, dirs=dirs, ids=ids, keys=keys, idents=idents, open_db=open_db)
    shutil.rmtree(root, ignore_errors=True)


def _grant(peer_iid: str, key: DeviceKey) -> Grant:
    return Grant("g-" + peer_iid[:4], peer_iid, fed_key.public_key_b64(key), key.device_id, "x", ("machine",), None, "", None, None)


def _legacy(world, name: str) -> LinkIdentity:
    d, ident = world.dirs["legacy"], world.idents[name]
    key, cert = d / f"{name}-key.pem", d / f"{name}-cert.pem"
    shutil.copy(ident.key_path, key)
    shutil.copy(ident.cert_path, cert)
    return LinkIdentity(cert=ident.cert, key_path=key, cert_path=cert)


def _stage_and_send(world, name: str) -> tuple:
    new_key = DeviceKey.from_seed(bytes([NEW_SEEDS[name]]) * 32)
    cert = link_rotate.stage(new_key, world.ids[name], world.dirs[name])
    return new_key, cert, new_key.sign(link_rotate.link_cert_message(cert.der))


def test_accept_stores_next_beside_current_and_refuses_the_rest(world):
    main_cert, member_cert = world.idents["main"].cert, world.idents["member"].cert
    with closing_conn(world) as conn:
        store.put(conn, store.LinkRow(MEMBER_IID, "member", "tls", "", cert_der=member_cert.der, cert_sha256=member_cert.cert_sha256,
                                      link_fid=member_cert.link_fid))
        new_key, cert, sig = _stage_and_send(world, "member")
        grant = _grant(MEMBER_IID, new_key)
        b64 = link_rotate.join_proto.b64e(cert.der)
        assert ensure_link_identity(new_key, MEMBER_IID, world.dirs["member"]).cert.cert_sha256 == member_cert.cert_sha256
        wrong = DeviceKey.from_seed(b"\x77" * 32).sign(link_rotate.link_cert_message(cert.der))
        for bad_sig in (wrong, "x", None):
            with pytest.raises(link_rotate.LinkCertRefused) as caught:
                link_rotate.accept(conn, grant, b64, bad_sig, own_link_fid=main_cert.link_fid)
            assert caught.value.code == "link_cert_signature"
        with pytest.raises(link_rotate.LinkCertRefused) as caught:
            link_rotate.accept(conn, grant, "!!notbase64", sig, own_link_fid=main_cert.link_fid)
        assert caught.value.code == "link_cert_malformed"
        with pytest.raises(link_rotate.LinkCertRefused) as caught:
            link_rotate.accept(conn, grant, b64, sig, own_link_fid=cert.link_fid)
        assert caught.value.code == "cert_invalid"
        stranger = _grant("other-install-zzzz", new_key)
        with pytest.raises(link_rotate.LinkCertRefused) as caught:
            link_rotate.accept(conn, stranger, b64, sig, own_link_fid=main_cert.link_fid)
        assert (caught.value.code, caught.value.status) == ("computer_not_linked_tls", 409)
        assert store.get(conn, MEMBER_IID).next_cert_sha256 is None
        link_rotate.accept(conn, grant, b64, sig, own_link_fid=main_cert.link_fid)
        row = store.get(conn, MEMBER_IID)
        assert row.cert_sha256 == member_cert.cert_sha256 and row.next_cert_sha256 == cert.cert_sha256
        assert len(pinned_certs([row.cert_der, row.next_cert_der], own_link_fid=main_cert.link_fid)) == 2


class closing_conn:

    def __init__(self, world) -> None:
        self._conn = world.open_db()

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, *exc) -> None:
        self._conn.close()


async def _flipped(world, *, main_identity, on_rotated=None, get_link, on_member_rotated=None, member_cert_pin=None):
    root, member = world.root, world.idents["member"]
    seen: list = []
    stubs = [await _stub_listener(str(root / "main.sock"), "main", seen), await _stub_listener(str(root / "member.sock"), "member", seen)]
    rendezvous = Rendezvous()
    listener = MemberListener(identity=member, rendezvous=rendezvous, host="127.0.0.1")
    assert await listener.bind(0)
    holder: dict = {}
    hub = LinkListener(identity=main_identity, fed_dir=world.dirs["main"], listener_path=str(root / "main.sock"), addresses=lambda: ["a"],
                       on_rotated=on_rotated, on_members=lambda ms: holder["dialer"].set_members(ms))
    cache = store.LinkCache()
    cache.replace([store.LinkRow(MEMBER_IID, "member", "tls", "", addresses=("127.0.0.1",), link_port=listener.port)])
    holder["dialer"] = LinkDialer(identity=main_identity, hub=hub, rows=cache.get, backoff=lambda _a: 0, stagger=0.05)
    transport = TlsInitiatorTransport(install_id=MEMBER_IID, host_key="peer-main", rendezvous=rendezvous, get_link=get_link,
                                      listener_path=str(root / "member.sock"), make_client=_Client, on_rotated=on_member_rotated, control_dir=root)
    return hub, holder["dialer"], listener, transport, stubs


@pytest.mark.asyncio
async def test_rotation_over_a_live_link_pins_both_then_drops_the_old(world):
    member_cert, main = world.idents["member"].cert, world.idents["main"]
    old_member = _legacy(world, "member")
    with closing_conn(world) as conn:
        store.put(conn, store.LinkRow(MEMBER_IID, "member", "tls", "", cert_der=member_cert.der, cert_sha256=member_cert.cert_sha256,
                                      link_fid=member_cert.link_fid))
    new_key, new_cert, sig = _stage_and_send(world, "member")
    with closing_conn(world) as conn:
        link_rotate.accept(conn, _grant(MEMBER_IID, new_key), link_rotate.join_proto.b64e(new_cert.der), sig,
                           own_link_fid=main.cert.link_fid)

    def members() -> List[Member]:
        with closing_conn(world) as conn:
            row = store.get(conn, MEMBER_IID)
        certs = pinned_certs([d for d in (row.cert_der, row.next_cert_der) if d], own_link_fid=main.cert.link_fid)
        return [Member(MEMBER_IID, GRANT, certs[0], certs[1] if len(certs) > 1 else None)]

    promoted: List[str] = []

    async def on_rotated(iid: str, sha: str) -> None:
        assert link_rotate.promote(world.open_db, iid, sha)
        promoted.append(sha)
        await hub.set_members(members())

    main_row = store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=main.cert.der, cert_sha256=main.cert.cert_sha256)
    hub, dialer, listener, transport, stubs = await _flipped(world, main_identity=main, on_rotated=on_rotated, get_link=lambda: main_row)
    await listener.set_pins([main.cert])
    await hub.set_members(members())
    try:
        await asyncio.wait_for(transport.settle(), 5)
        await transport.establish()
        assert hub.connected() == [MEMBER_IID] and promoted == []
        link_rotate.swap(world.idents["member"], MEMBER_IID, world.dirs["member"])
        assert world.idents["member"].cert.cert_sha256 == new_cert.cert_sha256
        assert not (world.dirs["member"] / f"link-{MEMBER_IID[:12]}-next-cert.pem").exists()
        assert ensure_link_identity(new_key, MEMBER_IID, world.dirs["member"]).cert.cert_sha256 == new_cert.cert_sha256
        await listener.set_pins([main.cert])
        await transport.close()
        await asyncio.wait_for(transport.settle(), 5)
        await transport.establish()
        assert promoted == [new_cert.cert_sha256]
        with closing_conn(world) as conn:
            row = store.get(conn, MEMBER_IID)
        assert row.cert_sha256 == new_cert.cert_sha256 and row.next_cert_der is None and row.link_fid == new_cert.link_fid
        assert hub.connected() == [MEMBER_IID]
        late = MemberListener(identity=old_member, rendezvous=Rendezvous(), host="127.0.0.1")
        assert await late.bind(0)
        await late.set_pins([main.cert])
        ctx = client_link_ctx(main, pinned_certs([row.cert_der], own_link_fid=main.cert.link_fid))
        with pytest.raises(ssl.SSLCertVerificationError):
            await asyncio.open_connection("127.0.0.1", late.port, ssl=ctx, server_hostname="127.0.0.1")
        await late.stop()
    finally:
        await transport.close()
        await dialer.stop()
        await hub.stop()
        await listener.stop()
        for s in stubs:
            s.close()


@pytest.mark.asyncio
async def test_a_member_promotes_mains_next_cert_when_main_presents_it(world):
    member, main_old = world.idents["member"], world.idents["main"]
    new_key, new_cert, sig = _stage_and_send(world, "main")
    with closing_conn(world) as conn:
        store.put(conn, store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=main_old.cert.der, cert_sha256=main_old.cert.cert_sha256,
                                      link_fid=main_old.cert.link_fid, addresses=("127.0.0.1",)))
        link_rotate.accept(conn, _grant(MAIN_IID, new_key), link_rotate.join_proto.b64e(new_cert.der), sig, own_link_fid=member.cert.link_fid)
        row = store.get(conn, MAIN_IID)
    link_rotate.swap(main_old, MAIN_IID, world.dirs["main"])
    reported: List[str] = []

    async def rotated(sha: str) -> None:
        reported.append(sha)
        assert link_rotate.promote(world.open_db, MAIN_IID, sha)

    def current() -> store.LinkRow:
        with closing_conn(world) as conn:
            return store.get(conn, MAIN_IID)

    hub, dialer, listener, transport, stubs = await _flipped(world, main_identity=main_old, get_link=current, on_member_rotated=rotated)
    await listener.set_pins(pinned_certs([row.cert_der, row.next_cert_der], own_link_fid=member.cert.link_fid))
    await hub.set_members([Member(MEMBER_IID, GRANT, member.cert)])
    try:
        await asyncio.wait_for(transport.settle(), 5)
        await transport.establish()
        assert reported == [new_cert.cert_sha256]
        with closing_conn(world) as conn:
            row = store.get(conn, MAIN_IID)
        assert row.cert_sha256 == new_cert.cert_sha256 and row.next_cert_der is None
    finally:
        await transport.close()
        await dialer.stop()
        await hub.stop()
        await listener.stop()
        for s in stubs:
            s.close()


class _FakeClient:

    def __init__(self, signer: DeviceKey, log: list, status: int = 200) -> None:
        self.signer, self.log, self.status = signer, log, status

    async def request(self, method: str, path: str, json=None, **kw):
        assert (method, path) == ("POST", link_rotate.LINK_CERT_PATH)
        der = link_rotate.join_proto.b64d(json["cert_der"])
        link_rotate.verify_link_cert(fed_key.public_key_b64(self.signer), der, json["sig"])
        self.log.append(path)
        return SimpleNamespace(status_code=self.status)


@pytest.mark.asyncio
async def test_run_step_tells_each_computer_once_and_swaps_when_all_acknowledged_or_a_week_passed(world):
    ident, iid, fed_dir = world.idents["main"], MAIN_IID, world.dirs["main"]
    old_sha = ident.cert.cert_sha256
    with closing_conn(world) as conn:
        for peer in ("peer-a", "peer-b"):
            store.put(conn, store.LinkRow(peer, "member", "tls", "", cert_sha256="s-" + peer, link_fid="f-" + peer, cert_der=b"x"))
        store.put(conn, store.LinkRow("ssh-peer", "peer", "ssh", ""))
    new_key, new_cert, _ = _stage_and_send(world, "main")
    told: list = []
    links = SimpleNamespace(clients={"peer-a": _FakeClient(new_key, told)}, client=lambda p: links.clients.get(p))
    args = dict(links=links, open_db=world.open_db, fed_dir=fed_dir, iid=iid, signer=new_key, identity=ident)
    assert await link_rotate.run_step(**args) == link_rotate.WAITING and told == [link_rotate.LINK_CERT_PATH]
    assert link_rotate.read_staged(fed_dir, iid).acked == ("peer-a",)
    assert await link_rotate.run_step(**args) == link_rotate.WAITING and len(told) == 1
    assert ident.cert.cert_sha256 == old_sha
    assert await link_rotate.run_step(**args, now=time.time() + link_rotate.SWAP_AFTER_SECONDS + 5) == link_rotate.SWAPPED
    assert ident.cert.cert_sha256 == new_cert.cert_sha256 and link_rotate.read_staged(fed_dir, iid) is None
    key2 = DeviceKey.from_seed(b"\x55" * 32)
    cert2 = link_rotate.stage(key2, iid, fed_dir)
    links.clients["peer-b"] = _FakeClient(key2, told)
    links.clients["peer-a"] = _FakeClient(key2, told)
    assert await link_rotate.run_step(**{**args, "signer": key2}) == link_rotate.SWAPPED and ident.cert.cert_sha256 == cert2.cert_sha256
    assert len(told) == 3
    with closing_conn(world) as conn:
        for peer in ("peer-a", "peer-b"):
            store.delete(conn, peer)
    cert3 = link_rotate.stage(DeviceKey.from_seed(b"\x56" * 32), iid, fed_dir)
    assert await link_rotate.run_step(**args) == link_rotate.SWAPPED and ident.cert.cert_sha256 == cert3.cert_sha256
    assert await link_rotate.run_step(**args) == link_rotate.IDLE


@pytest.mark.asyncio
async def test_key_rotate_hands_the_new_key_to_the_link_after_the_commit(world, monkeypatch):
    order: list = []
    old, new = world.keys["main"], DeviceKey.from_seed(b"\x66" * 32)
    monkeypatch.setattr(fed_key, "load_key", lambda iid: old)
    monkeypatch.setattr(fed_key, "begin_rotation", lambda iid: new)
    monkeypatch.setattr(fed_key, "commit_rotation", lambda iid: order.append("commit"))

    async def hook(key: DeviceKey) -> None:
        order.append(("link", key))

    monkeypatch.setattr(link_rotate, "after_federation_rotation", hook)
    result = await key_rotate.rotate(install_id=MAIN_IID, links=None, live_grants=0)
    assert order == ["commit", ("link", new)] and result["fid"] == fed_key.fid_for(new.raw_pub)
