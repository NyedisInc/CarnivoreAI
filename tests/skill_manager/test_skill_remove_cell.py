
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_command_routes, skills_manager_routes
from src.api.auth import require_auth
from src.core.db_migration import ensure_db_migrated
from tests.helpers.catalog_app import StateOnlySettings, register_projects
from tests.skill_manager.test_skill_copy import Ledger, cols


def test_remove_cell(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    live, ln3, outside = tmp_path / "live", tmp_path / "ln3", tmp_path / "trash_out"
    outside.mkdir()
    for path in (live, ln3):
        (path / ".git").mkdir(parents=True)
        skill = path / ".claude" / "skills" / "tool"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: tool\ndescription: d\n---\nbody\n", encoding="utf-8")
    other = live / ".claude" / "skills" / "kept"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: kept\ndescription: d\n---\nbody\n", encoding="utf-8")
    (ln3 / ".claude" / ".carnivore-trash").symlink_to(outside)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    register_projects(state, [live, ln3])
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_manager_routes.settings, "auth_config_file", str(config))
    Ledger.managed = []
    notified = []
    monkeypatch.setattr(skills_command_routes.notifier, "notify", notified.append)
    app = FastAPI()
    app.include_router(skills_command_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = SimpleNamespace(
        settings_reader=StateOnlySettings(state), catalog=SimpleNamespace(ledger=Ledger),
        clock=SimpleNamespace(now=lambda: 1_790_000_000.0),
    )
    client = TestClient(app)

    def matrix() -> dict:
        return client.get("/api/v1/skills/command-center").json()

    def cell_of(m: dict, label: str, name: str) -> tuple:
        col = cols(m, label, "claude")
        return col["column_id"], next(r for r in m["rows"] if r["name"] == name)["cells"][col["column_id"]][0]["location_id"]

    def post(m: dict, label: str, name: str = "tool", **over):
        column_id, loc = cell_of(m, label, name)
        return client.post("/api/v1/skills/remove", json={"location_id": loc, "column_id": column_id, "generation": m["generation"], **over})

    m = matrix()
    assert post(m, "project-0", generation="").status_code == 400
    stale = post(m, "project-0", generation="old")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale"
    bogus = client.post("/api/v1/skills/remove", json={"location_id": "nope", "column_id": "nope", "generation": m["generation"]})
    assert bogus.status_code == 404
    assert (live / ".claude" / "skills" / "tool").is_dir() and not notified
    unsafe = post(m, "project-1")
    assert unsafe.status_code == 409 and unsafe.json()["detail"]["code"] == "target_unsafe"
    assert (ln3 / ".claude" / "skills" / "tool").is_dir() and not list(outside.iterdir())
    Ledger.managed = [str(live / ".claude" / "skills" / "tool")]
    managed = post(matrix(), "project-0")
    assert managed.status_code == 409 and managed.json()["detail"]["code"] == "use_catalog_uninstall"
    assert (live / ".claude" / "skills" / "tool").is_dir() and not notified
    Ledger.managed = []
    m = matrix()
    done = post(m, "project-0")
    assert done.status_code == 200 and done.json()["name"] == "tool"
    trashed = Path(done.json()["trashed_to"])
    assert trashed.parent == live / ".claude" / ".carnivore-trash" and (trashed / "SKILL.md").is_file()
    assert not (live / ".claude" / "skills" / "tool").exists() and (live / ".claude" / "skills" / "kept").is_dir()
    assert notified == ["local_skills"]
    assert post(m, "project-0", generation=m["generation"]).status_code in (404, 409)
