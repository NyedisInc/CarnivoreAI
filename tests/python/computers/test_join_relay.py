
from __future__ import annotations

import glob
import os

import pytest
import structlog

from tests.python.computers.test_join_commit import JOIN, MAIN, world  # noqa: F401
from tests.python.computers.test_join_doors import _ask, _deps, _door, env, relay_join  # noqa: F401

# ruff: noqa: E402, F811
from src.core.computers import join_job, join_proto, store
from src.core.computers.join_proto import JoinPake
from src.core.computers.tls_identity import client_join_ctx


async def _v1_hello(port: int) -> dict:
    import asyncio

    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=client_join_ctx(), server_hostname="")
    writer.write(join_proto.MAGIC)
    hello = join_proto.hello(mode="code", msg_a=JoinPake("joiner", b"x" * 8).start(), fid="f" * 26)
    await join_proto.write_message(writer, {**hello, "v": 1})
    reply = await join_proto.read_message(reader, join_proto.MESSAGE_TIMEOUT)
    writer.close()
    return reply


@pytest.mark.asyncio
async def test_a_join_through_the_helper_relay(env, tmp_path, monkeypatch):
    main, join, srv, invites = env
    inv = invites.mint("code")
    await srv.sync()
    deps = await _deps(main, join, srv)
    door = await _door(tmp_path)
    saved = structlog.get_config()
    try:
        status = (await _ask(door, {"op": "status"}))[0]
        assert status["join_relay"] == 1 and "targets" not in status

        reply = await _v1_hello(srv.port)
        assert reply == {"t": "error", "code": "incompatible"} and inv.attempts_left == 3

        lines = await relay_join(door, srv, main, monkeypatch, {"op": "join", "code": inv.code})
        assert lines[0]["state"] == "waiting_relay"
        assert lines[-1]["state"] == "joined" and lines[-1]["main_label"] == "air" and lines[-1]["error"] is None
        assert join_job.current_job().state == "joined"

        member = next(r for r in main.query(store.list_rows) if r.peer_install_id == JOIN)
        reserved = next(r for r in join.query(store.list_rows) if r.peer_install_id == MAIN).link_port
        assert member.link_port == reserved and reserved is not None
        assert list(member.addresses) == ["hosta.local", "127.0.0.1"]
        mains = [r for r in join.query(store.list_rows) if r.role == "main"]
        assert [(r.peer_install_id, r.link_port, tuple(r.addresses)) for r in mains] == [(MAIN, reserved, ())]
        assert glob.glob(os.path.join(os.path.dirname(door.path), "relay-*")) == []
        assert "sock" not in deps.held
    finally:
        structlog.configure(**saved)
        await door.stop()
        await srv.stop()
