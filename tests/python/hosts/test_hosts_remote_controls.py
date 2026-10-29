
from __future__ import annotations

import os
import tempfile

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_1048_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_1048_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api import restart_routes, routes as routes_mod  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.composition import build_services  # noqa: E402
from src.core.hosts.identity import remote_session_id  # noqa: E402
from src.core.sessions.background_store import SessionBackgroundStore  # noqa: E402
from tests.test_hosts_remote_listing import _row, _rows, _twins  # noqa: E402
from tests.test_hosts_remote_registry_resume import (  # noqa: E402
    UUID, _append, _local_pane, _pane, _prompt, _transcript_path)
from tests.test_hosts_remote_sessions import HOST, TMUX, _wait, rig  # noqa: E402,F401

pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4a40000000049454e44ae426082")


def _app(rig) -> FastAPI:
    app = FastAPI()
    app.state.session_manager = rig.mgr
    app.state.services = build_services(session_manager=rig.mgr)
    app.state.session_background_store = SessionBackgroundStore(
        path=lambda: rig.state / "session_backgrounds.json")
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.include_router(restart_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return app


def _fields(row: dict) -> tuple:
    return tuple(row[k] for k in ("id", "title", "lifecycle", "tmux_created_epoch",
                                  "claude_session_uuid", "host_key"))


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1")


@pytest.mark.asyncio
async def test_rename_theme_background_and_preview_act_on_the_host_and_spare_the_twin(rig):
    from src.config import settings

    mgr = rig.mgr
    local, remote = await _twins(rig)
    name, rid = remote.tmux_session, remote_session_id(HOST, remote.tmux_session)
    local_pane = _local_pane(mgr, name)
    app = _app(rig)
    async with _client(app) as client:
        for target, label in ((remote.id, "far one"), (rid, "far two")):
            resp = await client.patch(f"/sessions/{target}/name", json={"new_name": label})
            assert resp.status_code == 200, resp.text
            assert (_row(rig, HOST, name)["title"], _row(rig, "local", name)["title"]) == (
                label, "near")
        resp = await client.patch(f"/sessions/{local.id}/name", json={"new_name": "near two"})
        assert resp.status_code == 200, resp.text
        assert (_row(rig, HOST, name)["title"], _row(rig, "local", name)["title"]) == (
            "far two", "near two")
        missing = await client.patch(f"/sessions/remote:{HOST}:nosuch/name",
                                     json={"new_name": "x"})
        assert missing.status_code == 404

        resp = await client.patch(f"/sessions/{rid}/theme", json={"theme_id": "metal"})
        assert resp.status_code == 200, resp.text
        assert (resp.json()["pinned_theme"], resp.json()["host_key"]) == ("metal", HOST)
        resp = await client.patch(f"/sessions/{name}/theme", json={"theme_id": "nord"})
        assert resp.status_code == 200, resp.text
        assert mgr._theme_store.pinned_themes == {rid: "metal", name: "nord"}
        rows = await _rows(mgr)
        assert (rows[remote.id].pinned_theme, rows[local.id].pinned_theme) == ("metal", "nord")
        resp = await client.patch(f"/sessions/{rid}/pinned-theme", json={"pinned_theme": None})
        assert resp.status_code == 200, resp.text
        rows = await _rows(mgr)
        assert (rows[remote.id].pinned_theme, rows[local.id].pinned_theme) == (None, "nord")

        resp = await client.patch(f"/sessions/{rid}/background", json={"disabled": True})
        assert resp.status_code == 200, resp.text
        put = await client.put(f"/sessions/{rid}/background/image",
                               files={"file": ("p.png", PNG, "image/png")})
        assert put.status_code == 200, put.text
        assert put.json()["image"].startswith("remote-")
        got = await client.get(f"/sessions/{rid}/background/image")
        assert (got.status_code, got.content) == (200, PNG)
        overrides = (await client.get("/session-backgrounds")).json()["overrides"]
        assert rid in overrides and name not in overrides
        assert (await client.get(f"/sessions/{name}/background/image")).status_code == 404
        assert (await client.delete(f"/sessions/{rid}/background/image")).status_code == 204
        images = settings.get_session_background_images_dir()
        assert str(images).startswith(str(rig.state)) and not list(images.iterdir())

        far = await client.get("/sessions/restart/preview", params={"session_name": rid})
        assert far.status_code == 200, far.text
        assert (far.json()["name"], far.json()["pane_state"], far.json()["options"]) == (
            rid, "alive", [])
        near = await client.get("/sessions/restart/preview", params={"session_name": name})
        assert (near.status_code, near.json()["name"]) == (200, name)
    assert _local_pane(mgr, name) == local_pane


@pytest.mark.asyncio
async def test_a_stopped_remote_row_restarts_on_its_host_only_when_measured_gone(rig):
    mgr = rig.mgr
    (rig.fake.root / "home" / "proj").mkdir(exist_ok=True)
    remote = await mgr.create_session(session_id="ses_10480001", working_dir="~/proj",
                                      auto_start_claude=True, project_name="p2 restart",
                                      label="far", host_key=HOST)
    name = remote.tmux_session
    local = await mgr.create_session(session_id="ses_10480002", working_dir=str(rig.state),
                                     auto_start_claude=False, project_name="p2 restart")
    assert local.tmux_session == name
    local_pane, local_row = _local_pane(mgr, name), _row(rig, "local", name)
    with rig.db() as conn:
        conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE host_key = ? "
                     "AND tmux_name = ?", (UUID, HOST, name))
        conn.commit()
    transcript = _transcript_path(rig)
    _append(transcript, _prompt("2026-09-28T09:00:00.000Z"))
    far_row = _row(rig, HOST, name)
    uuid = far_row["session_uuid"]
    host = await mgr.hosts.get(HOST)
    app = _app(rig)

    async with _client(app) as client:
        running = await client.post(f"/sessions/{uuid}/restart")
        assert running.status_code == 409, running.text
        assert running.json()["detail"]["code"] == "session_already_running"

        code, _ = await rig.far("kill-session", "-t", f"={name}")
        assert code == 0
        await _rows(mgr)
        assert _row(rig, HOST, name)["lifecycle"] == "stopped"

        rig.fake.set("scenario", "unreachable")
        await host.channel.stop()
        try:
            refused = await client.post(f"/sessions/{uuid}/restart")
            assert refused.status_code in (502, 503), refused.text
        finally:
            rig.fake.set("scenario", "ok")
            await host.channel.start()
        await _wait(lambda: host.is_up, what="the host to come back")
        assert (await rig.far("has-session", "-t", f"={name}"))[0] != 0

        moved = transcript.with_suffix(".away")
        transcript.rename(moved)
        refused = await client.post(f"/sessions/{uuid}/restart")
        assert refused.status_code == 409, refused.text
        assert (await rig.far("has-session", "-t", f"={name}"))[0] != 0
        moved.rename(transcript)

        resp = await client.post(f"/sessions/{uuid}/restart")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert (body["conversation"], body["row_reused"], body["replaced_session_id"]) == (
            "resumed", True, far_row["id"])
        assert body["session"]["tmux_session"] == name
    started = (await rig.far("list-panes", "-t", f"={name}", "-F", "#{pane_start_command}"))[1]
    assert f"'--resume' '{UUID}'" in started and str(rig.fake.bin_dir) in started, started
    after = _row(rig, HOST, name)
    assert (after["id"], after["lifecycle"], after["title"]) == (far_row["id"], "running", "far")
    assert (await _pane(rig, name))["dead"] == "0"
    assert _local_pane(mgr, name) == local_pane
    assert _fields(_row(rig, "local", name)) == _fields(local_row)
