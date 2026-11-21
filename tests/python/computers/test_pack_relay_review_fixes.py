from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.computers.link_listener import LinkListener, Member, _Conn
from src.core.phone_link import tunnel_client as tc
from src.core.phone_link.gate import LinkStream, StreamTable
from src.core.phone_link.pack_relay import PackAcceptor, PackAdmission


@pytest.mark.asyncio
async def test_acceptor_keeps_its_pins_across_stop_and_start():
    acceptor = PackAcceptor(identity=MagicMock(), hub=MagicMock(), admission=PackAdmission(), table=StreamTable())
    acceptor._ctx, acceptor._shas = object(), frozenset({"abc"})
    await acceptor.start()
    await acceptor.stop()
    assert acceptor._ctx is not None and acceptor._shas == frozenset({"abc"}) and acceptor.port is None


def test_detach_frees_the_slot_of_every_stream_and_stops_trust_sending():
    relay = MagicMock()
    relay.admission = PackAdmission(per_source=2, total=4)
    client = tc.TunnelClient(url="ws://x", session=None, local_port=lambda: None, streams=StreamTable(), pack=relay)
    assert relay.acceptor.send_trust == client.trust
    for sid in (1, 2):
        info = LinkStream(stream_id=sid, client_ip="203.0.113.1", client_port=sid)
        assert relay.admission.enter(info)
        stream = tc._Stream(sid, info, None, None, 0)
        stream.admission = relay.admission
        client._streams[sid] = stream
    assert not relay.admission.enter(LinkStream(stream_id=3, client_ip="203.0.113.1", client_port=3))
    client.detach_pack()
    assert all(not s.info.slot for s in client._streams.values()) and relay.acceptor.send_trust is None
    assert relay.admission.enter(LinkStream(stream_id=4, client_ip="203.0.113.1", client_port=4))


@pytest.mark.asyncio
async def test_a_link_that_missed_the_relay_keys_is_closed_once_when_they_become_owed():
    owed = {"on": False}
    hub = LinkListener(identity=MagicMock(), fed_dir=Path("."), listener_path="x", addresses=lambda: [],
                       hello_extras=lambda iid: {"relay_id": "r"} if owed["on"] else {})
    session = MagicMock()

    async def close(reason: int = 0) -> None:
        session.closed = reason

    session.close = close
    hub._conns["iid"] = _Conn(Member("iid", "g", None), session, "sha", True, announced=False)
    assert await hub.reannounce() == 0
    owed["on"] = True
    assert await hub.reannounce("other") == 0
    assert await hub.reannounce("iid") == 1
    assert await hub.reannounce() == 0
