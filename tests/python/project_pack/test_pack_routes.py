
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import projects_routes
from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.core.project_pack import jobs
from tests.python.project_pack.pack_world import storage_row, tree_digest


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(projects_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_pack_then_unpack_over_http(world):
    client, before = _client(), tree_digest(world.root)
    url = "/api/v1/projects/oldsite"
    plan = client.post(f"{url}/pack", json={}).json()
    assert plan["ok"] is True and plan["job"] is None, plan["checks"]
    assert client.post(f"{url}/pack", json={"apply": True}).status_code == 428
    assert client.post(f"{url}/pack", json={"apply": True, "plan_fingerprint": "0" * 16}).status_code == 412
    started = client.post(f"{url}/pack", json={"apply": True, "plan_fingerprint": plan["fingerprint"]})
    assert started.status_code == 200 and started.json()["job"]["kind"] == "pack", started.text
    jobs.join(world.ids["oldsite"])
    storage = client.get(f"{url}/storage").json()["storage"]
    assert storage["state"] == "packed" and storage["integrity"]["status"] == "ok" and storage["archive_bytes"] > 0
    listed = {p["name"]: p for p in client.get("/api/v1/projects", params={"include_archived": True}).json()}
    assert listed["oldsite"]["storage"]["state"] == "packed" and listed["kid"]["storage"]["packed_in"] == world.ids["oldsite"]
    refused = client.post(f"{url}/unarchive")
    assert refused.status_code == 409 and "unpack it first" in refused.json()["detail"]
    assert client.post("/api/v1/sessions", json={"working_dir": str(world.root)}).status_code == 409
    assert client.post(f"{url}/storage/verify").json()["integrity"] == {"status": "ok", "message": "", "full": True}
    archive = world.root / storage_row(world)["archive_name"]
    with open(archive, "ab") as handle:
        handle.write(b"x")
    warned = client.post(f"{url}/unpack", json={}).json()
    assert warned["integrity"]["status"] == "modified" and any("WARNING" in w for w in warned["warnings"])
    assert client.post(f"{url}/storage/verify").json()["integrity"]["status"] == "modified"
    os.truncate(archive, archive.stat().st_size - 1)
    plan = client.post(f"{url}/unpack", json={}).json()
    started = client.post(f"{url}/unpack", json={"apply": True, "plan_fingerprint": plan["fingerprint"]})
    assert started.status_code == 200, started.text
    jobs.join(world.ids["oldsite"])
    assert storage_row(world)["state"] == "unpacked"
    assert tree_digest(world.root) == before
    assert client.post(f"{url}/unarchive").status_code == 200
