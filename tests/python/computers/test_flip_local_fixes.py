
from __future__ import annotations

import asyncio
import os
import time

import pytest

from src.core.computers import join_helper, join_job, membership
from tests.python.computers.test_join_commit import JOIN, MAIN, world  # noqa: F401
from tests.python.computers.test_join_doors import _ask, _deps, _door, env  # noqa: F401


def test_the_door_path_check_accepts_only_the_fed_directory_door(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(join_helper, "fed_dir", lambda: tmp_path)
    assert join_helper.door_path_ok(str(tmp_path / "door-1a2b3c4d.sock"))
    for bad in (str(tmp_path / "door-1a2b3c4.sock"), str(tmp_path / "x" / "door-1a2b3c4d.sock"), "/etc/passwd", str(tmp_path / "door-1A2B3C4D.sock")):
        assert not join_helper.door_path_ok(bad)
    assert join_helper.main(["--attach", "--door", "/tmp/door-1a2b3c4d.sock"]) == 2


@pytest.mark.asyncio
async def test_relay_and_relay_fail_name_the_job_and_a_mismatch_is_refused(env, tmp_path):  # noqa: F811
    main, join, srv, invites = env
    await _deps(main, join, srv)
    door = await _door(tmp_path)
    try:
        first = (await _ask(door, {"op": "join", "code": "123456"}))[0]
        assert first["state"] == "waiting_relay"
        status = (await _ask(door, {"op": "status"}))[0]
        job_id = join_job.current_job().id
        assert status["job"] == job_id
        assert (await _ask(door, {"op": "relay_fail", "code": "no_pack"}))[0] == {"error": "bad_request"}
        assert (await _ask(door, {"op": "relay_fail", "job": "other", "code": "no_pack"}))[0] == {"error": "no_join_waiting"}
        assert join_job.current_job().state == "waiting_relay"
        assert (await _ask(door, {"op": "relay_fail", "job": job_id, "code": "no_pack"}))[0]["error"] == "no_pack"
    finally:
        await door.stop()
        await srv.stop()


@pytest.mark.asyncio
async def test_a_held_status_that_closes_ends_the_waiting_job_at_once(env, tmp_path, monkeypatch):  # noqa: F811
    main, join, srv, invites = env
    await _deps(main, join, srv)
    door = await _door(tmp_path)
    try:
        await _ask(door, {"op": "join", "code": "123456"})
        monkeypatch.setattr(join_helper, "door_path", lambda: door.path)
        status, hold = await join_helper.ask_held()
        assert status["state"] == "waiting_relay" and hold is not None
        assert join_job.current_job().state == "waiting_relay"
        hold.close()
        for _ in range(50):
            if join_job.current_job().state != "waiting_relay":
                break
            await asyncio.sleep(0.05)
        assert (join_job.current_job().state, join_job.current_job().error) == ("failed", "no_relay")
    finally:
        await door.stop()
        await srv.stop()


def test_a_stale_relay_socket_is_removed_on_the_next_bind_and_a_fresh_one_stays() -> None:
    import socket
    import tempfile
    from pathlib import Path

    tmp_path = Path(tempfile.mkdtemp(prefix="fx", dir="/tmp"))

    def make(name: str, age: float) -> str:
        path = str(tmp_path / name)
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.close()
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    old, fresh = make("relay-aaaaaaaaaaaaaaaa.sock", 300), make("relay-bbbbbbbbbbbbbbbb.sock", 1)
    sock, path = join_helper.bind_relay(tmp_path)
    sock.close()
    assert not os.path.exists(old) and os.path.exists(fresh)


@pytest.mark.asyncio
async def test_step_connect_prints_before_the_connect(monkeypatch) -> None:
    order = []

    async def held():
        return {"state": "waiting_relay", "job": "J1"}, None

    async def targets(_s):
        return [{"name": "air", "fid": None, "fid_short": None, "addresses": [("127.0.0.1", 1)]}]

    async def refuse(_addrs):
        order.append("connect")
        raise OSError("no")

    async def door(_req):
        return {"state": "failed", "error": "unreachable"}

    monkeypatch.setattr(join_helper, "ask_held", held)
    monkeypatch.setattr(join_helper, "find_targets", targets)
    monkeypatch.setattr(join_helper, "connect_first", refuse)
    monkeypatch.setattr(join_helper, "ask_once", door)
    out = join_helper.Printer(machine=True, agent=False)
    monkeypatch.setattr(out, "step", lambda name, person="": order.append(f"step:{name}"))
    await join_helper.serve(out, first_request=None)
    assert order.index("step:connect") < order.index("connect")


@pytest.mark.asyncio
async def test_terminal_opens_only_for_a_job_this_request_created(monkeypatch) -> None:
    from src.core.computers import terminal_helper

    opened = []

    async def fake(path):
        opened.append(path)
        return True

    monkeypatch.setattr(terminal_helper, "_open_terminal", fake)
    job = join_job.JoinJob(state="waiting_relay", running=True)
    assert await terminal_helper.open_attach(job, created=False) is False and opened == []
