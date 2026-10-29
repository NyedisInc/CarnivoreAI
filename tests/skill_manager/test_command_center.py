
from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_command_routes, skills_manager_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from tests.helpers.catalog_app import StateOnlySettings, register_projects


def make_skill(root: Path, folder: str, name: str, body: str = "body") -> Path:
    directory = root / folder
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n{body}\n", encoding="utf-8")
    return directory


class SpyLedger:

    opened = 0

    def __enter__(self) -> "SpyLedger":
        SpyLedger.opened += 1
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def list(self) -> tuple:
        return ()

    def targets(self, install_id: str) -> tuple:
        return ()


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    make_skill(home / ".claude" / "skills", "sme", "sme")
    live, bare, archived = tmp_path / "live", tmp_path / "bare", tmp_path / "old"
    for path in (live, bare, archived):
        (path / ".git").mkdir(parents=True)
    proj_skills = live / ".claude" / "skills"
    make_skill(proj_skills, "sme", "sme", "different body")
    make_skill(proj_skills, "dup-a", "twin")
    make_skill(proj_skills, "dup-b", "twin")
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    register_projects(state, [live, bare, archived, home])
    with contextlib.closing(connect(db_path_for(state))) as conn:
        conn.execute("UPDATE projects SET archived_at='2026-09-02T00:00:00Z' WHERE display_name='project-2'")
        conn.commit()
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_manager_routes.settings, "auth_config_file", str(config))
    SpyLedger.opened = 0
    app = FastAPI()
    app.include_router(skills_command_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = SimpleNamespace(
        settings_reader=StateOnlySettings(state), catalog=SimpleNamespace(ledger=SpyLedger)
    )
    return SimpleNamespace(client=TestClient(app), live=live, bare=bare, home=home, proj_skills=proj_skills)


def col(body: dict, label: str, harness: str) -> dict:
    return next(c for c in body["columns"] if c["label"] == label and c["harness"] == harness)


def test_command_center_matrix(world):
    body = world.client.get("/api/v1/skills/command-center").json()
    assert SpyLedger.opened == 1
    live, bare = col(body, "project-0", "claude"), col(body, "project-1", "claude")
    assert live["exists"] and live["writable"] and not bare["exists"] and bare["writable"]
    sme = next(r for r in body["rows"] if r["name"] == "sme")
    assert sme["cells"][bare["column_id"]][0]["state"] == "none_yet"
    assert sme["cells"][col(body, "project-0", "codex")["column_id"]][0]["state"] == "none_yet"
    personal = col(body, "all projects (claude)", "claude")
    assert personal["writable"] and personal["accounts_sharing"] == ["default"]
    assert sme["cells"][personal["column_id"]][0]["state"] == "present"
    assert sme["cells"][live["column_id"]][0]["state"] == "shadowed"
    assert not any(c["label"] == "project-2" for c in body["columns"])
    both = world.client.get("/api/v1/skills/command-center", params={"include_archived": "true"}).json()
    assert col(both, "project-2", "claude")["readonly_reason"] == "archived"
    assert not col(both, "project-2", "claude")["writable"]
    home = col(body, "project-3", "claude")
    assert home["readonly_reason"] == "home_folder" and not home["writable"]
    (twin,) = [r for r in body["rows"] if r["name"] == "twin"]
    assert sorted(c["folder"] for c in twin["cells"][live["column_id"]]) == ["dup-a", "dup-b"]
    assert world.client.get("/api/v1/skills/command-center").json()["generation"] == body["generation"]
    (world.proj_skills / "dup-a" / "extra.txt").write_text("x" * 7, encoding="utf-8")
    first = world.client.get("/api/v1/skills/command-center").json()["generation"]
    assert first != body["generation"]
    (world.proj_skills / "dup-a" / "extra.txt").write_text("x" * 8, encoding="utf-8")
    assert world.client.get("/api/v1/skills/command-center").json()["generation"] != first
