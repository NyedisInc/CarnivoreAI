
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s2g_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s2g_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import body, body_create, delivery, project_agent, store, thread_port
from src.cplugs.host import runtime
from src.cplugs.huddle import routes as huddle_routes
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"
PROFILE = {"id": "swarm-ok", "harness": "claude", "label": "ok", "permissions": "ask", "model": {"mode": "fixed", "value": "opus"}}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"launch_profiles": {"profiles": [PROFILE]}}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(tmp_path).status == "ok"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        boss = store.create_agent(conn, slug="p-agent", rank="project", job="project agent", display_name="p agent",
                                  repo_dir=str(tmp_path), effort="high")
        project = body_create.register_project(conn, str(repo), "repo")
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    app.include_router(swarm_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    ctx = host.context("huddle")
    port = TaskManagerSwarmPort(ctx)
    ctx.swarm.register_thread_port(port)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, port=port, tmp=tmp_path, boss=boss, project=project, tmp_cfg=cfg, app=app)
    thread_port.register(None)


def _facade(world):
    from src.core.swarm.facade import SwarmFacade

    return SwarmFacade(world.tmp, lambda: asyncio.sleep(0, result=[]), SimpleNamespace())


def _item(world, item_id):
    items = world.client.get(f"{BASE}/lists/{world.boss['thread_key']}").json()["items"]
    return next(i for i in items if i["id"] == item_id)


def _dialog(question, body_text):
    return SimpleNamespace(question=question, body=body_text, kind="other", fingerprint="fp1")


def test_a_non_approve_decision_closes_the_cards_item(world, monkeypatch):
    async def noop(*a, **k):
        return None

    monkeypatch.setattr(delivery, "answer_dialog_card", noop)
    item = asyncio.run(world.port.post_card(world.boss["thread_key"], "question", "allow external imports?", "x",
                                            f"import:{world.boss['id']}:fp1"))
    assert _item(world, item)["state"] == "open"
    asyncio.run(_facade(world).card_decided(f"import:{world.boss['id']}:fp1", "answer", "keep disabled", "msg"))
    assert _item(world, item)["state"] == "done"


def test_a_second_trust_card_closes_the_first(world):
    agent = store.get_agent(connect(db_path_for(world.tmp), create=False), world.boss["id"])
    first = asyncio.run(delivery.post_trust_card(agent, 1, "aa"))
    second = asyncio.run(delivery.post_trust_card(agent, 2, "bb"))
    assert _item(world, first)["state"] == "done"
    assert _item(world, second)["state"] == "open"


def test_dialog_card_text_has_no_border_drawing_and_secrets_stay_starred(world):
    rule = "─" * 40
    dialog = _dialog(f"Allow external CLAUDE.md file imports? {rule}",
                     f"{rule}\n│ sk-ant-api03-" + "A" * 40 + " is imported │\n{rule}")
    agent = store.get_agent(connect(db_path_for(world.tmp), create=False), world.boss["id"])
    item = asyncio.run(delivery.post_dialog_card(agent, delivery.IMPORT_PREFIX, "fp1", dialog))
    text = _item(world, item)["text"]
    assert "Allow external CLAUDE.md file imports?" in text and "imported" in text
    assert not any(0x2500 <= ord(ch) < 0x25A0 for ch in text)
    assert "A" * 40 not in text


def test_an_unknown_launch_profile_is_422_and_writes_no_row(world):
    r = world.client.post(f"/api/v1/swarm/projects/{world.project['id']}/agent", json={"launch_profile": "no-such-profile"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_agent"
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        assert store.get_project_agent(conn, world.project["id"]) is None


def test_a_retry_naming_a_valid_profile_replaces_a_stored_bad_one(world, monkeypatch):
    wakes = []

    async def wake(app_state, agent_id, *a, **k):
        wakes.append(agent_id)
        if len(wakes) == 1:
            raise body.BodyError("refused")

    monkeypatch.setattr(body, "wake", wake)
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        stuck = store.create_agent(conn, slug="stuck", rank="project", job="project agent for repo", display_name="repo agent",
                                   repo_dir=world.project["root"], effort="high", project_id=world.project["id"],
                                   naming_state="none", launch_profile="no-such-profile")
    with pytest.raises(body.BodyError):
        asyncio.run(project_agent.turn_on(SimpleNamespace(), world.project["id"]))
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        assert store.get_agent(conn, stuck["id"])["launch_profile"] == "no-such-profile"
    asyncio.run(project_agent.turn_on(SimpleNamespace(), world.project["id"], "swarm-ok"))
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        assert store.get_agent(conn, stuck["id"])["launch_profile"] == "swarm-ok"
    assert wakes == [stuck["id"], stuck["id"]]


def test_a_trust_card_closes_only_on_positive_evidence_and_keeps_its_mark(world):
    from datetime import datetime, timedelta, timezone

    agent = store.get_agent(connect(db_path_for(world.tmp), create=False), world.boss["id"])
    seen = SimpleNamespace(evidence=SimpleNamespace(dialog=None), stale=False, observed_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    info = SimpleNamespace(tmux_session=None, session=SimpleNamespace(id="s1"), startup_gate="ready")
    state = SimpleNamespace(attention_watcher=SimpleNamespace(observation_for=lambda sid: seen))

    async def live_info(_state, _agent):
        return info

    original, body.live_info = body.live_info, live_info
    try:
        item = asyncio.run(delivery.post_trust_card(agent, 9, "cc"))
        delivery._trust_posted.add((9, "cc"))
        assert asyncio.run(delivery.close_gone_trust_cards(state, agent, 9)) is False
        seen.observed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        info.startup_gate = "unknown"
        assert asyncio.run(delivery.close_gone_trust_cards(state, agent, 9)) is False
        info.startup_gate = "ready"
        assert asyncio.run(delivery.close_gone_trust_cards(state, agent, 9)) is True
        assert _item(world, item)["state"] == "done"
        assert (9, "cc") in delivery._trust_posted
    finally:
        body.live_info = original
        delivery.forget_wake(9)


def test_one_turn_on_inits_a_plain_folder_and_closes_the_old_card_and_refuses_unsafe_folders(world, monkeypatch):
    async def wake(app_state, agent_id, *a, **k):
        await body.run_db(lambda c: store.cas_state(c, agent_id, "asleep", "awake"))

    monkeypatch.setattr(body, "wake", wake)
    world.app.state.session_manager = SimpleNamespace(list_session_infos=lambda: asyncio.sleep(0, result=[]))

    def register(folder):
        folder.mkdir(parents=True, exist_ok=True)
        with closing(connect(db_path_for(world.tmp), create=False)) as conn:
            return body_create.register_project(conn, str(folder), folder.name)

    def agent_of(project_id):
        with closing(connect(db_path_for(world.tmp), create=False)) as conn:
            return store.get_project_agent(conn, project_id)

    outer = world.tmp / "outer"
    inner = register(outer / "inner")
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    r = world.client.post(f"/api/v1/swarm/projects/{inner['id']}/agent")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "swarm_refused"
    assert "inside the git repo at" in r.json()["detail"]["message"]
    assert not (outer / "inner" / ".git").exists() and agent_of(inner["id"]) is None

    home = register(world.tmp / "home")
    real_home = os.environ["HOME"]
    monkeypatch.setenv("HOME", str(world.tmp / "home"))
    r = world.client.post(f"/api/v1/swarm/projects/{home['id']}/agent")
    monkeypatch.setenv("HOME", real_home)
    assert r.status_code == 409 and "is your home folder" in r.json()["detail"]["message"]
    assert not (world.tmp / "home" / ".git").exists() and agent_of(home["id"]) is None

    plain = world.tmp / "plain"
    loose = register(plain)
    ref = f"gitinit:{loose['id']}"
    asyncio.run(world.port.post_card(str(loose["id"]), "question", "start a git repo here?", "left from before #1434", ref))
    card = world.client.get(f"{BASE}/lists/{loose['id']}", params={"include_swarm": "1"}).json()["items"][-1]
    assert card["swarm_ref"] == ref and card["state"] == "open"

    def refuse(root):
        raise body_create.CreateRefused("git init failed in the agent's folder")

    real_init = body_create.ensure_repo
    monkeypatch.setattr(body_create, "ensure_repo", refuse)
    r = world.client.patch(f"{BASE}/items/{card['id']}", json={"approved": True, "expected_revision": card["revision"]})
    assert r.status_code == 409 and r.json()["detail"] == {"code": "swarm_card_refused", "detail": "git init failed in the agent's folder"}
    after = world.client.get(f"{BASE}/lists/{loose['id']}", params={"include_swarm": "1"}).json()["items"][-1]
    assert after["id"] == card["id"] and after["state"] == "open"
    assert not (plain / ".git").exists()

    monkeypatch.setattr(body_create, "ensure_repo", real_init)
    r = world.client.post(f"/api/v1/swarm/projects/{loose['id']}/agent")
    assert r.status_code == 201, r.text
    assert (plain / ".git").is_dir()
    made = agent_of(loose["id"])
    assert made is not None and made["rank"] == "project" and made["state"] == "awake"
    closed = next(i for i in world.client.get(f"{BASE}/lists/{loose['id']}", params={"include_swarm": "1"}).json()["items"] if i["id"] == card["id"])
    assert closed["state"] == "done"
    assert not [i for i in world.client.get(f"{BASE}/lists/{loose['id']}", params={"include_swarm": "1"}).json()["items"]
                if i["id"] != card["id"] and (i.get("swarm_ref") or "").startswith("gitinit:")]
