
from __future__ import annotations

import os
import shutil
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_upl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_upl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import httpx
import pytest
from fastapi import FastAPI

from src.api import swarm_upload_routes
from src.api.auth import require_auth
from src.api.swarm_switch_routes import require_swarm_on
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import store, thread_port


class Port:
    pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    thread_port.register(Port())
    conn = connect(db_path_for(state))
    repo = tmp_path / "sysop-home"
    repo.mkdir()
    agent = store.create_agent(conn, slug="sysop", rank="project", job="repo", display_name="SysOp", effort="medium",
                               repo_dir=str(repo))
    app = FastAPI()
    app.include_router(swarm_upload_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_swarm_on] = lambda: None
    yield app, conn, agent, repo
    thread_port.register(None)
    conn.close()


async def _post(app: FastAPI, agent_id: int, name: str, data: bytes) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        return await client.post(f"/swarm/agents/{agent_id}/upload-file", files={"file": (name, data, "text/plain")})


@pytest.mark.asyncio
async def test_an_asleep_agent_takes_a_file_into_its_own_folder(env):
    app, conn, agent, repo = env
    assert agent["state"] == "asleep"

    resp = await _post(app, agent["id"], "notes.txt", b"look at this\n")

    assert resp.status_code == 201, resp.text
    path = resp.json()["path"]
    assert os.path.isabs(path)
    assert os.path.dirname(path) == os.path.join(os.path.realpath(repo), ".carnivore_uploads")
    assert path.endswith("-notes.txt")
    with open(path, "rb") as fh:
        assert fh.read() == b"look at this\n"

    shutil.rmtree(repo)
    assert (await _post(app, agent["id"], "a.txt", b"x")).status_code == 409
    assert not repo.exists()
    conn.execute("UPDATE swarm_agents SET torn_down_at = 1 WHERE id = ?", (agent["id"],))
    conn.commit()
    assert (await _post(app, agent["id"], "a.txt", b"x")).status_code == 404
