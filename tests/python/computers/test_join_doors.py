
from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_jd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_jd_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

from tests.python.computers.test_join_commit import JOIN, MAIN, Side, _pair_over_ssh, world  # noqa: F401, E402

import src.api.auth as auth_mod  # noqa: E402
from src.api import join_local_routes  # noqa: E402
from src.config import settings  # noqa: E402
from src.core import setup_state  # noqa: E402
from src.core.computers import join_job, membership, store  # noqa: E402
from src.core.computers.door import Door  # noqa: E402
from src.core.computers.invites import Invites  # noqa: E402
from src.core.computers.join_job import JoinDeps  # noqa: E402
from src.core.computers.join_server import JoinServer  # noqa: E402

PORT = settings.port
SENTINEL = setup_state.PAIRED_SENTINEL_NAME


@pytest.fixture()
def env(world, monkeypatch):
    main, join = world
    monkeypatch.setattr(settings, "auth_config_file", str(join.config))
    settings.drop_auth_config_cache()
    monkeypatch.setattr(membership, "_join_running", False)
    monkeypatch.setattr(join_job, "_job", None)
    invites = Invites()
    srv = JoinServer(invites=invites, identity=main.identity, fed_key=main.key, public_key=main.public, own_iid=MAIN, own_label="air",
                     open_db=main.open_db, listener=main.listener, pack=main.pack, host="127.0.0.1", port=0,
                     addresses=lambda: ["127.0.0.1"], link_port=47110, app_version="t", fail_delay=0.0, lan_only=False)
    yield main, join, srv, invites
    join_job.configure_join(None)
    settings.drop_auth_config_cache()
    store.CACHE.replace([])


async def _deps(main: Side, side: Side, srv: JoinServer, **over) -> JoinDeps:
    held: dict = {}

    async def reserve():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        held["sock"] = sock
        return sock.getsockname()[1]

    async def release():
        sock = held.pop("sock", None)
        if sock is not None:
            sock.close()

    deps = JoinDeps(identity=side.identity, fed_key=side.key, public_key=side.public, own_iid=JOIN, own_label="hosta", open_db=side.open_db,
                    links=side.links, pack=side.pack, reserve_port=reserve, release_port=release, addresses=lambda: ["hosta.local"],
                    app_version="t", **over)
    deps.held = held  # type: ignore[attr-defined]
    join_job.configure_join(deps)
    return deps


async def relay_join(door: Door, srv: JoinServer, main: Side, monkeypatch, req: dict, mains=None) -> list:
    from src.core.computers import join_helper

    first = await _ask(door, req)
    if first[-1].get("state") != "waiting_relay":
        return first

    async def targets(_status):
        return mains if mains is not None else [{"name": "air", "fid": main.key.device_id, "fid_short": main.key.device_id[:6], "addresses": [("127.0.0.1", srv.port)]}]

    monkeypatch.setattr(join_helper, "door_path", lambda: door.path)
    monkeypatch.setattr(join_helper, "find_targets", targets)
    await asyncio.to_thread(join_helper.main, ["--attach"])
    return first + await _ask(door, {"op": "status"})


async def _door(tmp_path, totp_ok=False) -> Door:
    async def totp(code: str) -> bool:
        return totp_ok and code == "654321"

    async def login(_store):
        return {"access_token": "a", "refresh_token": "r", "expires_in": 1}

    door = Door(os.path.join(tempfile.mkdtemp(prefix="jd", dir="/tmp"), "d.sock"), totp_ok=totp, login=login, setup_status=lambda: "complete")
    await door.start()
    return door


async def _ask(door: Door, req: dict) -> list:
    reader, writer = await asyncio.open_unix_connection(door.path)
    writer.write(json.dumps(req).encode() + b"\n")
    await writer.drain()
    out = [json.loads(line) async for line in reader]
    writer.close()
    return out


@pytest.mark.asyncio
async def test_door_join_on_paired_needs_the_owner_for_a_new_main_and_allows_a_rejoin(env, tmp_path, monkeypatch):
    main, join, srv, invites = env
    (join.dir / SENTINEL).write_text("x")
    inv = invites.mint("code")
    await srv.sync()
    await _deps(main, join, srv)
    door = await _door(tmp_path)
    try:
        lines = await relay_join(door, srv, main, monkeypatch, {"op": "join", "code": inv.code})
        assert lines[0]["state"] == "waiting_relay" and lines[-1]["state"] == "failed" and lines[-1]["error"] == "needs_owner"
        assert inv.attempts_left == 3 or inv.attempts_left == 2
        assert store.CACHE.rows() == [] and main.listener.sets == []
        lines = await _ask(door, {"op": "join", "code": inv.code, "totp": "000000"})
        assert lines == [{"error": "bad_totp"}]
    finally:
        await door.stop()
    _pair_over_ssh(main, join)
    inv2 = invites.mint("code")
    await srv.sync()
    await _deps(main, join, srv)
    door = await _door(tmp_path)
    try:
        lines = await relay_join(door, srv, main, monkeypatch, {"op": "join", "code": inv2.code})
        assert lines[-1]["state"] == "joined" and lines[-1]["main_label"] == "air"
        assert [(r.peer_install_id, r.join_kind) for r in store.CACHE.rows()] == [(MAIN, "migrate")]
    finally:
        await door.stop()
        await srv.stop()


@pytest.mark.asyncio
async def test_door_join_on_paired_with_a_valid_code_joins_a_new_main(env, tmp_path, monkeypatch):
    main, join, srv, invites = env
    (join.dir / SENTINEL).write_text("x")
    inv = invites.mint("code")
    await srv.sync()
    await _deps(main, join, srv)
    door = await _door(tmp_path, totp_ok=True)
    try:
        lines = await relay_join(door, srv, main, monkeypatch, {"op": "join", "code": inv.code, "totp": "654321"})
        assert lines[-1]["state"] == "joined"
        assert [(r.peer_install_id, r.join_kind) for r in store.CACHE.rows()] == [(MAIN, "new")]
        again = await relay_join(door, srv, main, monkeypatch, {"op": "join", "code": inv.code})
        assert again[-1]["state"] == "joined"
    finally:
        await door.stop()
        await srv.stop()


@pytest.mark.asyncio
async def test_door_login_only_when_joined(env, tmp_path):
    main, join, srv, _inv = env
    door = await _door(tmp_path)
    try:
        assert await _ask(door, {"op": "login"}) == [{"error": "not_joined"}]
        assert (await _ask(door, {"op": "status"}))[0]["joined"] is False
        setup_state.joined_marker_path(join.config).touch()
        assert await _ask(door, {"op": "login"}) == [{"access_token": "a", "refresh_token": "r", "expires_in": 1}]
        assert (await _ask(door, {"op": "status"}))[0]["joined"] is True
        assert await _ask(door, {"op": "join", "code": "123456"}) == [{"error": "already_joined"}]
        assert await _ask(door, {"op": "leave"}) == [{"error": "bad_request"}]
    finally:
        await door.stop()


@pytest.mark.asyncio
async def test_two_start_join_calls_return_one_job(env):
    main, join, srv, _inv = env
    gate = asyncio.Event()
    calls = []

    async def slow_join(**kw):
        calls.append(kw["relay_path"])
        await gate.wait()
        raise join_job.JoinFailed("unreachable")

    deps = await _deps(main, join, srv, join=slow_join)
    first = membership.start_join("123456", None, origin="local", totp_ok=False)
    second = membership.start_join("654321", None, origin="door", totp_ok=False)
    assert first is second and first.state == "waiting_relay" and membership.first_run_state() == "join_pending"
    await join_job.attach_relay("/relay.sock", "192.0.2.13", None)
    await asyncio.sleep(0.05)
    assert membership.start_join("111111", None, origin="door", totp_ok=False) is first
    gate.set()
    await first_done(first)
    assert calls == ["/relay.sock"] and first.error == "unreachable" and membership.first_run_state() == "unpaired"
    assert "sock" not in deps.held
    with pytest.raises(join_job.JoinNotAllowed):
        membership.start_join("12", None, origin="local", totp_ok=False)


async def first_done(job) -> None:
    for _ in range(100):
        if not job.running:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("job did not end")


def test_local_routes_gate_on_transport_and_state(env):
    main, join, srv, _inv = env
    auth_mod.limiter.reset()
    app = FastAPI()
    app.state.limiter = auth_mod.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(join_local_routes.router, prefix="/api/v1")
    local = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000))
    remote = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("192.0.2.15", 50000))
    assert remote.get("/api/v1/auth/join/status").status_code == 403
    assert remote.get("/api/v1/auth/join/status").json()["detail"] == {"reason": "join_local_only"}
    assert local.get("/api/v1/auth/join/status", headers={"Authorization": "Bearer x"}).status_code == 403
    got = local.get("/api/v1/auth/join/status")
    assert got.status_code == 200 and got.json()["state"] == "idle" and got.headers["cache-control"] == "no-store"
    assert local.get("/api/v1/auth/join/candidates").json() == {"candidates": []}
    assert local.post("/api/v1/auth/join", json={"code": "12"}).status_code in (422, 503)
    assert local.post("/api/v1/auth/join", json={"link": "nope"}).status_code in (422, 503)
    (join.dir / SENTINEL).write_text("x")
    assert local.get("/api/v1/auth/join/status").status_code == 409
    assert local.post("/api/v1/auth/join", json={"code": "123456"}).json()["detail"] == {"reason": "not_joinable"}
    (join.dir / SENTINEL).unlink()
    setup_state.joined_marker_path(join.config).touch()
    assert local.get("/api/v1/auth/join/candidates").status_code == 409


def test_the_phone_link_may_not_join_add_remove_or_leave_but_may_list_and_mint():
    from src.core.phone_link.gate import is_denied

    for path in ("/api/v1/auth/join", "/api/v1/auth/join/status", "/api/v1/computers/add", "/api/v1/computers/peers/x",
                 "/api/v1/computers/join", "/api/v1/computers/leave"):
        assert is_denied(path), path
    for path in ("/api/v1/computers", "/api/v1/computers/invites", "/api/v1/computers/invites/abc"):
        assert not is_denied(path), path


def test_the_window_polls_linking_then_joined_through_the_status_route(env, monkeypatch):
    main, join, srv, _inv = env
    auth_mod.limiter.reset()
    app = FastAPI()
    app.state.limiter = auth_mod.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(join_local_routes.router, prefix="/api/v1")
    local = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000))
    state = {"v": "join_pending"}
    monkeypatch.setattr(join_job, "first_run_state", lambda: state["v"])
    monkeypatch.setattr(membership, "first_run_state", lambda: state["v"])
    job = join_job.JoinJob(state="waiting_relay")
    monkeypatch.setattr(join_job, "_job", job)
    assert local.get("/api/v1/auth/join/status").json()["state"] == "waiting_relay"
    job.state, job.main_label = "joined", "air"
    got = local.get("/api/v1/auth/join/status")
    assert got.status_code == 200 and got.json()["state"] == "linking"
    state["v"] = "joined"
    got = local.get("/api/v1/auth/join/status")
    assert got.status_code == 200 and got.json()["state"] == "joined" and got.json()["main_label"] == "air"
    assert local.post("/api/v1/auth/join", json={"code": "123456"}).status_code == 409
