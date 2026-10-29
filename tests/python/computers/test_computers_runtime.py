
from __future__ import annotations

import json
import os
import socket
import tempfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from tests.python.computers.test_join_commit import JOIN, MAIN, Side, _join_prov, _main_prov, world  # noqa: F401

# ruff: noqa: E402
from src.core import setup_state
from src.core.computers import join_job, runtime, store
from src.core.computers.link_transport import TlsInitiatorTransport
from src.core.federation import fed_key
from src.core.federation.peer_links import PeerLinks


def _state(complete: bool = True, joined: bool = False) -> setup_state.SetupState:
    return setup_state.SetupState(status=setup_state.SETUP_COMPLETE if complete else setup_state.SETUP_INCOMPLETE, checks=(), joined=joined)


def _free_pair() -> int:
    while True:
        with socket.socket() as a, socket.socket() as b:
            a.bind(("127.0.0.1", 0))
            port = a.getsockname()[1]
            try:
                b.bind(("127.0.0.1", port + 1))
            except OSError:
                continue
            return port


def _runtime(side: Side, monkeypatch, *, host: str = "0.0.0.0", complete: bool = True, joined: bool = False) -> runtime.ComputersRuntime:
    monkeypatch.setattr(fed_key, "load_key", lambda _iid: side.key)
    monkeypatch.setattr(runtime, "local_addresses", lambda: ["air.local"])
    side.config.write_text(json.dumps({"computers": {"link_port": _free_pair()}}))

    async def totp(_code: str) -> bool:
        return False

    async def login(_store):
        return {}

    return runtime.ComputersRuntime(
        open_db=side.open_db, pack=side.pack, fed_dir=side.dir, listener_path=os.path.join(side.dir, "peer.sock"), config_path=side.config,
        host=host, label="air", app_version="t", door_path=os.path.join(tempfile.mkdtemp(prefix="rt", dir="/tmp"), "d.sock"),
        door_totp_ok=totp, door_login=login, setup_state_fn=lambda: _state(complete, joined),
        control_dir=Path(tempfile.mkdtemp(prefix="cm")))


@pytest.mark.asyncio
async def test_a_stored_member_row_starts_a_tls_transport_before_boot(world, monkeypatch):
    main, join = world
    res = await _main_prov(main, join, "new")
    await _join_prov(main, join, res, "new")
    store.CACHE.replace([])
    monkeypatch.setattr(fed_key, "load_key", lambda _iid: join.key)
    links = PeerLinks(open_db=join.open_db, listener_path=os.path.join(join.dir, "peer.sock"))
    links.use_key(join.key)
    rt = _runtime(join, monkeypatch)
    assert links.transport_factory is None
    await rt.prepare(links)
    assert links.transport_factory is not None and store.CACHE.tls_main_for(MAIN) is not None
    await links.boot()
    try:
        assert isinstance(links._transports[MAIN], TlsInitiatorTransport)
    finally:
        await links.shutdown()


@pytest.mark.asyncio
async def test_listener_follows_the_rule_and_lp_follows_the_state(world, monkeypatch):
    main, join = world
    await _main_prov(main, join, "new")
    cases = [
        (("0.0.0.0", True, False), ("dialing", True)),
        (("0.0.0.0", False, False), ("stopped", False)),
        (("0.0.0.0", True, True), ("stopped", False)),
        (("127.0.0.1", True, False), ("off_loopback", False)),
    ]
    for (host, complete, joined), (state, has_lp) in cases:
        rt = _runtime(main, monkeypatch, host=host, complete=complete, joined=joined)
        await rt.prepare(PeerLinks(open_db=main.open_db, listener_path=rt._listener_path))
        await rt.start()
        try:
            assert (rt.link_state, rt.advertised_port() == rt.link_port, runtime.advertised_link_port() == rt.advertised_port()) == (
                state, has_lp, True), (host, complete, joined)
            if state in ("dialing", "off_loopback") and complete and not joined:
                assert rt.listener.state == "dialing"
        finally:
            await rt.stop()
        assert runtime.active() is None and runtime.advertised_link_port() is None


@pytest.mark.asyncio
async def test_join_port_door_and_job_follow_the_runtime(world, monkeypatch):
    main, _join = world
    rt = _runtime(main, monkeypatch)
    await rt.prepare(PeerLinks(open_db=main.open_db, listener_path=rt._listener_path))
    await rt.start()
    try:
        assert os.path.exists(rt.door.path) and join_job._deps is not None and rt.join_server.port is None
        rt.invites.mint()
        await rt.join_server.sync()
        assert rt.join_server.port == rt.link_port + 1
        for inv in rt.invites.live():
            rt.invites.cancel(inv.id)
        await rt.join_server.sync()
        assert rt.join_server.port is None
    finally:
        await rt.stop()
    assert join_job._deps is None and not os.path.exists(rt.door.path)


@pytest.mark.asyncio
async def test_slow_tick_reverts_a_provisional_member_and_unpins_it(world, monkeypatch):
    main, join = world
    await _main_prov(main, join, "new")
    rt = _runtime(main, monkeypatch)
    await rt.prepare(PeerLinks(open_db=main.open_db, listener_path=rt._listener_path))
    await rt.start()
    try:
        assert rt.link_state == "dialing"
        with closing(main.open_db()) as conn:
            row = store.get(conn, JOIN)
            store.put(conn, replace(row, joined_at="2020-01-01T00:00:00.000000Z"))
        await rt._slow_tick()
        assert main.query(lambda c: store.list_rows(c)) == [] and rt.link_state == "stopped" and rt.last_pins == ()
    finally:
        await rt.stop()


def test_link_port_reads_config_and_rejects_nonsense(tmp_path):
    cfg = tmp_path / "config.json"
    assert runtime.read_link_port(cfg) == 47110
    for value, want in ((50000, 50000), (0, 47110), (70000, 47110), ("47200", 47110), (True, 47110)):
        cfg.write_text(json.dumps({"computers": {"link_port": value}}))
        assert runtime.read_link_port(cfg) == want
