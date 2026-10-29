
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s3c_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s3c_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import answers, desk, facts, memory, routing, spawn, store, thread_port
from src.core.swarm.facade import SwarmFacade

VIEW = SimpleNamespace(app=SimpleNamespace(state=object()))
PROJECT_TEXT = "swap models with the model command, restarting the session after"
COMPANY_TEXT = "the staging banner colour is orange on every deploy page"
QUESTION = "how do we swap models and restart the session?"
UNCOVERED = "which vendor invoices the quarterly licence renewal"
OWNER_REPLY = "Acme Corp invoices the licence renewal every quarter, paid from the ops card."


class Port:

    def __init__(self) -> None:
        self.cards, self.owner_messages, self.closed = [], [], []

    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)

    async def settle_cards(self, ref, **kw): ...

    async def post_owner_message(self, key, text):
        self.owner_messages.append((key, text))
        return f"huddle:msg:{100 + len(self.owner_messages)}"

    async def close_card(self, item_id, state):
        self.closed.append((item_id, state))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    port = Port()
    thread_port.register(port)
    conn = connect(db_path_for(tmp_path / "state"))
    mk = lambda slug, rank, parent=None: store.create_agent(  # noqa: E731
        conn, slug=slug, rank=rank, job=slug, display_name=slug.title(), effort="high", repo_dir=str(tmp_path / slug),
        parent_id=parent, project_id=None)
    alpha = mk("alpha", "alpha")
    acme = mk("acme", "company", alpha["id"])
    loki = mk("loki", "project", acme["id"])
    fixer = mk("fixer", "feature", loki["id"])
    for a in (alpha, acme, loki, fixer):
        memory.ensure_layout(memory.memory_dir(Path(a["repo_dir"]), a["slug"], a["memory_scope"]))
    told, current = [], {"agent": fixer}

    async def tell(app_state, agent_id, text, **kw):
        told.append(SimpleNamespace(agent_id=agent_id, text=text, **kw))
        return True

    async def parent_agent(view, caller):
        return current["agent"]

    monkeypatch.setattr(routing, "tell", tell)
    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    yield SimpleNamespace(conn=conn, alpha=alpha, acme=acme, loki=loki, fixer=fixer, port=port, told=told, tmp=tmp_path,
                          as_agent=lambda a: current.update(agent=a))
    thread_port.register(None)
    conn.close()


def run(coro):
    return asyncio.run(coro)


def teach(env, agent, title, text):
    lid = env.conn.execute("INSERT INTO swarm_learning (agent_id, kind, text, owner_message_ref, created_at) "
                           "VALUES (?, 'sealed_answer', ?, 'huddle:msg:7', 'now')", (agent["id"], text)).lastrowid
    env.as_agent(agent)
    return run(facts.remember(None, None, {"title": title, "scope": "craft", "learning_id": lid}))["fact_id"]


def escalate(env, qid):
    state = lambda: env.conn.execute("SELECT state FROM swarm_questions WHERE id = ?", (qid,)).fetchone()[0]  # noqa: E731
    while state() in routing.WALKING:
        hop = env.conn.execute("SELECT agent_id FROM swarm_question_hops WHERE question_id = ? ORDER BY id DESC LIMIT 1",
                               (qid,)).fetchone()
        env.as_agent(store.get_agent(env.conn, hop[0]))
        run(answers.pass_up(VIEW, None, {"question_id": qid}))
    return state()


def ask(env, text):
    env.as_agent(env.fixer)
    return run(routing.ask(VIEW, None, {"question": text, "summary": "Can you answer this for the asker?"}))


def test_the_s3_chain(env):
    real = teach(env, env.loki, "swapping models", PROJECT_TEXT)
    teach(env, env.acme, "staging banner", COMPANY_TEXT)

    asked = ask(env, QUESTION)
    assert [t.agent_id for t in env.told] == [env.loki["id"]]
    assert env.port.cards == []
    env.as_agent(env.loki)
    done = run(answers.answer(VIEW, None, {"question_id": asked["question_id"], "text": "use /model, then restart",
                                           "fact_ids": [real]}))
    assert done["fact_ids"] == [real] and done["kind"] == "owner_fact"
    delivered = env.told[-1]
    assert delivered.agent_id == env.fixer["id"] and "swapping models" in delivered.text and "taught by you" in delivered.text
    assert "staging banner" not in delivered.text
    assert env.conn.execute("SELECT COUNT(*) FROM swarm_learning WHERE question_id = ?", (asked["question_id"],)).fetchone()[0] == 0

    env.told.clear()
    open_q = ask(env, UNCOVERED)
    assert open_q["state"] == "routing" and env.port.cards == []
    assert escalate(env, open_q["question_id"]) == "open"
    assert [t.agent_id for t in env.told] == [env.loki["id"], env.acme["id"], env.alpha["id"]]
    assert ("all", "question", f"question:{open_q['question_id']}") in env.port.cards

    env.told.clear()

    facade = SwarmFacade(env.tmp / "state", infos=None, app_state=object())
    run(facade.card_decided(f"question:{open_q['question_id']}", "answer", OWNER_REPLY, "huddle:msg:55"))
    assert [(t.agent_id, t.authority) for t in env.told] == [(env.fixer["id"], "owner")]
    assert OWNER_REPLY in env.told[0].text
    rows = env.conn.execute("SELECT agent_id, kind, text, owner_message_ref, state FROM swarm_learning WHERE question_id = ? "
                            "ORDER BY agent_id", (open_q["question_id"],)).fetchall()
    assert [r["agent_id"] for r in rows] == sorted([env.alpha["id"], env.acme["id"], env.loki["id"]])
    assert all(r["kind"] == "sealed_answer" and r["text"] == OWNER_REPLY and r["owner_message_ref"] == "huddle:msg:55"
               and r["state"] == "queued" for r in rows)
    for tier in (env.alpha, env.acme, env.loki):
        lines = desk.render(desk.gather(env.conn, tier))
        assert any("learning inbox" in ln for ln in lines) and any(OWNER_REPLY in ln for ln in lines)
