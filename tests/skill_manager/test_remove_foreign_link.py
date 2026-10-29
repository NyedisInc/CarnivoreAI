
from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_manager_routes
from src.api.auth import require_auth
from src.core import slash_command_discovery as scd
from src.core.db_migration import ensure_db_migrated
from src.core.event_hub import EventHub
from src.core.live_ports import SystemClock
from src.core.skills import targets as skill_targets
from src.core.skills.sweeper import TRASH_TTL_SECONDS, sweep_project_trashes
from src.core.test_write_guard import OutsideTempWriteError
from tests.helpers.catalog_app import StateOnlySettings, register_projects
from tests.skill_manager.test_inventory_shadowing import NoIndex, NoLedger, make_skill


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claude = home / ".claude"
    make_skill(claude / "skills", "plain")
    foreign = make_skill(tmp_path / "foreign", "outside")
    (foreign / "notes.txt").write_text("keep me", encoding="utf-8")
    os.symlink(foreign, claude / "skills" / "linked")
    make_skill(claude / "plugins" / "cache" / "mk" / "plug" / "1.0.0" / "skills", "plug-skill")
    monkeypatch.setattr(scd, "CLAUDE_HOME", claude)
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    make_skill(project / ".claude" / "skills", "proj-only")
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    register_projects(state, [project])
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_manager_routes.settings, "auth_config_file", str(config))
    app = FastAPI()
    app.include_router(skills_manager_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    hub = EventHub()
    app.state.event_hub = hub
    app.state.services = SimpleNamespace(
        settings_reader=StateOnlySettings(state),
        catalog=SimpleNamespace(ledger=NoLedger, index_cache=NoIndex()),
        clock=SystemClock(),
    )
    return SimpleNamespace(
        home=home, project=project, foreign=foreign, claude=claude, client=TestClient(app), hub=hub
    )


def location_id(world, folder: str, **params) -> str:
    body = world.client.get("/api/v1/skills", params=params).json()
    ids = [loc["location_id"] for g in body["skills"] for loc in g["locations"] if loc["folder"] == folder]
    assert len(ids) == 1, (folder, ids)
    return ids[0]


def remove(world, loc: str, **body):
    return world.client.request("DELETE", f"/api/v1/skills/locations/{loc}", json={"confirm": True, **body})


def test_a_foreign_link_moves_as_a_link_and_its_target_is_untouched(world):
    loc = location_id(world, "linked")
    frames = []
    world.hub.publish = frames.append
    reply = remove(world, loc)
    assert reply.status_code == 200, reply.text
    trash = world.claude / ".carnivore-trash"
    moved = Path(reply.json()["trashed_to"])
    assert moved.parent == trash and moved.is_symlink()
    assert os.path.realpath(moved) == os.path.realpath(world.foreign)
    assert not os.path.lexists(world.claude / "skills" / "linked")
    assert (world.foreign / "notes.txt").read_text() == "keep me" and (world.foreign / "SKILL.md").is_file()
    assert (trash / ".gitignore").read_text() == "*\n"
    assert (world.claude / "skills" / "plain" / "SKILL.md").is_file()
    assert [f["type"] for f in frames] == ["skills.changed"]
    assert remove(world, loc).status_code == 404


def test_refusals_leave_disk_alone(world):
    loc = location_id(world, "plain")
    no_confirm = world.client.request("DELETE", f"/api/v1/skills/locations/{loc}", json={})
    assert no_confirm.status_code == 400
    assert remove(world, "cp-000000000000:nothere").status_code == 404
    plugin = remove(world, location_id(world, "plug-skill"))
    assert plugin.status_code == 409 and plugin.json()["detail"]["code"] == "read_only"
    assert remove(world, loc, project_path=str(world.project.parent / "stranger")).status_code == 404
    assert (world.claude / "skills" / "plain" / "SKILL.md").is_file()
    assert not (world.claude / ".carnivore-trash").exists()


def test_project_trash_is_ignored_and_swept(world):
    loc = location_id(world, "proj-only", project_path=str(world.project))
    reply = remove(world, loc, project_path=str(world.project))
    assert reply.status_code == 200, reply.text
    trash = world.project / ".claude" / ".carnivore-trash"
    assert (trash / ".gitignore").read_text() == "*\n"
    old = time.time() - TRASH_TTL_SECONDS - 60
    for entry in trash.iterdir():
        os.utime(entry, (old, old), follow_symlinks=False)
    assert sweep_project_trashes([str(world.project)], TRASH_TTL_SECONDS, time.time()) == 1
    assert [p.name for p in trash.iterdir()] == [".gitignore"]


def test_negative_control_the_guard_blocks_a_real_home_trash(monkeypatch):
    real_home = Path(os.path.expanduser("~"))
    calls = []
    monkeypatch.setattr(skill_targets.os, "replace", lambda *a, **k: calls.append(a))
    with pytest.raises(OutsideTempWriteError):
        skill_targets.move_to_trash(
            real_home / ".claude" / "skills" / "x", real_home / ".claude" / ".carnivore-trash", "20260928T000000Z"
        )
    assert calls == []
