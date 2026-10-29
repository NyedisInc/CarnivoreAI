
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from src.core.computers import store
from src.core.computers.link_dialer import LinkDialer
from src.core.computers.link_listener import LinkListener, Member
from src.core.computers.link_transport import TlsInitiatorTransport
from src.core.computers.member_listener import MemberListener, Rendezvous
from src.core.computers.tls_identity import client_link_ctx, ensure_link_identity
from src.core.relay_identity.device_key import DeviceKey
from tests.python.computers.test_tls_link import _Client, _record, _stub_listener

MAIN_IID, MEMBER_IID, GRANT = "main-install-aaaa", "member-install-bbbb", "g1"


@pytest.fixture()
def world():
    root = Path(tempfile.mkdtemp(prefix="lf"))
    idents = {}
    for seed, name in ((1, "main"), (2, "member"), (3, "stranger")):
        (root / name).mkdir(mode=0o700)
        idents[name] = ensure_link_identity(DeviceKey.from_seed(bytes([seed]) * 32), f"{name}-install-xxxx", root / name)
    yield root, idents
    shutil.rmtree(root, ignore_errors=True)


async def _wait(predicate, seconds: float = 5.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_main_dials_the_pinned_member_and_redials_after_a_drop(world):
    root, idents = world
    rendezvous = Rendezvous()
    listener = MemberListener(identity=idents["member"], rendezvous=rendezvous, host="127.0.0.1")
    assert await listener.bind(0)
    await listener.set_pins([idents["main"].cert])
    linked, hellos = [], []
    member_row = store.LinkRow(MEMBER_IID, "member", "tls", "", cert_der=idents["member"].cert.der, cert_sha256=idents["member"].cert.cert_sha256,
                               link_fid=idents["member"].cert.link_fid, addresses=("127.0.0.1",), link_port=listener.port)
    main_row = store.LinkRow(MAIN_IID, "main", "tls", "", cert_der=idents["main"].cert.der, cert_sha256=idents["main"].cert.cert_sha256,
                             link_fid=idents["main"].cert.link_fid)
    cache = store.LinkCache()
    cache.replace([member_row])
    dialer: LinkDialer
    hub = LinkListener(identity=idents["main"], fed_dir=root / "main", listener_path=str(root / "main.sock"), addresses=lambda: ["main.local"],
                       on_link=lambda iid: _record(linked, iid), on_member_hello=lambda iid, a, p: _record(hellos, (iid, a, p)),
                       on_members=lambda members: dialer.set_members(members))
    dialer = LinkDialer(identity=idents["main"], hub=hub, rows=cache.get, backoff=lambda _attempt: 0, stagger=0.05)
    transport = TlsInitiatorTransport(install_id=MEMBER_IID, host_key="peer-main", rendezvous=rendezvous, get_link=lambda: main_row,
                                      listener_path=str(root / "member.sock"), make_client=_Client,
                                      addresses=lambda: ["member.local", "198.51.100.15"], listen_port=lambda: listener.port, control_dir=root)
    stubs = [await _stub_listener(str(root / "main.sock"), "main", []), await _stub_listener(str(root / "member.sock"), "member", [])]
    try:
        await hub.set_members([Member(MEMBER_IID, GRANT, idents["member"].cert)])
        await asyncio.wait_for(transport.settle(), 5)
        await transport.establish()
        assert linked == [MEMBER_IID] and hub.connected() == [MEMBER_IID]
        assert hellos == [(MEMBER_IID, ["member.local", "198.51.100.15"], listener.port)]
        assert dialer.dial_state(MEMBER_IID) == {"state": "linked", "since": None}

        ctx = client_link_ctx(idents["stranger"], [idents["member"].cert])
        reader, writer = await asyncio.open_connection("127.0.0.1", listener.port, ssl=ctx, server_hostname="127.0.0.1")
        try:
            assert await asyncio.wait_for(reader.read(1), 5) == b""
        except OSError:
            pass
        writer.close()
        assert rendezvous.take() is None

        await transport.close()
        await _wait(lambda: not hub.connected())
        await asyncio.wait_for(transport.settle(), 5)
        await transport.establish()
        assert linked == [MEMBER_IID, MEMBER_IID]
    finally:
        await transport.close()
        await dialer.stop()
        await hub.stop()
        await listener.stop()
        for stub in stubs:
            stub.close()

