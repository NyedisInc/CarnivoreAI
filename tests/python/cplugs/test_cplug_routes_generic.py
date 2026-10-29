
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cplugs.host import routes as host_routes, runtime
from src.api.auth import require_auth


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.published = []
    host.publish = host.published.append
    app.include_router(host_routes.router, prefix="/api/v1")
    return app


def cplug_paths(app: FastAPI):
    for d in runtime.definitions():
        for route in (d.router.routes if d.router else ()):
            if "GET" in getattr(route, "methods", ()):
                yield "/api/v1" + route.path.replace("{key}", "all").replace("{item_id}", "1").replace("{message_id}", "1").replace("{entry_id}", "1").replace("{ticket}", "none")


def test_every_cplug_route_needs_a_token_and_answers_409_while_off(app: FastAPI, monkeypatch):
    paths = [p for p in cplug_paths(app) if not p.endswith("/sessions")]
    assert "/api/v1/cplugs/huddle/lists" in paths
    with TestClient(app) as anonymous:
        for path in paths:
            expected = 404 if "/artifact-view" in path else 409 if ("/cplugs/reviewboard/view/" in path or "/cplugs/devwidgetlab/draft-harness/" in path) else 401
            assert anonymous.get(path).status_code == expected, path
    paths = [p for p in paths if p.startswith("/api/v1/cplugs/huddle/")]
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    from src.cplugs.huddle import service

    monkeypatch.setattr(service, "project_names", lambda ctx: {})
    with TestClient(app) as client:
        fresh = client.get("/api/v1/cplugs/huddle").json()
        assert fresh["enabled"] is True and fresh["state"] == "active" and fresh["revision"] == 0
        assert fresh["grants"]["app"] == fresh["permissions"]["app"] and fresh["needs"] == []
        off_first = client.put("/api/v1/cplugs/huddle", json={"revision": 0, "enabled": False}).json()
        for path in paths:
            refused = client.get(path)
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "cplug_disabled", path
        on = client.put("/api/v1/cplugs/huddle", json={"revision": off_first["revision"], "enabled": True,
                                                        "grants": {"app": fresh["permissions"]["app"]}})
        row = on.json()
        assert on.status_code == 200 and row["state"] == "active" and row["grants"]["app"] == row["permissions"]["app"]
        for path in paths:
            passed = client.get(path)
            assert passed.status_code == 200 or (passed.status_code == 404 and passed.json()["detail"]["code"] == "task_manager_not_found"), path
        off = client.put("/api/v1/cplugs/huddle", json={"revision": row["revision"], "enabled": False})
        assert off.status_code == 200 and off.json()["state"] == "disabled"
        assert app.state.cplugs_host.published[-1] == "cplugs"
        for path in paths:
            refused = client.get(path)
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "cplug_disabled", path


def test_the_host_routes_refuse_what_the_contract_refuses(app: FastAPI):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        listed = client.get("/api/v1/cplugs").json()["cplugs"]
        assert [a["id"] for a in listed] == ["huddle", "unread", "share", "save",
                                               "flow", "reviewboard", "publicboard", "crate", "timemachine"]
        assert {a["id"]: a["enabled"] for a in listed} == {
            "huddle": True, "unread": True, "share": True, "save": False,
            "flow": False,
            "reviewboard": False, "publicboard": False, "crate": False, "timemachine": False}
        assert client.get("/api/v1/cplugs/nope").json()["detail"]["code"] == "cplug_unknown"
        stale = client.put("/api/v1/cplugs/huddle", json={"revision": 7, "enabled": False})
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_revision"
        assert stale.json()["detail"]["current"]["revision"] == 0
        extra = client.put("/api/v1/cplugs/huddle", json={"revision": 0, "grants": {"app": ["notify", "root"]}})
        assert extra.status_code == 422 and extra.json()["detail"]["code"] == "grant_not_asked"
        secret = client.put("/api/v1/cplugs/huddle", json={"revision": 0, "settings": {"api_token": "x"}})
        assert secret.status_code == 422 and secret.json()["detail"]["code"] == "settings_invalid"
        narrowed = client.put("/api/v1/cplugs/huddle", json={"revision": 0, "enabled": True,
                                                             "grants": {"app": ["sessions.read"]}}).json()
        assert narrowed["state"] == "needs_approval" and set(narrowed["needs"]) == {"sessions.message", "notify", "agent_writes", "swarm"}


def test_purge_is_priced_first_and_refused_while_on(app: FastAPI, tmp_path: Path):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    folder = tmp_path / "cplugs" / "huddle"
    folder.mkdir(parents=True)
    (folder / "huddle.db").write_bytes(b"x" * 10)
    (folder / "files").mkdir()
    (folder / "files" / "a.txt").write_bytes(b"x" * 4)
    with TestClient(app) as client:
        client.put("/api/v1/cplugs/huddle", json={"revision": 0, "enabled": True})
        assert client.post("/api/v1/cplugs/huddle/purge", json={}).json()["detail"]["code"] == "cplug_enabled"
        client.put("/api/v1/cplugs/huddle", json={"revision": 1, "enabled": False})
        price = client.post("/api/v1/cplugs/huddle/purge", json={"dry_run": True}).json()
        assert (price["files"], price["bytes"], price["kept"], price["dry_run"]) == (1, 4, 1, True) and folder.exists()
        wrong = client.post("/api/v1/cplugs/huddle/purge", json={"dry_run": False, "confirm_token": "nope"})
        assert wrong.json()["detail"]["code"] == "purge_stale" and folder.exists()
        done = client.post("/api/v1/cplugs/huddle/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
        assert done.status_code == 200 and (folder / "huddle.db").read_bytes() == b"x" * 10 and not (folder / "files").exists()
        row = client.get("/api/v1/cplugs/huddle").json()
        assert row["enabled"] is True and row["revision"] == 0
        refused = client.post("/api/v1/cplugs/..x/purge", json={"dry_run": False, "confirm_token": "x"})
        assert refused.status_code == 404 and tmp_path.exists()


def test_a_retired_plugin_id_acts_on_the_plugin_that_absorbed_it(app: FastAPI):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        row = client.get("/api/v1/cplugs/nudge").json()
        assert row["id"] == "huddle" and row["enabled"] is True
        on = client.put("/api/v1/cplugs/nudge", json={"revision": row["revision"], "enabled": True, "settings": {"nudgeMinutes": 90}})
        assert on.status_code == 200, on.text
        assert on.json()["enabled"] is True and on.json()["settings"]["nudgeEnabled"] is True and on.json()["settings"]["nudgeMinutes"] == 90
        off = client.put("/api/v1/cplugs/nudge", json={"revision": on.json()["revision"], "enabled": False})
        assert off.status_code == 200 and off.json()["enabled"] is True and off.json()["settings"]["nudgeEnabled"] is False
        assert client.put("/api/v1/cplugs/nudge", json={"revision": 0, "grants": {"app": ["root"]}}).status_code == 409
