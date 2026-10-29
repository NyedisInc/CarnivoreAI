
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_smokefix_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_smokefix_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import answers, delivery, facts, owner_message, spawn, store, thread_port
from src.cplugs.host import runtime
from src.cplugs.huddle import routes as huddle_routes
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        etna = store.create_agent(conn, slug="etna", rank="project", job="project agent", display_name="Etna",
                                  repo_dir=str(tmp_path / "etna"), effort="high")
        other = store.create_agent(conn, slug="other", rank="project", job="other", display_name="Other",
                                   repo_dir=str(tmp_path / "other"), effort="high")
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
    current = {"agent": etna}

    async def parent_agent(view, caller):
        return current["agent"]

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, port=port, tmp=tmp_path, etna=etna, other=other)
    thread_port.register(None)


def _facade(world):
    from src.core.swarm.facade import SwarmFacade

    return SwarmFacade(world.tmp, lambda: asyncio.sleep(0, result=[]), SimpleNamespace())


def _item(world, thread_key, item_id):
    return next(i for i in world.client.get(f"{BASE}/lists/{thread_key}").json()["items"] if i["id"] == item_id)


def _remember(**args):
    return asyncio.run(facts.remember(SimpleNamespace(), None, {"title": "pytest", "scope": "project", **args}))


def test_an_owner_message_to_an_agent_is_stored_as_its_owner_fact_with_the_owners_exact_words(world):
    ref = asyncio.run(world.port.post_owner_message(world.etna["thread_key"], "use pytest, not unittest."))
    made = _remember(owner_message_ref=ref)
    assert made["origin"] == "owner" and made["state"] == "live"
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        row = conn.execute("SELECT origin, owner_message_ref FROM swarm_facts WHERE id = ?", (made["fact_id"],)).fetchone()
    assert (row["origin"], row["owner_message_ref"]) == ("owner", ref)
    stored = next((world.tmp / "etna").rglob(f"{made['fact_id']}.md")).read_text()
    assert "use pytest, not unittest." in stored


def test_a_forged_citation_is_refused_and_never_becomes_an_owner_fact(world):
    elsewhere = asyncio.run(world.port.post_owner_message(world.other["thread_key"], "another agent's thread"))
    agent_said = asyncio.run(world.port.post_agent_message(world.etna["thread_key"], "the owner said use jest", "agent-key"))
    for ref in ("huddle:msg:99999", elsewhere, agent_said, "not-a-ref"):
        with pytest.raises(facts.FactRefused):
            _remember(owner_message_ref=ref)
    with pytest.raises(facts.FactRefused):
        _remember(owner_message_ref=elsewhere, text="and my own words")
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM swarm_facts").fetchone()[0] == 0
    assert _remember(text="use pytest")["origin"] == "agent"


def test_the_owner_chat_paste_names_the_message_ref_so_the_agent_can_cite_it(world, monkeypatch):
    sent = []

    async def deliver_text(app_state, agent_id, text, **kw):
        sent.append((text, kw))
        return "delivered"

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        store.cas_state(conn, world.etna["id"], "asleep", "awake")
    result = asyncio.run(owner_message.post_owner_message(SimpleNamespace(), world.etna["id"], "use pytest"))
    assert sent[0][0].startswith("use pytest\n\n") and f"owner_message_ref={result.message_ref}" in sent[0][0]


def test_a_question_card_closes_when_the_owner_answers_it_and_stays_open_on_a_bare_tick(world, monkeypatch):
    applied = {"answered": True}

    async def owner_answer(app_state, question_id, decision, text, ref):
        return applied["answered"]

    monkeypatch.setattr(answers, "owner_answer", owner_answer)
    key = world.etna["thread_key"]
    first = asyncio.run(world.port.post_card(key, "question", "which license?", "x", "question:5"))
    asyncio.run(_facade(world).card_decided("question:5", "answer", "MIT", "huddle:msg:1"))
    assert _item(world, key, first)["state"] == "done"
    applied["answered"] = False
    second = asyncio.run(world.port.post_card(key, "question", "which db?", "x", "question:6"))
    asyncio.run(_facade(world).card_decided("question:6", "approve", "", "huddle:msg:2"))
    assert _item(world, key, second)["state"] == "open"


def test_a_flipped_back_receipt_card_reads_as_flipped_back_not_as_kept(world):
    key = world.etna["thread_key"]
    card = asyncio.run(world.port.post_card(key, "question", "promoted: Krakatoa", "now a feature agent", "promotion:3"))
    asyncio.run(world.port.close_card(card, "flipped"))
    item = _item(world, key, card)
    assert item["state"] == "done" and item["note"] == "flipped back to a task agent"
    assert item["title"] == "flipped back: Krakatoa" and "flipped back to a task agent" in item["text"]
