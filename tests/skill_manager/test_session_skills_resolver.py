
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import skills_manager_routes
from src.api.auth import require_auth
from src.core import slash_command_discovery as scd
from src.core.account_switch.pane_account import PaneProfile
from tests.skill_manager.test_inventory_shadowing import make_skill


class Manager:

    def __init__(self, rows: Dict[str, SimpleNamespace]) -> None:
        self.rows = rows

    async def get_session_info(self, session_id: Optional[str] = None):
        return self.rows.get(session_id)

    def tmux_socket_name(self) -> str:
        return "test-socket"


def row(family: Optional[str], working_dir: Path, tmux: str = "cloude_x") -> SimpleNamespace:
    session = SimpleNamespace(
        working_dir=str(working_dir), agent_type=family, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc)
    )
    return SimpleNamespace(agent_family=family, tmux_session=tmux, session=session)


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(scd, "CLAUDE_HOME", home / ".claude")
    make_skill(home / ".claude" / "skills", "home-only")
    make_skill(home / ".agents" / "skills", "codex-skill")
    profile = tmp_path / "profile"
    make_skill(profile / "skills", "prof-only")
    make_skill(profile / "skills", "review")
    make_skill(profile / "skills", "shared")
    (profile / "settings.json").write_text(json.dumps({"skillOverrides": {"review": "on"}}), encoding="utf-8")
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    make_skill(project / ".claude" / "skills", "shared", "project copy")
    make_skill(project / ".claude" / "skills", "proj-only")
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps({"skillOverrides": {"review": "off"}}), encoding="utf-8"
    )
    pane: Dict[str, Optional[str]] = {}

    async def fake_pane(socket: str, tmux_name: str, variable: str) -> PaneProfile:
        return PaneProfile(readable=True, value=pane.get(variable))

    monkeypatch.setattr(skills_manager_routes, "read_pane_profile", fake_pane)
    manager = Manager(
        {
            "ses_1": row("claude", project),
            "adopted:cloude_x": row("claude", project),
            "ses_codex": row("codex", project),
            "ses_hermes": row("hermes", project),
        }
    )
    app = FastAPI()
    app.include_router(skills_manager_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = manager
    return SimpleNamespace(client=TestClient(app), pane=pane, profile=profile, project=project)


def by_name(body: dict) -> Dict[str, list]:
    out: Dict[str, list] = {}
    for skill in body["skills"]:
        out.setdefault(skill["name"], []).append(skill)
    return out


def test_pane_profile_local_override_and_shadowing(world):
    world.pane["CLAUDE_CONFIG_DIR"] = str(world.profile)
    body = world.client.get("/api/v1/sessions/ses_1/skills").json()
    names = by_name(body)
    assert body["state"] == "ok" and body["profile"]["source"] == "pane"
    assert "prof-only" in names and "home-only" not in names
    assert names["prof-only"][0]["model_sees"] is True
    assert names["review"][0]["model_sees"] is False and names["review"][0]["reason"] == "off"
    assert names["review"][0]["state_source"] == "local"
    seen = {s["scope"]: s for s in names["shared"]}
    assert seen["personal"]["model_sees"] is True
    assert seen["project"]["model_sees"] is False and seen["project"]["reason"] == "shadowed"
    assert names["proj-only"][0]["model_sees"] is True
    assert body["budget_tokens_est"] == sum(s["tokens_est"] for s in body["skills"]) > 0
    assert body["restart_required"] is False and body["tokens_label"] == "est."


def test_unset_pane_profile_reads_home_claude(world):
    body = world.client.get("/api/v1/sessions/ses_1/skills").json()
    names = by_name(body)
    assert "home-only" in names and "prof-only" not in names and body["profile"]["source"] == "default"


def test_codex_restart_required_adopted_id_unknown_and_unsupported(world):
    codex = world.client.get("/api/v1/sessions/ses_codex/skills").json()
    assert codex["state"] == "ok" and codex["restart_required"] is True
    assert "codex-skill" in by_name(codex) and "home-only" not in by_name(codex)
    adopted = world.client.get("/api/v1/sessions/adopted:cloude_x/skills")
    assert adopted.status_code == 200 and adopted.json()["family"] == "claude"
    assert world.client.get("/api/v1/sessions/ses_nope/skills").status_code == 404
    other = world.client.get("/api/v1/sessions/ses_hermes/skills").json()
    assert other["state"] == "unsupported" and "skills" not in other


def _sub_session(world) -> None:
    sub = world.project / "sub" / "dir"
    sub.mkdir(parents=True)
    world.client.app.state.session_manager.rows["ses_sub"] = row("claude", sub)


def test_subfolder_session_reads_repo_root_local_override(world):
    world.pane["CLAUDE_CONFIG_DIR"] = str(world.profile)
    _sub_session(world)
    body = world.client.get("/api/v1/sessions/ses_sub/skills").json()
    review = by_name(body)["review"][0]
    assert (review["state"], review["model_sees"], review["reason"]) == ("off", False, "off")


def test_subfolder_local_file_root_wins_on_same_key(world):
    world.pane["CLAUDE_CONFIG_DIR"] = str(world.profile)
    _sub_session(world)
    sub_claude = world.project / "sub" / "dir" / ".claude"
    sub_claude.mkdir()
    (sub_claude / "settings.local.json").write_text(
        json.dumps({"skillOverrides": {"review": "on", "prof-only": "off"}}), encoding="utf-8"
    )
    skills = by_name(world.client.get("/api/v1/sessions/ses_sub/skills").json())
    assert skills["review"][0]["state"] == "off"
    assert skills["prof-only"][0]["state"] == "off"
