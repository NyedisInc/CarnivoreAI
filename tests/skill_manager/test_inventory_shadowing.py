
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_manager_routes
from src.api.auth import require_auth
from src.core import slash_command_discovery as scd
from src.core.db_migration import ensure_db_migrated
from src.core.skill_manager.inventory import build_inventory
from src.core.skill_manager.roots import known_profiles, profile_groups
from src.core.skill_manager.types import PLUGIN_NO_TOGGLE_REASON
from tests.helpers.catalog_app import StateOnlySettings, register_projects


def make_skill(root: Path, folder: str, description: str = "does a thing") -> Path:
    directory = root / folder
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {folder}\ndescription: {description}\n---\nbody\n", encoding="utf-8"
    )
    return directory


class NoLedger:

    def __enter__(self) -> "NoLedger":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def list(self) -> tuple:
        return ()

    def targets(self, install_id: str) -> tuple:
        return ()


class NoIndex:

    async def get(self) -> SimpleNamespace:
        return SimpleNamespace(verified=None, refusal=None)


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claude = home / ".claude"
    make_skill(claude / "skills", "review")
    make_skill(claude / "skills", "sme")
    (claude / "skills" / ".hidden").mkdir()
    (claude / "skills" / ".hidden" / "SKILL.md").write_text("x", encoding="utf-8")
    (claude / "settings.json").write_text(
        '{"skillOverrides": {"sme": "name-only"}, "secret": "do-not-read"}', encoding="utf-8"
    )

    accounts = home / ".carnivore" / "accounts"
    linked = accounts / "linked"
    linked.mkdir(parents=True)
    os.symlink(claude / "skills", linked / "skills")
    os.symlink(claude / "settings.json", linked / "settings.json")
    own = accounts / "own"
    make_skill(own / "skills", "bench-only")
    (own / "settings.json").write_text("{}", encoding="utf-8")

    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    make_skill(project / ".claude" / "skills", "review", "project copy")
    make_skill(project / ".claude" / "skills", "proj-only")

    plugin_skills = claude / "plugins" / "cache" / "mk" / "plug" / "1.0.0" / "skills"
    make_skill(plugin_skills, "plug-skill")
    monkeypatch.setattr(scd, "CLAUDE_HOME", claude)

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
    app.state.services = SimpleNamespace(
        settings_reader=StateOnlySettings(state),
        catalog=SimpleNamespace(ledger=NoLedger, index_cache=NoIndex()),
    )
    return SimpleNamespace(home=home, project=project, client=TestClient(app))


def locations(body: dict, name: str) -> list:
    return next(g["locations"] for g in body["skills"] if g["name"] == name)


def test_personal_shadows_project_and_settings_are_read_key_only(world):
    body = world.client.get("/api/v1/skills", params={"project_path": str(world.project)}).json()
    personal, project = sorted(locations(body, "review"), key=lambda loc: loc["scope"] != "personal")
    assert personal["scope"] == "personal" and project["scope"] == "project"
    assert project["shadowed_by"] == personal["location_id"]
    assert personal["shadows"] == [project["location_id"]]
    assert personal["toggle"]["kind"] == "four_state"
    assert locations(body, "sme")[0]["state"] == "name-only"
    assert "do-not-read" not in str(body)
    assert locations(body, "proj-only")[0]["shadowed_by"] is None
    assert locations(body, "review")[0]["tokens_label"] == "est."


def test_a_symlinked_profile_groups_with_its_target_and_own_folder_stays_apart(world):
    body = world.client.get("/api/v1/skills").json()
    groups = {tuple(g["profiles"]): g for g in body["profile_groups"]}
    assert ("default", "linked") in groups
    assert ("own",) in groups
    assert groups[("own",)]["own_folder"] is True
    assert groups[("default", "linked")]["skills_path"] != groups[("own",)]["skills_path"]
    own = world.client.get("/api/v1/skills", params={"profile": "own"}).json()
    assert [g["name"] for g in own["skills"] if g["locations"][0]["scope"] == "personal"] == ["bench-only"]
    linked = world.client.get("/api/v1/skills", params={"profile": "linked"}).json()
    assert linked["context"]["group_id"] == body["context"]["group_id"]


def test_a_plugin_skill_reports_no_toggle(world):
    body = world.client.get("/api/v1/skills").json()
    (plug,) = locations(body, "plug-skill")
    assert plug["scope"] == "plugin" and plug["plugin"] == "plug"
    assert plug["toggle"]["kind"] == "none"
    assert plug["toggle"]["reason"] == PLUGIN_NO_TOGGLE_REASON


def test_an_unsafe_folder_name_is_skipped_and_reported(world):
    body = world.client.get("/api/v1/skills").json()
    assert all(g["name"] != ".hidden" for g in body["skills"])
    assert [s["folder"] for s in body["skipped"]] == [".hidden"]
    assert "starts with a dot" in body["skipped"][0]["reason"]


def test_an_unknown_project_or_profile_is_404(world, tmp_path):
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    assert world.client.get("/api/v1/skills", params={"project_path": str(stranger)}).status_code == 404
    assert world.client.get("/api/v1/skills", params={"profile": "nope"}).status_code == 404
    assert world.client.get("/api/v1/skills", params={"project_path": str(world.project)}).status_code == 200


def test_model_layer_matches_the_route_for_shadowing(world):
    profiles = known_profiles([], home=world.home, managed_root=str(world.home / ".carnivore" / "accounts"))
    assert [p.profile_id for p in profiles][:1] == ["default"]
    assert len(profile_groups(profiles)) == 2
    body = build_inventory(
        profiles=profiles, profile_id=None, project_path=str(world.project), home=world.home,
        codex_home=world.home / ".codex", ledger_rows=(), targets_for=lambda _i: (),
        update_check=lambda _r: False, plugin_scope=scd.discover_plugin_scope,
    )
    assert any(loc["shadowed_by"] for loc in locations(body, "review"))
