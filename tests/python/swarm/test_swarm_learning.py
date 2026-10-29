
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s3c2_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s3c2_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import answers, desk, facts, learning, memory, question_events, routing, spawn, store, thread_port, wake_prompt
from src.core.swarm.facade import SwarmFacade
from src.core.trail_entry import utc_now

VIEW = SimpleNamespace(app=SimpleNamespace(state=object()))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    conn = connect(db_path_for(tmp_path / "state"))
    mk = lambda slug, rank, parent=None: store.create_agent(  # noqa: E731
        conn, slug=slug, rank=rank, job=slug, display_name=slug.title(), effort="high", repo_dir=str(tmp_path / slug),
        parent_id=parent, project_id=None)
    alpha = mk("alpha", "alpha")
    loki = mk("loki", "project", alpha["id"])
    fixer = mk("fixer", "feature", loki["id"])
    for a in (alpha, loki, fixer):
        memory.ensure_layout(memory.memory_dir(Path(a["repo_dir"]), a["slug"], a["memory_scope"]))
    current = {"agent": fixer}

    async def parent_agent(view, caller):
        return current["agent"]

    async def tell(app_state, agent_id, text, **kw):
        return True

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    monkeypatch.setattr(routing, "tell", tell)
    yield SimpleNamespace(conn=conn, alpha=alpha, loki=loki, fixer=fixer, tmp=tmp_path, as_agent=lambda a: current.update(agent=a))
    thread_port.register(None)
    conn.close()


def run(coro):
    return asyncio.run(coro)


def items(env, agent, kind=None):
    return [r for r in env.conn.execute("SELECT * FROM swarm_learning WHERE agent_id = ? ORDER BY id", (agent["id"],))
            if kind is None or r["kind"] == kind]


def test_a_huddle_tell_to_a_child_queues_one_skip_level_item_for_its_parent(env):
    facade = SwarmFacade(env.tmp / "state", infos=None, app_state=object())
    facade.record_delivery(env.fixer["id"], "owner", "huddle_tell", "huddle:msg:31", "use the staging db")
    facade.record_delivery(env.fixer["id"], "owner", "huddle_tell", "huddle:msg:31", "use the staging db")
    facade.record_delivery(env.fixer["id"], "data", "crosstalk", "crosstalk:msg:2", None)
    facade.record_delivery(env.alpha["id"], "owner", "huddle_tell", "huddle:msg:32", "hello alpha")
    rows = items(env, env.loki, "skip_level")
    assert len(rows) == 1 and rows[0]["state"] == "queued" and rows[0]["owner_message_ref"] == "huddle:msg:31"
    assert rows[0]["text"] == "to Fixer: use the staging db"
    assert items(env, env.alpha) == []


def test_push_up_queues_a_discovery_and_a_parent_stamp_never_makes_it_an_owner_fact(env):
    env.as_agent(env.fixer)
    run(facts.remember(None, None, {"title": "retry flag", "scope": "project", "text": "pass --retry 3 to the uploader",
                                    "push_up": True}))
    found = items(env, env.loki, "discovery")
    assert len(found) == 1 and found[0]["text"] == "pass --retry 3 to the uploader" and found[0]["owner_message_ref"] is None
    env.as_agent(env.loki)
    stamped = run(facts.remember(None, None, {"title": "retry flag", "scope": "craft", "learning_id": found[0]["id"]}))
    assert stamped["origin"] == "agent"
    assert items(env, env.loki, "discovery")[0]["state"] == "stamped"
    events = run(question_events.learned_events(env.loki, 10))
    assert [e["event"] for e in events] == ["learned"] and events[0]["fact_id"] == stamped["fact_id"]


def test_a_tier_is_due_at_the_batch_size_or_after_a_day_and_the_desk_and_resume_line_carry_the_inbox(env):
    now = datetime.now(timezone.utc)
    for n in range(3):
        env.conn.execute("INSERT INTO swarm_learning (agent_id, kind, text, created_at) VALUES (?, 'discovery', ?, 'now')",
                         (env.loki["id"], f"note {n}"))
    assert learning.due(env.conn, now, 10, 24) == []
    assert learning.due(env.conn, now, 3, 24) == [env.loki["id"]]
    env.conn.execute("INSERT INTO swarm_learning (agent_id, kind, text, created_at) VALUES (?, 'skip_level', 'old words', "
                     "'2020-01-01T00:00:00.000000Z')", (env.alpha["id"],))
    assert learning.due(env.conn, now, 10, 24) == [env.alpha["id"]]
    assert learning.due(env.conn, now - timedelta(days=4000), 10, 24) == []

    work = desk.gather(env.conn, env.loki)
    assert "note 2" in wake_prompt.render_desk(env.loki, "learning", "", work)
    resume = wake_prompt.resume_message("learning", "", inbox=work.learning)
    assert "learning inbox (3 waiting)" in resume and "note 0" in resume
    wake_id = store.open_wake(env.conn, env.loki["id"], reason="learning", mode="fresh", authority="data")
    learning.mark_delivered(env.conn, [i["id"] for i in work.learning], wake_id)
    assert desk.gather(env.conn, env.loki).learning == []


def test_an_answered_event_carries_the_receipt_and_its_facts(env):
    env.as_agent(env.loki)
    lid = env.conn.execute("INSERT INTO swarm_learning (agent_id, kind, text, owner_message_ref, created_at) "
                           "VALUES (?, 'sealed_answer', 'use /model', 'huddle:msg:7', 'now')", (env.loki["id"],)).lastrowid
    fact = run(facts.remember(None, None, {"title": "swapping models", "scope": "craft", "learning_id": lid}))["fact_id"]
    qid = env.conn.execute("INSERT INTO swarm_questions (text, state, created_at) VALUES ('how to swap models', 'routing', ?)", (utc_now(),)).lastrowid
    env.conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (?, ?, ?)", (qid, env.fixer["id"], utc_now()))
    env.conn.execute("INSERT INTO swarm_question_hops (question_id, agent_id, coverage, outcome, at) VALUES (?, ?, 1.0, 'timeout', "
                     "'2999-01-01T00:00:00.000000Z')", (qid, env.loki["id"]))
    run(answers.answer(VIEW, None, {"question_id": qid, "text": "use /model", "fact_ids": [fact]}))
    ev = [e for e in question_events._events(env.conn, env.fixer["id"], 10) if e["event"] == "answered"][0]
    assert ev["receipt"]["kind"] == "owner_fact" and "taught by you" in ev["receipt"]["rendered"]
    assert [f["id"] for f in ev["receipt"]["facts"]] == [fact] and ev["receipt"]["facts"][0]["scope"] == "craft"
