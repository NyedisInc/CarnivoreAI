
from __future__ import annotations

import asyncio
import subprocess
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.swarm.test_swarm_s7_smokefix import _db, env  # noqa: F401,E402
from src.core.companies import store as companies
from src.core.db import connect, db_path_for
from src.core.swarm import body, body_create, company_promote, project_promote, store
from src.core.swarm.facade import SwarmFacade


@pytest.fixture()
def world(env, monkeypatch):
    folder = env.root / "Amerifund"
    folder.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    live, slept = set(), []
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        co = companies.create_company(conn, "Amerifund")
        hqp = body_create.register_project(conn, str(folder), "Amerifund")
        companies.assign_project(conn, hqp["id"], co["id"])
        companies.set_hq_project(conn, co["id"], hqp["id"])
        for name in ("lead", "other"):
            conn.execute("INSERT INTO sessions (session_uuid, project_id, working_dir, title, origin, lifecycle, agent_family, created_at, updated_at)"
                         " VALUES (?, ?, ?, ?, 'created', 'stopped', 'claude', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')",
                         (f"u-{name}", hqp["id"], str(folder), name))

    async def live_info(app_state, agent):
        return SimpleNamespace() if agent["session_row_id"] in live else None

    async def sleep_by_uuid(app_state, session_uuid, **kw):
        slept.append(session_uuid)
        live.discard(_row_id_of(env, session_uuid))
        return SimpleNamespace(status="asleep", detail="")

    monkeypatch.setattr(body, "live_info", live_info)
    import src.api.session_sleep_routes as sleep_routes
    monkeypatch.setattr(sleep_routes, "sleep_by_uuid", sleep_by_uuid)
    env.co, env.hqp, env.slept, env.live, env.folder = co, hqp, slept, live, folder
    return env


def _row_id_of(world, session_uuid: str) -> int:
    return _db(world, lambda c: c.execute("SELECT id FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()[0])


def _promote(world, name: str, company_id=None):
    return asyncio.run(company_promote.promote_session(SimpleNamespace(), f"u-{name}", company_id or world.co["id"]))


def _company_agents(world):
    return _db(world, lambda c: [a for a in store.list_agents(c) if a["rank"] == "company" and a["company_id"] == world.co["id"]])


def test_an_asleep_hq_session_becomes_the_company_agent_on_its_own_row_and_stays_asleep(world):
    agent = _promote(world, "lead")
    assert agent["rank"] == "company" and agent["state"] == "asleep" and agent["session_row_id"] == _row_id_of(world, "u-lead")
    assert agent["project_id"] == world.hqp["id"] and agent["company_id"] == world.co["id"] and agent["repo_dir"].endswith("Amerifund")
    assert [a["id"] for a in _company_agents(world)] == [agent["id"]] and world.slept == []
    assert world.woke == [] and (world.folder / ".claude" / "agents" / f"{agent['slug']}.md").is_file()
    seat = [s for s in SwarmFacade(world.state, lambda: asyncio.sleep(0, []), SimpleNamespace()).agent_seats() if s.agent_id == agent["id"]][0]
    assert seat.project_key == str(world.hqp["id"]) and seat.session_uuid == "u-lead"


def test_a_running_session_is_stopped_then_woken_resuming(world, monkeypatch):
    world.live.add(_row_id_of(world, "u-lead"))
    woke = []

    async def wake(app_state, agent_id, reason, authority, **kw):
        woke.append((agent_id, reason, authority, kw["mode"], "company agent" in kw["orders"]))

    monkeypatch.setattr(body, "wake", wake)
    agent = _promote(world, "lead")
    assert world.slept == ["u-lead"] and woke == [(agent["id"], "manual", "data", "resume", True)]


def test_a_session_in_the_middle_of_a_turn_refuses_and_nothing_is_written(world, monkeypatch):
    world.live.add(_row_id_of(world, "u-lead"))

    async def busy(app_state, session_uuid, **kw):
        return SimpleNamespace(status="refused", detail="cannot sleep: the session is working")

    import src.api.session_sleep_routes as sleep_routes
    monkeypatch.setattr(sleep_routes, "sleep_by_uuid", busy)
    with pytest.raises(project_promote.PromoteRefused, match="working"):
        _promote(world, "lead")
    assert _company_agents(world) == [] and world.woke == []


def test_a_live_company_agent_is_repointed_and_keeps_its_slug_and_the_old_body_is_a_plain_session(world):
    first = _promote(world, "lead")
    again = _promote(world, "other")
    assert again["id"] == first["id"] and again["slug"] == first["slug"] and again["session_row_id"] == _row_id_of(world, "u-other")
    assert _db(world, lambda c: store.get_agent_by_session_row(c, _row_id_of(world, "u-lead"))) is None
    assert _promote(world, "other")["id"] == first["id"] and world.slept == []


def test_a_turned_on_company_agent_with_no_body_is_repointed_not_duplicated(world):
    existing = _db(world, lambda c: store.create_agent(c, slug="amerifund-agent", rank="company", job="j", display_name="Amerifund agent",
                                                        repo_dir=str(world.folder), effort="high", company_id=world.co["id"], project_id=world.hqp["id"]))
    agent = _promote(world, "lead")
    assert agent["id"] == existing["id"] and agent["session_row_id"] == _row_id_of(world, "u-lead") and len(_company_agents(world)) == 1


def test_a_company_without_an_hq_and_an_unknown_company_are_refused(world):
    _db(world, lambda c: c.execute("UPDATE companies SET hq_project_id = NULL WHERE id = ?", (world.co["id"],)))
    with pytest.raises(project_promote.PromoteRefused, match="no HQ folder"):
        _promote(world, "lead")
    with pytest.raises(company_promote.CompanyMissing):
        _promote(world, "lead", company_id=9999)


def test_an_unfit_session_is_refused_before_anything_is_written(world):
    _db(world, lambda c: c.execute("UPDATE sessions SET agent_family = 'codex' WHERE session_uuid = 'u-lead'"))
    with pytest.raises(project_promote.PromoteRefused, match="not a Claude session"):
        _promote(world, "lead")
    assert _company_agents(world) == [] and world.slept == [] and world.woke == []


def test_the_project_promote_still_refuses_an_hq_folder_and_the_facade_dispatches_it_to_the_company(world):
    with pytest.raises(project_promote.PromoteRefused, match="company's own HQ"):
        asyncio.run(project_promote.promote_session(SimpleNamespace(), "u-lead", world.hqp["id"]))
    facade = SwarmFacade(world.state, lambda: asyncio.sleep(0, []), SimpleNamespace())
    assert facade.company_hq(str(world.hqp["id"])) == world.co["id"] and facade.company_hq("99999") is None
    ref = asyncio.run(facade.promote_session("u-lead", str(world.hqp["id"])))
    assert ref.rank == "company" and len(_company_agents(world)) == 1


def test_the_owner_route_maps_404_and_409_and_needs_the_owner(world):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import swarm_routes
    from src.api.auth import require_auth
    app = FastAPI()
    app.include_router(swarm_routes.router, prefix="/api/v1")
    app.state.session_manager = SimpleNamespace()
    url = "/api/v1/swarm/companies/{}/promote"
    unauthed = TestClient(app).post(url.format(world.co["id"]), json={"session_uuid": "u-lead"})
    assert unauthed.status_code in (401, 403) and _company_agents(world) == []
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)
    assert client.post(url.format(9999), json={"session_uuid": "u-lead"}).json()["detail"]["code"] == "company_not_found"
    refused = client.post(url.format(world.co["id"]), json={"session_uuid": "u-nobody"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "swarm_refused"
