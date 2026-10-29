
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_climb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_climb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import answers, memory, routing, spawn, store, thread_port
from src.core.swarm.cards import port as card_port
from src.core.swarm.facade import SwarmFacade

VIEW = SimpleNamespace(app=SimpleNamespace(state=object()))
UNCOVERED = "should the walkthrough page be renamed to orchard walkthrough before launch"
OWNER_REF = "huddle:msg:347"
OWNER_REPLY = "Yes, rename it to Orchard-Walkthrough."


class Port:

    def __init__(self) -> None:
        self.cards, self.owner_messages = [], []

    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)

    async def settle_cards(self, ref, **kw): ...

    async def post_owner_message(self, key, text):
        self.owner_messages.append((key, text))
        return f"huddle:msg:{900 + len(self.owner_messages)}"

    async def close_card(self, item_id, state): ...


class Cards:

    def __init__(self) -> None:
        self.origin_ref = None

    async def cards(self, **kw):
        return [{"title": "rename the page", "origin": {"kind": "agent", "ref": self.origin_ref}}] if self.origin_ref else []


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    port, cards = Port(), Cards()
    thread_port.register(port)
    card_port.register(cards)
    conn = connect(db_path_for(tmp_path / "state"))
    mk = lambda slug, rank, parent=None: store.create_agent(  # noqa: E731
        conn, slug=slug, rank=rank, job=slug, display_name=slug.title(), effort="high", repo_dir=str(tmp_path / slug),
        parent_id=parent, project_id=None)
    alpha = mk("alpha", "alpha")
    nyedis = mk("nyedis", "company", alpha["id"])
    orchard = mk("orchard", "project", nyedis["id"])
    fixer = mk("fixer", "feature", orchard["id"])
    relay = mk("relay", "project", alpha["id"])
    for a in (alpha, nyedis, orchard, fixer, relay):
        memory.ensure_layout(memory.memory_dir(Path(a["repo_dir"]), a["slug"], a["memory_scope"]))
    told, current = [], {"agent": fixer}

    async def tell(app_state, agent_id, text, **kw):
        told.append(SimpleNamespace(agent_id=agent_id, text=text, **kw))
        return True

    async def parent_agent(view, caller):
        return current["agent"]

    monkeypatch.setattr(routing, "tell", tell)
    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    yield SimpleNamespace(conn=conn, alpha=alpha, nyedis=nyedis, orchard=orchard, fixer=fixer, relay=relay, port=port,
                          cards=cards, told=told, tmp=tmp_path, as_agent=lambda a: current.update(agent=a))
    thread_port.register(None)
    card_port.register(None)
    conn.close()


def run(coro):
    return asyncio.run(coro)


def owner_wrote(env, agent, at):
    env.conn.execute("INSERT INTO swarm_deliveries (agent_id, authority, source, owner_message_ref, delivered_at) "
                     "VALUES (?, 'owner', 'owner_chat', 'huddle:msg:1', ?)", (agent["id"], at))
    env.conn.commit()


def climb_to_owner(env):
    env.as_agent(env.fixer)
    qid = run(routing.ask(VIEW, None, {"question": UNCOVERED, "summary": "Rename the walkthrough page?"}))["question_id"]
    for tier in (env.orchard, env.nyedis, env.alpha):
        assert env.told[-1].agent_id == tier["id"] and env.port.cards == []
        env.as_agent(tier)
        run(answers.pass_up(VIEW, None, {"question_id": qid}))
    return qid


def test_every_tier_is_asked_then_the_card_lands_where_the_owner_is_reading(env):
    owner_wrote(env, env.fixer, "2026-10-08T05:00:00.000000Z")
    owner_wrote(env, env.nyedis, "2026-10-08T05:29:35.000000Z")
    qid = climb_to_owner(env)
    assert [t.agent_id for t in env.told] == [env.orchard["id"], env.nyedis["id"], env.alpha["id"]]
    assert all(t.source == "swarm_question" and t.authority == "data" for t in env.told)
    assert env.port.cards == [(env.nyedis["thread_key"], "question", f"question:{qid}")]
    assert env.conn.execute("SELECT state FROM swarm_questions WHERE id = ?", (qid,)).fetchone()[0] == "open"


def test_the_card_falls_back_to_the_relayer_then_the_all_list(env):
    assert routing.owner_thread(env.conn, [env.fixer], []) == routing.ALL_THREAD
    env.cards.origin_ref = str(env.relay["id"])
    qid = climb_to_owner(env)
    assert env.port.cards == [(env.relay["thread_key"], "question", f"question:{qid}")]


def test_the_owner_answer_carries_his_message_id_and_a_relayed_one_does_not(env):
    qid = climb_to_owner(env)
    env.told.clear()
    facade = SwarmFacade(env.tmp / "state", infos=None, app_state=object())
    run(facade.card_decided(f"question:{qid}", "answer", OWNER_REPLY, OWNER_REF))
    [got] = env.told
    assert got.agent_id == env.fixer["id"] and got.authority == "owner" and got.owner_message_ref == OWNER_REF
    assert OWNER_REF in got.text and OWNER_REPLY in got.text

    env.told.clear()
    env.as_agent(env.fixer)
    relayed_q = run(routing.ask(VIEW, None, {"question": "which colour is the staging banner on deploy pages",
                                              "summary": "Banner colour?"}))["question_id"]
    env.as_agent(env.orchard)
    run(answers.answer(VIEW, None, {"question_id": relayed_q, "owner_message_ref": OWNER_REF,
                                    "text": f"The owner answered your question {relayed_q} ({OWNER_REF}): orange"}))
    delivered = env.told[-1]
    assert delivered.agent_id == env.fixer["id"] and delivered.authority == "data"
    assert getattr(delivered, "owner_message_ref", None) is None
    assert f"> The owner answered your question {relayed_q}" in delivered.text


def test_a_forged_owner_ref_is_refused(env):
    qid = climb_to_owner(env)
    with pytest.raises(routing.QuestionRefused):
        run(answers.owner_answer(object(), qid, "answer", OWNER_REPLY, "huddle:msg:347 or anything"))
