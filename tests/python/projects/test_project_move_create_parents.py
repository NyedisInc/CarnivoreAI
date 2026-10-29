
from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import project_move_routes
from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.core.db import connect
from src.core.project_move import apply as apply_mod
from src.core.project_move.apply import apply_plan
from tests.python.projects.move_world import NO_PANES, plan_for, snapshot


def test_the_plan_lists_the_folders_it_would_create_and_creates_none(world):
    target = world.base / "org" / "x" / "y" / "alpha"
    plan = plan_for(world, move_folder=True, new_root=str(target), create_parents=True)
    assert plan.ok, plan.failed()
    assert plan.folders_to_create == [str(world.base / "org" / "x"), str(world.base / "org" / "x" / "y")]
    assert not (world.base / "org" / "x").exists()


def test_apply_creates_the_parents_then_moves(world):
    target = world.base / "org" / "initech" / "alpha"
    plan = plan_for(world, move_folder=True, new_root=str(target), create_parents=True)
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
    assert done["folders_created"] == [str(world.base / "org" / "initech")]
    assert (target / "notes.md").read_text() == "x" and not world.old.exists()


def test_a_failed_apply_removes_only_the_folders_it_created(world, monkeypatch):
    target = world.base / "org" / "initech" / "alpha"
    before = snapshot(world)
    plan = plan_for(world, move_folder=True, new_root=str(target), create_parents=True)

    def boom(conn, plan):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(apply_mod, "_rewrite_db", boom)
    with closing(connect(world.db, create=False)) as conn, pytest.raises(apply_mod.MoveFailed) as failed:
        apply_plan(conn, plan, state_dir=world.state)
    assert failed.value.undo_errors == []
    assert not (world.base / "org" / "initech").exists() and (world.base / "org").is_dir()
    assert snapshot(world) == before


def test_create_parents_without_move_folder_is_named_not_silent(world):
    plan = plan_for(world, move_folder=False, new_root=str(world.base / "org" / "initech" / "alpha"), create_parents=True)
    assert any("create_parents does nothing without move_folder" in w for w in plan.warnings)
    assert plan.folders_to_create == []


def test_the_route_carries_create_parents(world, monkeypatch):
    monkeypatch.setattr(project_move_routes, "read_live_panes", lambda: NO_PANES)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    target = str(world.base / "org" / "initech" / "alpha")
    body = TestClient(app).post("/api/v1/projects/alpha/move", json={
        "new_root": target, "move_folder": True, "create_parents": True}).json()
    assert body["ok"] is True and body["create_parents"] is True
    assert body["folders_to_create"] == [str(world.base / "org" / "initech")]


def test_the_mcp_tool_carries_create_parents_and_checks_its_type(world, monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace

    from src.core.mcp.common import ToolError
    from src.core.mcp.project_tools import project_move

    monkeypatch.setattr(project_move_routes, "read_live_panes", lambda: NO_PANES)
    target = str(world.base / "org" / "initech" / "alpha")
    args = {"project": world.ids["alpha"], "new_root": target, "move_folder": True, "create_parents": True}
    answer = asyncio.run(project_move(SimpleNamespace(app=None), None, args))
    plan = json.loads(answer["content"][0]["text"])
    assert plan["folders_to_create"] == [str(world.base / "org" / "initech")] and plan["ok"] is True
    with pytest.raises(ToolError):
        asyncio.run(project_move(SimpleNamespace(app=None), None, {**args, "create_parents": "yes"}))
