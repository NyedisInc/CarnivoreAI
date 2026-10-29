
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s3b_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s3b_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import answers, facts, memory, routing, spawn, store, thread_port
from src.core.swarm.facade import SwarmFacade
from tests.python.swarm.test_swarm_routing_chain import escalate

OWNER_TEXT = "swap models with the model command, restarting the session after"
QUESTION = "how do we swap models and restart the session?"
VIEW = SimpleNamespace(app=SimpleNamespace(state=object()))


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
    loki = mk("loki", "project", alpha["id"])
    feat, feat2 = mk("fixer", "feature", loki["id"]), mk("mender", "feature", loki["id"])
    for a in (alpha, loki, feat, feat2):
        memory.ensure_layout(memory.memory_dir(Path(a["repo_dir"]), a["slug"], a["memory_scope"]))
    told, current = [], {"agent": feat}

    async def tell(app_state, agent_id, text, **kw):
        told.append(SimpleNamespace(agent_id=agent_id, text=text, **kw))
        return True

    async def parent_agent(view, caller):
        return current["agent"]

    monkeypatch.setattr(routing, "tell", tell)
    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    yield SimpleNamespace(conn=conn, alpha=alpha, loki=loki, feat=feat, feat2=feat2, port=port, told=told,
                          as_agent=lambda a: current.update(agent=a), tmp=tmp_path)
    thread_port.register(None)
    conn.close()


def run(coro):
    return asyncio.run(coro)


def teach(env, agent, title, text, ref="huddle:msg:7"):
    lid = env.conn.execute("INSERT INTO swarm_learning (agent_id, kind, text, owner_message_ref, created_at) "
                           "VALUES (?, 'sealed_answer', ?, ?, 'now')", (agent["id"], text, ref)).lastrowid
    env.as_agent(agent)
    return run(facts.remember(None, None, {"title": title, "scope": "craft", "learning_id": lid}))["fact_id"]


def ask(env, agent, text=QUESTION):
    env.as_agent(agent)
    return run(routing.ask(VIEW, None, {"question": text, "summary": "Can you answer this for the asker?"}))


def state_of(env, qid):
    return env.conn.execute("SELECT state FROM swarm_questions WHERE id = ?", (qid,)).fetchone()[0]


def test_a_forged_fact_id_is_dropped_and_only_the_routed_tier_may_answer(env):
    real = teach(env, env.loki, "swapping models", OWNER_TEXT)
    env.as_agent(env.alpha)
    other = run(facts.remember(None, None, {"title": "alpha fact", "scope": "craft", "text": "alpha keeps the roadmap"}))["fact_id"]
    asked = ask(env, env.feat)
    assert asked["state"] == "routing" and not asked["joined"]
    assert [t.agent_id for t in env.told] == [env.loki["id"]]
    assert env.told[0].authority == "data" and env.told[0].source == "swarm_question"
    assert env.port.cards == []

    env.as_agent(env.alpha)
    with pytest.raises(routing.QuestionRefused):
        run(answers.answer(VIEW, None, {"question_id": asked["question_id"], "text": "guess", "fact_ids": []}))

    env.as_agent(env.loki)
    done = run(answers.answer(VIEW, None, {"question_id": asked["question_id"], "text": "use /model, then restart",
                                           "fact_ids": [real, "f_000000000000", other, "not an id", real]}))
    assert done["fact_ids"] == [real] and done["kind"] == "owner_fact"
    assert "taught by you" in done["receipt"] and "swapping models" in done["receipt"]
    row = env.conn.execute("SELECT * FROM swarm_receipts WHERE question_id = ?", (asked["question_id"],)).fetchone()
    assert row["fact_ids"] == f'["{real}"]' and row["rendered"] == done["receipt"]
    delivered = env.told[-1]
    assert delivered.agent_id == env.feat["id"] and delivered.source == "swarm_answer" and delivered.authority == "data"
    assert "> use /model, then restart" in delivered.text and done["receipt"] in delivered.text
    assert state_of(env, asked["question_id"]) == "answered"

    q2 = ask(env, env.feat2, "what colour is the staging banner on the deploy page")
    assert escalate(env, q2["question_id"]) == "open"
    q3 = ask(env, env.feat, "swap models restart session again please")
    env.as_agent(env.loki)
    guess = run(answers.answer(VIEW, None, {"question_id": q3["question_id"], "text": "unsure", "fact_ids": ["f_000000000000"]}))
    assert guess["kind"] == "judgment" and "own judgment, no stored fact" in guess["receipt"] and guess["fact_ids"] == []


def test_kill_reopens_the_questions_it_answered_and_routes_them_again(env):
    real = teach(env, env.loki, "swapping models", OWNER_TEXT)
    asked = ask(env, env.feat)
    qid = asked["question_id"]
    env.as_agent(env.loki)
    run(answers.answer(VIEW, None, {"question_id": qid, "text": "use /model", "fact_ids": [real]}))
    unrelated = ask(env, env.feat2, "where does the dev server bind its port")
    escalate(env, unrelated["question_id"])
    env.told.clear()

    reopened = run(answers.kill_fact(VIEW.app.state, real))
    assert reopened == [qid]
    mem = memory.memory_dir(Path(env.loki["repo_dir"]), "loki", env.loki["memory_scope"])
    assert not (mem / "facts" / f"{real}.md").exists()
    assert env.conn.execute("SELECT state FROM swarm_facts WHERE id = ?", (real,)).fetchone()[0] == "killed"
    withdrawn = [c for c in env.port.cards if c[2] == f"withdrawn:{qid}"]
    assert withdrawn == [(env.feat["thread_key"], "info", f"withdrawn:{qid}")]
    assert [t.agent_id for t in env.told] == [env.alpha["id"]]
    escalate(env, qid)
    q = env.conn.execute("SELECT * FROM swarm_questions WHERE id = ?", (qid,)).fetchone()
    assert q["state"] == "open" and q["answer_text"] is None and q["card_ref"]
    assert ("all", "question", f"question:{qid}") in env.port.cards
    assert state_of(env, unrelated["question_id"]) == "open"
    with pytest.raises(facts.FactRefused):
        run(answers.kill_fact(VIEW.app.state, real))


def test_answered_once_joins_and_the_owner_answer_reaches_every_asker(env):
    first = ask(env, env.feat, "where is the staging database password rotated each month?")
    assert escalate(env, first["question_id"]) == "open"
    cards = len(env.port.cards)
    joined = ask(env, env.feat2, "where is the staging database password rotated?")
    assert joined["joined"] and joined["question_id"] == first["question_id"]
    assert len(env.port.cards) == cards
    assert [r[0] for r in env.conn.execute("SELECT agent_id FROM swarm_question_askers WHERE question_id = ? ORDER BY agent_id",
                                           (first["question_id"],))] == sorted([env.feat["id"], env.feat2["id"]])
    unlike = ask(env, env.feat2, "how many retries does the uploader attempt before giving up")
    assert not unlike["joined"] and unlike["question_id"] != first["question_id"]

    env.told.clear()
    facade = SwarmFacade(env.tmp / "state", infos=None, app_state=object())
    with pytest.raises(Exception):
        run(facade.card_decided(f"question:{first['question_id']}", "answer", "AWS console", ""))
    run(facade.card_decided(f"question:{first['question_id']}", "approve", "", ""))
    assert state_of(env, first["question_id"]) == "open"
    run(facade.card_decided(f"question:{first['question_id']}", "answer", "It rotates in the AWS console on the 1st.", "huddle:msg:42"))

    assert state_of(env, first["question_id"]) == "answered"
    assert {t.agent_id for t in env.told} == {env.feat["id"], env.feat2["id"]}
    for t in env.told:
        assert t.authority == "owner" and t.owner_message_ref.startswith("huddle:msg:") and t.source == "swarm_answer"
        assert "It rotates in the AWS console on the 1st." in t.text
    assert [m[1] for m in env.port.owner_messages] == ["It rotates in the AWS console on the 1st."] * 2
    rows = env.conn.execute("SELECT agent_id, kind, text, owner_message_ref, state FROM swarm_learning WHERE question_id = ? "
                            "ORDER BY agent_id", (first["question_id"],)).fetchall()
    assert [r["agent_id"] for r in rows] == sorted([env.alpha["id"], env.loki["id"]])
    assert {(r["kind"], r["text"], r["owner_message_ref"], r["state"]) for r in rows} == {
        ("sealed_answer", "It rotates in the AWS console on the 1st.", "huddle:msg:42", "queued")}
    with pytest.raises(Exception):
        run(facade.card_decided(f"question:{first['question_id']}", "answer", "again", "huddle:msg:43"))


def test_a_pass_or_a_timeout_sends_the_question_up(env):
    teach(env, env.loki, "swapping models", OWNER_TEXT)
    asked = ask(env, env.feat)
    qid = asked["question_id"]
    env.as_agent(env.loki)
    assert run(answers.pass_up(VIEW, None, {"question_id": qid, "reason": "not sure"}))["state"] == "routing"
    env.as_agent(env.alpha)
    assert run(answers.pass_up(VIEW, None, {"question_id": qid}))["state"] == "open"
    assert env.conn.execute("SELECT outcome FROM swarm_question_hops WHERE question_id = ? AND agent_id = ?",
                            (qid, env.loki["id"])).fetchone()[0] == "passed"
    q2 = ask(env, env.feat, "swap models command zebra giraffe")
    hop = env.conn.execute("SELECT * FROM swarm_question_hops WHERE question_id = ? ORDER BY id DESC", (q2["question_id"],)).fetchone()
    assert hop["outcome"] == "timeout" and hop["agent_id"] == env.loki["id"]
    assert run(routing.sweep(object())) >= 1 and state_of(env, q2["question_id"]) == "routing"
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    env.conn.execute("UPDATE swarm_question_hops SET at = ? WHERE id = ?", (past, hop["id"]))
    run(routing.sweep(object()))
    assert state_of(env, q2["question_id"]) == "routing"
    env.conn.execute("UPDATE swarm_question_hops SET at = ? WHERE question_id = ? AND outcome = 'timeout'", (past, q2["question_id"]))
    run(routing.sweep(object()))
    assert state_of(env, q2["question_id"]) == "open"
    with pytest.raises(routing.QuestionRefused):
        env.as_agent(env.loki)
        run(answers.answer(VIEW, None, {"question_id": q2["question_id"], "text": "late", "fact_ids": []}))
