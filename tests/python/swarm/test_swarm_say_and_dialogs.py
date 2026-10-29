
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s2f_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s2f_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.auth import require_auth
from src.core.approvals.extract import Dialog, ROLE_OPTION, Row, extract_dialog
from src.core.db import connect, db_path_for
from src.core.db_steps import run_chain
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, body_create, definition, delivery, owner_message, say, spawn, store, thread_port
from src.core.swarm.facade import SwarmFacade
from src.cplugs.host import runtime
from src.cplugs.huddle import routes as huddle_routes
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"
CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 59)
        alpha = store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="Alpha", repo_dir=str(tmp_path), effort="high")
        loki = store.create_agent(conn, slug="loki", rank="project", job="j", display_name="Loki", repo_dir=str(tmp_path),
                                  effort="high", parent_id=alpha["id"])
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    ctx = host.context("huddle")
    port = TaskManagerSwarmPort(ctx)
    ctx.swarm.register_thread_port(port)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    pane = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="cloude_a", session_row_id=None)

    async def infos():
        return [pane]

    manager = SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, manager=manager, loki=loki, key=loki["thread_key"], port=port, tmp=tmp_path)
    thread_port.register(None)


def _stub_parent(monkeypatch, agent):
    async def parent_agent(view, caller):
        if caller.external:
            raise spawn.SpawnRefused("swarm tools are for Swarm agents")
        return agent

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)


def test_swarm_say_posts_an_agent_entry_the_conversation_returns(world, monkeypatch):
    _stub_parent(monkeypatch, world.loki)
    out = asyncio.run(tools.call_tool(world.manager, CALLER, "swarm_say", {"text": "the swap is in; token sk-ant-api03-" + "a" * 40}))
    assert not out.get("isError"), out
    assert json.loads(out["content"][0]["text"])["message_ref"].startswith("huddle:msg:")
    entries = asyncio.run(world.port.read_thread(world.key, 10))
    agent_entries = [e for e in entries if e["kind"] == "agent"]
    assert len(agent_entries) == 1 and agent_entries[0]["text"].startswith("the swap is in;")
    assert "a" * 40 not in agent_entries[0]["text"]

    external = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="t")
    refused = asyncio.run(tools.call_tool(world.manager, external, "swarm_say", {"text": "hi"}))
    assert refused.get("isError")
    assert len([e for e in asyncio.run(world.port.read_thread(world.key, 10)) if e["kind"] == "agent"]) == 1
    for bad in ({}, {"text": "  "}, {"text": "x" * (say.MAX_SAY_CHARS + 1)}):
        assert asyncio.run(tools.call_tool(world.manager, CALLER, "swarm_say", bad)).get("isError")


def test_owner_paste_and_wake_text_carry_no_reply_line(world, monkeypatch):
    pasted = []

    async def deliver_text(app_state, agent_id, text, **kw):
        pasted.append((text, kw["authority"]))
        return "delivered"

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    awake = dict(world.loki, state="awake")

    async def get_agent(fn):
        return awake

    monkeypatch.setattr(body, "run_db", get_agent)
    result = asyncio.run(owner_message.post_owner_message(object(), world.loki["id"], "swap the models"))
    assert result.outcome == "delivered"
    ref = result.message_ref
    assert pasted == [(f"swap the models\n\n{owner_message.REF_LINE.format(ref=ref)}", "owner")]
    from src.core.swarm import wake_prompt

    assert "swarm_say" not in wake_prompt.resume_message("owner_message", "")
    assert "swarm_say" not in wake_prompt.render_desk(world.loki, "owner_message", "", wake_prompt.desk_mod.Desk()).split("## open work")[0]


def test_upper_rank_settings_accept_child_crosstalk_and_a_recreate_rewrites_them(world, tmp_path):
    settings = json.loads(definition.render_settings(tmp_path / "mem"))
    assert settings["crossSessionInbound"] == "accept" and settings["permissions"]["allow"][-1] == "mcp__carnivore"
    agent = dict(world.loki, repo_dir=str(tmp_path / "repo"), memory_scope="project")
    (tmp_path / "repo").mkdir()
    body_create.write_settings(tmp_path, agent)
    from src.core.swarm import launch

    path = launch.settings_path(tmp_path, agent["id"])
    path.write_text('{"permissions": {}}\n')
    body_create.write_settings(tmp_path, agent)
    assert json.loads(path.read_text())["crossSessionInbound"] == "accept"
    feature = dict(agent, rank="feature", id=999)
    body_create.write_settings(tmp_path, feature)
    assert not launch.settings_path(tmp_path, 999).exists()


def _dialog(question: str, labels: list, fingerprint: str, body_text: str = "") -> Dialog:
    rows = tuple(Row(label, ROLE_OPTION, None, label.lower()) for label in labels)
    return Dialog(family="claude", kind="permission", question=question, body=body_text, rows=rows, cursor=0,
                  multi_select=False, fingerprint=fingerprint)


@pytest.fixture
def pane(world, monkeypatch):
    state = SimpleNamespace(dialog=None, answers=[])
    info = SimpleNamespace(tmux_session=None, session=SimpleNamespace(id="ses_1"), startup_gate="ready")
    watcher = SimpleNamespace(observation_for=lambda sid: SimpleNamespace(evidence=SimpleNamespace(dialog=state.dialog)))
    app_state = SimpleNamespace(attention_watcher=watcher)
    with closing(connect(db_path_for(world.tmp))) as conn:
        conn.execute("UPDATE swarm_agents SET state = 'awake' WHERE id = ?", (world.loki["id"],))
        agent = store.get_agent(conn, world.loki["id"])

    async def live_info(_state, _agent):
        return info

    async def send_answer(_state, session_id, fingerprint, label):
        state.answers.append((session_id, fingerprint, label))

    monkeypatch.setattr(body, "live_info", live_info)
    monkeypatch.setattr(delivery, "_send_answer", send_answer)
    state.app_state, state.info, state.agent = app_state, info, agent
    state.facade = SwarmFacade(world.tmp, lambda: asyncio.sleep(0, result=[]), app_state)
    state.cards = lambda: [i for i in world.client.get(f"{BASE}/lists/{world.key}").json()["items"] if i["swarm_ref"] != "chat"]
    return state


def test_held_message_dialog_is_one_card_and_approve_sends_deliver(world, pane):
    pane.dialog = _dialog("Held message from another session", ["Deliver", "Deny"], "fp-held", "from Hekla (feature agent)")

    async def go():
        for _ in range(3):
            await delivery._maybe_dialog_card(pane.app_state, pane.agent, 1, pane.info)
        await pane.facade.card_decided(pane.cards()[0]["swarm_ref"], "approve", "", "huddle:msg:1")

    asyncio.run(go())
    cards = pane.cards()
    assert len(cards) == 1 and cards[0]["swarm_ref"] == f"held:{pane.agent['id']}:fp-held" and "Hekla" in cards[0]["text"]
    assert pane.answers == [("ses_1", "fp-held", "Deliver")]
    asyncio.run(pane.facade.card_decided(cards[0]["swarm_ref"], "answer", "no", "huddle:msg:2"))
    assert pane.answers[-1][2] == "Deny"


def test_a_refused_paste_at_a_dialog_posts_the_card_and_a_changed_dialog_is_not_answered(world, pane, monkeypatch):
    import src.api.one_shot_routes as one_shot

    async def refuse(request, session_id, text):
        raise HTTPException(status_code=409, detail={"code": "pane_dialog_open"})

    monkeypatch.setattr(one_shot, "paste_through_gates", refuse)
    pane.dialog = _dialog("Allow external CLAUDE.md file imports?", ["Yes, allow external imports", "No, disable external imports"], "fp-imp")
    state, code = asyncio.run(delivery._attempt(pane.app_state, pane.agent["id"], "hi", "crosstalk", "data", "x:1", None))
    assert (state, code) == ("retry", "pane_dialog_open")
    (card,) = pane.cards()
    assert card["swarm_ref"].startswith(delivery.IMPORT_PREFIX) and card["kind"] == "question"
    pane.dialog = _dialog("Something else", ["Yes", "No"], "fp-other")
    with pytest.raises(body.BodyError):
        asyncio.run(pane.facade.card_decided(card["swarm_ref"], "approve", "", "huddle:msg:3"))
    assert pane.answers == []
    assert any(c["swarm_ref"].startswith(delivery.STUCK_PREFIX) for c in pane.cards())


def test_the_real_external_imports_screen_reads_as_a_dialog_and_gets_the_import_card(world, pane):
    dialog = extract_dialog((FIXTURES / "external_imports.txt").read_text(), "claude")
    assert dialog is not None and delivery._dialog_prefix(dialog) == delivery.IMPORT_PREFIX
    pane.dialog = dialog
    asyncio.run(delivery._maybe_dialog_card(pane.app_state, pane.agent, 1, pane.info))
    (card,) = pane.cards()
    asyncio.run(pane.facade.card_decided(card["swarm_ref"], "approve", "", "huddle:msg:4"))
    assert pane.answers[0][2] == "Yes, allow external imports"


def test_any_other_dialog_is_one_info_card_with_its_first_line_starred_and_no_buttons(world, pane):
    pane.dialog = _dialog("Do you want to create NOTES.txt? key sk-ant-api03-" + "b" * 40, ["Yes", "No"], "fp-edit")

    async def go():
        await delivery._maybe_dialog_card(pane.app_state, pane.agent, 1, pane.info)
        await delivery._maybe_dialog_card(pane.app_state, pane.agent, 1, pane.info)

    asyncio.run(go())
    (card,) = pane.cards()
    assert card["kind"] == "info" and card["text"].startswith("Loki is stuck on a dialog in its terminal: Do you want to create NOTES.txt?")
    assert "b" * 40 not in card["text"]
    asyncio.run(pane.facade.card_decided(card["swarm_ref"], "approve", "", "huddle:msg:5"))
    assert pane.answers == []
