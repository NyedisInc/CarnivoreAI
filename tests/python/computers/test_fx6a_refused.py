
from __future__ import annotations

import asyncio

import pytest
import structlog
import uvloop

from src.core.computers import store
from src.core.computers.link_dialer import REFUSED, LinkDialer
from src.core.computers.link_listener import LinkListener, Member
from src.core.computers.tls_identity import server_join_ctx
from tests.python.computers.test_tls_link import GRANT, MEMBER_IID, _down, _rows, _up, _wait, world  # noqa: F401


@pytest.fixture(params=["asyncio", "uvloop"])
def run(request):
    def go(coro):
        if request.param == "uvloop":
            return uvloop.run(coro)
        return asyncio.run(coro)
    go.kind = request.param
    return go


def test_a_member_rejecting_main_cert_reads_refused_and_logs_the_failure(world, run):  # noqa: F811
    logs = run(_refused_round(world))
    failed = [e for e in logs if e["event"] == "link_handshake_failed"]
    assert failed and all(e.get("error") and e.get("detail") is not None and len(e["detail"]) <= 200 for e in failed)


async def _refused_round(world):  # noqa: F811
    with structlog.testing.capture_logs() as logs:
        up = await _up(world, dialer_ident="evil", backoff=lambda _a: 0.05)
        try:
            await _wait(lambda: (up.dialer.dial_state(MEMBER_IID) or {}).get("state") == REFUSED)
            assert up.linked == [] and up.rendezvous.take() is None
        finally:
            await _down(up)
    return logs


def test_a_connection_that_ends_after_the_handshake_without_an_alert_is_never_refused(world, run):  # noqa: F811
    run(_clean_close_round(world))


async def _clean_close_round(world):  # noqa: F811
    root, dirs, idents = world
    seen = 0

    async def handle(reader, writer):
        nonlocal seen
        seen += 1
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_join_ctx(idents["member"]))
    port = server.sockets[0].getsockname()[1]
    member_row, _main_row = _rows(idents, port)
    cache = store.LinkCache()
    cache.replace([member_row])
    holder: dict = {}
    hub = LinkListener(identity=idents["main"], fed_dir=dirs["main"], listener_path=str(root / "main.sock"), addresses=lambda: [],
                       on_members=lambda members: holder["dialer"].set_members(members))
    dialer = holder["dialer"] = LinkDialer(identity=idents["main"], hub=hub, rows=cache.get, backoff=lambda _a: 0.02, stagger=0.05)
    try:
        await hub.set_members([Member(MEMBER_IID, GRANT, idents["member"].cert)])
        await _wait(lambda: seen >= 5, 8)
        assert (dialer.dial_state(MEMBER_IID) or {}).get("state") != REFUSED
    finally:
        await dialer.stop()
        await hub.stop()
        server.close()


@pytest.mark.parametrize("attempt", range(20))
def test_refused_is_reached_every_time_on_uvloop(world, attempt):  # noqa: F811
    async def body():
        up = await _up(world, dialer_ident="evil", backoff=lambda _a: 0.0)
        try:
            await _wait(lambda: (up.dialer.dial_state(MEMBER_IID) or {}).get("state") == REFUSED, 10)
        finally:
            await _down(up)
    uvloop.run(body())


def _failed_server_handshake(drop_hook: bool):
    import ssl as _ssl
    from src.core.computers.link_listener import AlertingSSLObject

    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    ctx.sslobject_class = AlertingSSLObject
    incoming = _ssl.MemoryBIO()
    obj = ctx.wrap_bio(incoming, _ssl.MemoryBIO(), server_side=True)
    assert isinstance(obj, AlertingSSLObject)
    if drop_hook:
        del obj._link_outgoing
    incoming.write(b"\x16\x03\x01\x00\x05hello" + b"\x00" * 8)
    with pytest.raises(_ssl.SSLError) as caught:
        obj.do_handshake()
    return caught.value, obj


def test_the_alert_hook_still_captures_on_this_python() -> None:
    err, obj = _failed_server_handshake(drop_hook=False)
    assert getattr(obj, "_link_outgoing", None) is not None and getattr(err, "link_alert", b"")[:1] == b"\x15"


def test_a_missing_alert_hook_degrades_to_a_plain_rejected_handshake() -> None:
    from src.core.computers.link_listener import AlertingSSLObject

    AlertingSSLObject._hook_logged = False
    with structlog.testing.capture_logs() as logs:
        err, _obj = _failed_server_handshake(drop_hook=True)
        _failed_server_handshake(drop_hook=True)
    assert not hasattr(err, "link_alert")
    missing = [e for e in logs if e["event"] == "link_alert_hook_missing"]
    assert len(missing) == 1 and missing[0]["error"] and missing[0]["detail"]
