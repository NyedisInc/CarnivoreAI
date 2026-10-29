
from __future__ import annotations

import asyncio
import ssl
import tempfile
from contextlib import closing

import pytest

from tests.python.computers.test_join_commit import JOIN, MAIN, Side, world  # noqa: F401

# ruff: noqa: E402, F811
from src.core.computers import join_client, join_proto, store
from src.core.computers.invites import Invites
from src.core.computers.join_client import JoinFailed
from src.core.computers.join_proto import JoinPake
from src.core.computers.join_server import JoinServer
from src.core.computers.tls_identity import client_join_ctx
from src.core.federation import grants, peer_hosts


def _server(main: Side, invites: Invites) -> JoinServer:
    return JoinServer(invites=invites, identity=main.identity, fed_key=main.key, public_key=main.public, own_iid=MAIN, own_label="air",
                      open_db=main.open_db, listener=main.listener, pack=main.pack, host="127.0.0.1", port=0,
                      addresses=lambda: ["127.0.0.1"], link_port=47110, app_version="t", fail_delay=0.0, lan_only=False)


async def _join(main: Side, join: Side, port: int, **kw):
    path = tempfile.mkdtemp(prefix="jr", dir="/tmp") + "/r.sock"

    async def pipe(reader, writer):
        up_r, up_w = await asyncio.open_connection("127.0.0.1", port)

        async def copy(r, w):
            try:
                while data := await r.read(65536):
                    w.write(data)
                    await w.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                w.close()

        await asyncio.gather(copy(reader, up_w), copy(up_r, writer))

    server = await asyncio.start_unix_server(pipe, path=path)
    try:
        return await join_client.join(relay_path=path, listen_port=47200, listen_addresses=["studio.local"], identity=join.identity, fed_key=join.key,
                                      public_key=join.public, own_iid=JOIN, own_label="studio", open_db=join.open_db, links=join.links, pack=join.pack, **kw)
    finally:
        server.close()


def _rows(side: Side):
    return side.query(lambda c: (store.list_rows(c), grants.list_grants(c), peer_hosts.list_peers(c)))


@pytest.mark.asyncio
async def test_right_code_joins_and_the_port_closes_with_the_last_invite(world):
    main, join = world
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    assert await srv.sync() and srv.port
    out = await _join(main, join, srv.port, mode="code", code=inv.code)
    assert (out.main_install_id, out.kind) == (MAIN, "new")
    m_links, m_grants, m_hosts = _rows(main)
    j_links, j_grants, j_hosts = _rows(join)
    assert [(r.peer_install_id, r.role, r.provisional) for r in m_links] == [(JOIN, "member", True)]
    assert [(r.peer_install_id, r.role, r.provisional) for r in j_links] == [(MAIN, "main", True)]
    assert len(m_grants) == len(j_grants) == 1 and len(m_hosts) == len(j_hosts) == 1
    assert join.links.started == [MAIN] and main.listener.sets[-1] == [JOIN]
    assert not invites.any_live() and await srv.sync() is False and srv.port is None


@pytest.mark.asyncio
async def test_three_wrong_codes_kill_the_invite_and_a_fourth_right_one_gets_no_invite(world):
    main, join = world
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    await srv.sync()
    right = inv.code
    wrong = "000000" if right != "000000" else "111111"
    lefts = []
    for _ in range(3):
        with pytest.raises(JoinFailed) as bad:
            await _join(main, join, srv.port, mode="code", code=wrong)
        assert bad.value.code == "wrong_code"
        lefts.append(bad.value.left)
    assert lefts == [2, 1, 0]
    with pytest.raises(JoinFailed) as gone:
        await _join(main, join, srv.port, mode="code", code=right)
    assert gone.value.code == "no_invite"
    assert _rows(main) == ([], [], []) and _rows(join) == ([], [], []) and not invites.any_live()


@pytest.mark.asyncio
async def test_link_mode_joins_and_a_wrong_cert_prefix_spends_no_attempt(world):
    main, join = world
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    await srv.sync()
    with pytest.raises(JoinFailed) as bad:
        await _join(main, join, srv.port, mode="invite", secret=inv.secret, invite_id=inv.id, expect_cert_k="0" * 32)
    assert bad.value.code == "main_mismatch" and inv.attempts_left == 3
    k = main.identity.cert.cert_sha256[:32]
    out = await _join(main, join, srv.port, mode="invite", secret=inv.secret, invite_id=inv.id, expect_cert_k=k)
    assert out.kind == "new" and len(_rows(main)[0]) == 1


async def _raw(port: int):
    return await asyncio.open_connection("127.0.0.1", port, ssl=client_join_ctx())


async def _send_hello(w, code: str, fid: str = "f" * 26) -> None:
    w.write(join_proto.MAGIC)
    await join_proto.write_message(w, join_proto.hello(mode="code", msg_a=JoinPake("joiner", join_proto.password("code", code=code)).start(), fid=fid))


@pytest.mark.asyncio
async def test_busy_only_after_a_valid_message_1_and_spends_nothing(world):
    main, _join_side = world
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    await srv.sync()
    ra, wa = await _raw(srv.port)
    await _send_hello(wa, inv.code)
    for _ in range(50):
        if inv.attempts_left == 2:
            break
        await asyncio.sleep(0.02)
    assert inv.attempts_left == 2
    rb, wb = await _raw(srv.port)
    wb.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    await wb.drain()
    try:
        assert await asyncio.wait_for(rb.read(), 3) == b""
    except (ssl.SSLError, ConnectionError):
        pass
    rc, wc = await _raw(srv.port)
    await _send_hello(wc, inv.code)
    reply = await join_proto.read_message(rc, 3)
    assert reply == {"t": "error", "code": "busy"} and inv.attempts_left == 2
    for w in (wa, wb, wc):
        w.close()


@pytest.mark.asyncio
async def test_a_joiner_with_another_grant_aborts_refused_before_message_5(world):
    main, join = world
    with closing(join.open_db()) as c:
        grants.create_grant(c, peer_install_id="third-install-cccc", public_key=main.public, label="third", remote_grant_id="gx", grant_id="gy")
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    await srv.sync()
    with pytest.raises(JoinFailed) as bad:
        await _join(main, join, srv.port, mode="code", code=inv.code)
    assert bad.value.code == "join_has_peers"
    for _ in range(50):
        if inv.attempts_left == 3:
            break
        await asyncio.sleep(0.02)
    assert inv.attempts_left == 3 and invites.any_live()
    assert _rows(main) == ([], [], []) and join.links.started == []
