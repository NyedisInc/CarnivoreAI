
from __future__ import annotations

import json
import os
import stat
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_manager_routes
from src.api.auth import require_auth
from src.core import config_writer
from src.core.db_migration import ensure_db_migrated
from src.core.event_hub import EventHub
from src.core.skill_manager import claude_overrides
from src.core.test_write_guard import OutsideTempWriteError
from tests.helpers.catalog_app import StateOnlySettings, register_projects

SHARED = {"model": "opus", "env": {"TOKEN": "secret-value"}, "permissions": {"allow": ["Bash(ls)"]}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claude = home / ".claude"
    (claude / "skills").mkdir(parents=True)
    shared = claude / "settings.json"
    shared.write_text(json.dumps(SHARED), encoding="utf-8")
    linked = home / ".carnivore" / "accounts" / "linked"
    linked.mkdir(parents=True)
    os.symlink(claude / "skills", linked / "skills")
    os.symlink(shared, linked / "settings.json")
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    (project / ".agents" / "skills" / "sme").mkdir(parents=True)
    (project / ".agents" / "skills" / "sme" / "SKILL.md").write_text("---\nname: sme\n---\n", encoding="utf-8")
    codex = home / ".codex"
    codex.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    register_projects(state, [project])
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_manager_routes.settings, "auth_config_file", str(config))
    hub = EventHub()
    app = FastAPI()
    app.include_router(skills_manager_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.services = SimpleNamespace(settings_reader=StateOnlySettings(state))
    app.state.event_hub = hub
    return SimpleNamespace(
        home=home, project=project, shared=shared, linked=linked, codex=codex, client=TestClient(app), hub=hub
    )


def put(world, **body):
    payload = {"harness": "claude", "file": "user", "skill": "sme", "state": "off"}
    payload.update(body)
    return world.client.put("/api/v1/skills/overrides", json=payload)


def test_write_goes_through_the_profile_link_and_keeps_every_other_key(world):
    before = world.shared.read_text()
    reply = put(world, profile="linked")
    assert reply.status_code == 200, reply.text
    assert reply.json()["wrote"] is True and reply.json()["restart_required"] is False
    assert os.path.islink(world.linked / "settings.json")
    assert os.path.realpath(world.linked / "settings.json") == os.path.realpath(world.shared)
    after = json.loads(world.shared.read_text())
    assert after.pop("skillOverrides") == {"sme": "off"}
    assert after == SHARED
    assert json.loads(before) == SHARED
    assert put(world, profile="linked", state=None).status_code == 200
    assert json.loads(world.shared.read_text()) == SHARED
    assert put(world, state=None).json()["wrote"] is False


def test_project_local_write_creates_only_its_own_file(world):
    reply = put(world, file="local", project_path=str(world.project), state="name-only")
    assert reply.status_code == 200, reply.text
    target = world.project / ".claude" / "settings.local.json"
    assert json.loads(target.read_text()) == {"skillOverrides": {"sme": "name-only"}}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert sorted(p.name for p in (world.project / ".claude").iterdir()) == ["settings.local.json"]
    assert json.loads(world.shared.read_text()) == SHARED


def test_refusals_leave_files_alone(world, tmp_path):
    world.shared.write_text("{not json", encoding="utf-8")
    bad = put(world)
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "settings_unparseable"
    assert world.shared.read_text() == "{not json"
    plugin = put(world, skill="plug:thing")
    assert plugin.status_code == 409 and plugin.json()["detail"]["code"] == "plugin_managed"
    assert put(world, project_path=str(tmp_path / "stranger"), file="local").status_code == 404
    assert put(world, profile="nope").status_code == 404
    assert put(world, skill="../x").status_code == 400
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, world.project / ".claude")
    unsafe = put(world, file="local", project_path=str(world.project))
    assert unsafe.status_code == 409 and unsafe.json()["detail"]["code"] == "target_unsafe"
    assert list(elsewhere.iterdir()) == []
    assert put(world, skill="anthropic-skills:pdf", file="user").status_code == 409


def test_a_write_publishes_skills_changed(world):
    frames = []
    world.hub.publish = lambda frame: frames.append(frame) or 1
    assert put(world).status_code == 200
    assert put(world).json()["wrote"] is False
    assert [f["type"] for f in frames] == ["skills.changed"]


def test_codex_write_keeps_the_rest_of_config_toml(world):
    config = world.codex / "config.toml"
    original = '# my codex\nmodel = "gpt-5"\n\n[mcp_servers.x]\ncommand = "npx"  # keep\n\n[[skills.config]]\nname = "old"\nenabled = false\n'
    config.write_text(original, encoding="utf-8")
    os.chmod(config, 0o600)
    reply = put(world, harness="codex", skill="sme")
    assert reply.status_code == 200 and reply.json()["restart_required"] is True
    text = config.read_text()
    assert text.startswith(original.rstrip("\n"))
    rules = tomllib.loads(text)["skills"]["config"]
    assert rules == [{"name": "old", "enabled": False}, {"name": "sme", "enabled": False}]
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert (world.codex / "config.toml.bak").read_text() == original
    assert put(world, harness="codex", skill="sme").json()["wrote"] is False
    project = put(world, harness="codex", file="project", project_path=str(world.project))
    assert project.status_code == 200
    skill_md = os.path.realpath(world.project / ".agents" / "skills" / "sme" / "SKILL.md")
    assert {"path": skill_md, "enabled": False} in tomllib.loads(config.read_text())["skills"]["config"]
    assert put(world, harness="codex", state="on").status_code == 200
    kept = tomllib.loads(config.read_text())
    assert [r.get("name") for r in kept["skills"]["config"] if "name" in r] == ["old"]
    assert kept["mcp_servers"] == {"x": {"command": "npx"}} and kept["model"] == "gpt-5"
    assert put(world, harness="codex", state="name-only").status_code == 400
    assert put(world, harness="codex", file="local").status_code == 400


def test_codex_layout_the_editor_cannot_handle_is_refused(world):
    config = world.codex / "config.toml"
    config.write_text('skills = { config = [] }\nmodel = "x"\n', encoding="utf-8")
    reply = put(world, harness="codex")
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "codex_config_edit_unsafe"
    assert config.read_text() == 'skills = { config = [] }\nmodel = "x"\n'
    config.write_text("= broken", encoding="utf-8")
    assert put(world, harness="codex").json()["detail"]["code"] == "settings_unparseable"


def test_negative_control_the_guard_blocks_the_real_home(monkeypatch):
    real = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    calls = []
    monkeypatch.setattr(config_writer, "commit", lambda path, *a, **k: calls.append(str(path)))
    monkeypatch.setattr(config_writer, "create_if_absent", lambda path, *a, **k: calls.append(str(path)))
    with pytest.raises(OutsideTempWriteError):
        claude_overrides.write_skill_override(real, "sme", "off")
    assert calls == []
