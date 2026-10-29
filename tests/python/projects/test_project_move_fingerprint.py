
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import project_move_routes
from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.core.db import connect
from src.core.mcp.common import ToolError
from src.core.mcp.project_tools import project_move
from tests.python.projects.move_world import NO_PANES, add_session, plan_for, snapshot

URL = "/api/v1/projects/alpha/move"


@pytest.fixture()
def client(world, monkeypatch):
    monkeypatch.setattr(project_move_routes, "read_live_panes", lambda: NO_PANES)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_two_plans_of_an_unchanged_world_agree(world):
    first, second = plan_for(world, move_folder=True), plan_for(world, move_folder=True)
    assert first.fingerprint and first.fingerprint == second.fingerprint


def test_a_different_folder_at_the_same_path_changes_it(world):
    before = plan_for(world, move_folder=True).fingerprint
    os.rename(world.old, world.base / "parked")
    world.old.mkdir()
    assert plan_for(world, move_folder=True).fingerprint != before


def test_the_mode_flags_change_it(world):
    assert plan_for(world, move_folder=True).fingerprint != plan_for(world, move_folder=False).fingerprint


def test_apply_without_a_fingerprint_is_428_and_changes_nothing(world, client):
    before = snapshot(world)
    answer = client.post(URL, json={"new_root": str(world.new), "move_folder": True, "apply": True})
    assert answer.status_code == 428
    assert answer.json()["detail"]["plan"]["fingerprint"]
    assert snapshot(world) == before


def test_apply_quoting_a_stale_plan_is_412_and_changes_nothing(world, client):
    read = client.post(URL, json={"new_root": str(world.new), "move_folder": True}).json()
    with closing(connect(world.db, create=False)) as conn:
        add_session(conn, "s-late", str(world.old / "late"))
    before = snapshot(world)
    answer = client.post(URL, json={"new_root": str(world.new), "move_folder": True, "apply": True,
                                    "plan_fingerprint": read["fingerprint"]})
    assert answer.status_code == 412 and "changed since it was read" in answer.json()["detail"]["message"]
    assert snapshot(world) == before


def test_apply_quoting_the_current_plan_runs(world, client):
    read = client.post(URL, json={"new_root": str(world.new), "move_folder": True}).json()
    answer = client.post(URL, json={"new_root": str(world.new), "move_folder": True, "apply": True,
                                    "plan_fingerprint": read["fingerprint"]})
    assert answer.status_code == 200, answer.text
    assert answer.json()["applied"] and (world.new / "notes.md").exists()


@pytest.mark.parametrize("quoted", [None, "0000000000000000"])
def test_the_mcp_tool_refuses_before_filing_an_approval(world, client, quoted):
    args = {"project": world.ids["alpha"], "new_root": str(world.new), "move_folder": True, "apply": True}
    if quoted:
        args["plan_fingerprint"] = quoted
    before = snapshot(world)
    with pytest.raises(ToolError) as refused:
        asyncio.run(project_move(SimpleNamespace(app=None), None, args))
    assert ("needs plan_fingerprint" if quoted is None else "changed since it was read") in str(refused.value)
    assert snapshot(world) == before


def test_the_mcp_tool_refuses_a_failing_plan_before_filing_an_approval(world, client):
    world.new.mkdir()
    plan = plan_for(world, move_folder=True)
    args = {"project": world.ids["alpha"], "new_root": str(world.new), "move_folder": True, "apply": True,
            "plan_fingerprint": plan.fingerprint}
    with pytest.raises(ToolError) as refused:
        asyncio.run(project_move(SimpleNamespace(app=None), None, args))
    assert "does not pass" in str(refused.value)
