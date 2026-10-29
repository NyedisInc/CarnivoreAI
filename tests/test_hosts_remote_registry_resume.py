
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s7_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s7_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api import restart_routes, routes as routes_mod  # noqa: E402
from src.api import session_rename_routes  # noqa: E402
from src.api.remote_route_guard import routed_remote  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.attention_wiring import build_attention_watcher  # noqa: E402
from src.core.composition import build_services  # noqa: E402
from src.core.hosts.identity import remote_session_id  # noqa: E402
from src.core.hosts.remote_claude_files import files_for  # noqa: E402
from tests.test_hosts_remote_listing import _row, _rows, _twins  # noqa: E402
from tests.test_hosts_remote_sessions import HOST, TMUX, _wait, rig  # noqa: E402,F401

pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")

UUID = "6c38286c-2db9-43b8-859d-19a96acbac98"


def _far_home(rig):
    return rig.fake.root / "home"


async def _pane(rig, name: str) -> dict:
    code, out = await rig.far("list-panes", "-t", f"={name}", "-F",
                              "#{pane_pid} #{session_created} #{pane_dead}")
    assert code == 0, out
    pid, created, dead = out.split()[:3]
    return {"pid": int(pid), "epoch": int(created), "dead": dead}


def _local_pane(mgr, name: str) -> tuple:
    import subprocess

    out = subprocess.run(["tmux", "-L", mgr._tmux_socket_name(), "list-panes", "-t", f"={name}",
                          "-F", "#{pane_pid}|#{pane_start_command}|#{pane_dead}"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return tuple(out.split("|"))


def _write_registry(rig, name: str, pane: dict, status: str = "busy") -> None:
    directory = _far_home(rig) / ".claude" / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    now_ms = int(time.time() * 1000)
    (directory / f"{pane['pid']}.json").write_text(json.dumps({
        "pid": pane["pid"], "sessionId": UUID, "cwd": str(_far_home(rig) / "proj"),
        "startedAt": (pane["epoch"] + 1) * 1000, "status": status,
        "statusUpdatedAt": now_ms, "version": "2.1.266", "tmux": f"{name}:@0.%0",
        "name": "far", "nameSource": "user", "nameSince": now_ms}))


def _transcript_path(rig):
    directory = _far_home(rig) / ".claude" / "projects" / "-far-proj"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{UUID}.jsonl"


def _append(path, *records) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _prompt(ts: str) -> dict:
    return {"type": "user", "isSidechain": False, "timestamp": ts, "sessionId": UUID,
            "message": {"role": "user", "content": "go"}}


def _turn_end(ts: str) -> dict:
    return {"type": "system", "subtype": "turn_duration", "durationMs": 1000, "messageCount": 2,
            "timestamp": ts, "uuid": "6b09440b-7e65-4fae-84b4-0dce91b930c0", "isMeta": False,
            "sessionId": UUID, "version": "2.1.266", "pendingBackgroundAgentCount": 0}


@pytest.mark.asyncio
async def test_the_far_registry_and_transcript_light_the_remote_row_and_bind_its_conversation(rig):
    mgr = rig.mgr
    local, remote = await _twins(rig)
    name = remote.tmux_session
    _write_registry(rig, name, await _pane(rig, name))
    transcript = _transcript_path(rig)
    _append(transcript, _prompt("2026-09-28T09:00:00.000Z"), _turn_end("2026-09-28T09:00:05.000Z"))
    watcher = build_attention_watcher(mgr, tick_seconds=0.0)

    for _ in range(3):
        await watcher.tick_once()
    rows = await _rows(mgr)
    assert (rows[remote.id].activity_status, rows[remote.id].status_source) == (
        "working", "registry")
    near = watcher.observation_for(local.id).evidence
    assert near.registry.verdict == "absent" and rows[local.id].activity_status != "working"
    assert _row(rig, HOST, name)["claude_session_uuid"] == UUID
    assert _row(rig, "local", local.tmux_session)["claude_session_uuid"] is None
    evidence = watcher.observation_for(remote.id).evidence
    assert evidence.registry.known and evidence.transcript.found

    host = await mgr.hosts.get(HOST)
    window = files_for(host)._windows[UUID]
    fetched_from = window.start
    _append(transcript, _prompt("2026-09-28T09:01:00.000Z"))
    await watcher.tick_once()
    window = files_for(host)._windows[UUID]
    assert (window.start, window.end) == (fetched_from, transcript.stat().st_size)
    newest = watcher.observation_for(remote.id).evidence.transcript.newest_user_prompt_at
    assert newest is not None and newest.minute == 1, newest

    (_far_home(rig) / ".claude" / "sessions" / f"{(await _pane(rig, name))['pid']}.json").unlink()
    _write_registry(rig, name, {"pid": 999999, "epoch": (await _pane(rig, name))["epoch"]})
    await watcher.tick_once()
    assert watcher.observation_for(remote.id).evidence.registry.verdict == "stale"


@pytest.mark.asyncio
async def test_respawn_resumes_on_the_far_host_and_never_touches_the_local_twin(rig):
    mgr = rig.mgr
    (_far_home(rig) / "proj").mkdir(exist_ok=True)
    remote = await mgr.create_session(session_id="ses_57aa0001", working_dir="~/proj",
                                      auto_start_claude=True, project_name="s7 resume",
                                      host_key=HOST)
    name = remote.tmux_session
    local = await mgr.create_session(session_id="ses_57bb0001", working_dir=str(rig.state),
                                     auto_start_claude=False, project_name="s7 resume")
    assert local.tmux_session == name
    local_before = _local_pane(mgr, name)
    with rig.db() as conn:
        conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE host_key = ? "
                     "AND tmux_name = ?", (UUID, HOST, name))
        conn.commit()
    _append(_transcript_path(rig), _prompt("2026-09-28T09:00:00.000Z"))
    remote_id = remote_session_id(HOST, name)

    bare = await mgr.respawn_session(name)
    assert bare["kind"] == "not_dead" and bare["session_id"] == local.id

    await mgr.send_input("exit\r", session_id=remote.id)
    await _wait_dead(rig, name)
    result = await mgr.respawn_session(remote_id)
    assert (result["ok"], result["conversation"], result["session_id"]) == (
        True, "resumed", remote.id), result
    assert f"'--resume' '{UUID}'" in result["command"]
    await _wait_far_text(rig, f"fake-claude:--resume {UUID}")
    assert _local_pane(mgr, name) == local_before

    await mgr.send_input("exit\r", session_id=remote.id)
    await _wait_dead(rig, name)
    _transcript_path(rig).unlink()
    refused = await mgr.respawn_session(remote_id)
    assert (refused["kind"], refused["ok"]) == ("transcript_missing", False)
    assert (await _pane(rig, name))["dead"] == "1"
    assert _local_pane(mgr, name) == local_before


async def _wait_dead(rig, name: str) -> None:
    for _ in range(100):
        if (await _pane(rig, name))["dead"] == "1":
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the far pane never died")


async def _wait_far_text(rig, text: str) -> None:
    pipes = _far_home(rig) / ".cache" / "carnivore" / "pipes"
    for _ in range(100):
        if any(text in p.read_text(errors="replace") for p in pipes.glob("*.pipe")):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{text!r} never reached the far pane")


def _app(mgr) -> FastAPI:
    app = FastAPI()
    app.state.session_manager = mgr
    app.state.services = build_services(session_manager=mgr)
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.include_router(restart_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return app


def _local_fingerprint(rig, mgr, local) -> tuple:
    row = _row(rig, "local", local.tmux_session)
    return (_local_pane(mgr, local.tmux_session), row["title"], row["claude_session_uuid"],
            row["lifecycle"], mgr._theme_store.pinned_themes.get(local.tmux_session))


@pytest.mark.asyncio
async def test_every_host_unaware_route_refuses_a_remote_session_and_spares_the_twin(rig):
    mgr = rig.mgr
    local, remote = await _twins(rig)
    name, rid = remote.tmux_session, remote_session_id(HOST, remote.tmux_session)
    before = _local_fingerprint(rig, mgr, local)
    refused = [
        ("GET", f"/sessions/{remote.id}/pane-facts", {}),
        ("GET", f"/sessions/{remote.id}/subagents", {}),
        ("GET", f"/sessions/{remote.id}/timers", {}),
        ("GET", f"/sessions/{remote.id}/token-usage", {}),
        ("POST", f"/sessions/{rid}/fork", {}),
        ("POST", "/sessions/adopt", {"json": {"session_name": rid}}),
        ("POST", "/sessions/upload-file", {"params": {"session_id": remote.id},
                                           "files": {"file": ("a.txt", b"x", "text/plain")}}),
    ]
    transport = httpx.ASGITransport(app=_app(mgr))
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
        for method, path, kwargs in refused:
            resp = await client.request(method, path, **kwargs)
            assert resp.status_code == 409, (method, path, resp.status_code, resp.text)
            assert resp.json()["detail"]["code"] == "remote_host", (method, path)
        put = await client.put(f"/sessions/{rid}/note", json={"body": "far", "expected_revision": 0})
        assert put.status_code == 200, put.text
        assert (await client.get(f"/sessions/{rid}/note")).json()["body"] == "far"
        assert (await client.get(f"/sessions/{local.tmux_session}/note")).json()["revision"] == 0
        resp = await client.post("/sessions/respawn", json={"session_name": rid})
        assert (resp.status_code, resp.json()["kind"], resp.json()["session_id"]) == (
            200, "not_dead", remote.id)
    assert _local_fingerprint(rig, mgr, local) == before

    session_rename_routes.routed_remote = lambda *_a, **_k: None
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
            await client.patch(f"/sessions/{remote.id}/name", json={"new_name": "hijack"})
    finally:
        session_rename_routes.routed_remote = routed_remote
    assert _row(rig, "local", local.tmux_session)["title"] == "hijack"


@pytest.mark.asyncio
async def test_a_far_session_ended_outside_is_stopped_only_when_measured_gone(rig):
    mgr = rig.mgr
    local, remote = await _twins(rig)
    name = remote.tmux_session
    host = await mgr.hosts.get(HOST)
    code, _ = await rig.far("kill-session", "-t", f"={name}")
    assert code == 0

    rig.fake.set("scenario", "unreachable")
    await host.channel.stop()
    try:
        await _rows(mgr)
        assert _row(rig, HOST, name)["lifecycle"] == "running"
    finally:
        rig.fake.set("scenario", "ok")
        await host.channel.start()
    await _wait(lambda: host.is_up, what="the host to come back")

    await _rows(mgr)
    assert _row(rig, HOST, name)["lifecycle"] == "stopped"
    assert _row(rig, "local", local.tmux_session)["lifecycle"] == "running"
