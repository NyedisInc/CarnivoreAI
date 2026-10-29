
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_diet_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_diet_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import fact_life, facts, memory, question_events, routing, spawn, store

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
    loki = mk("loki", "project")
    fixer = mk("fixer", "feature", loki["id"])
    stranger = mk("stranger", "project")
    for a in (loki, fixer, stranger):
        memory.ensure_layout(memory.memory_dir(Path(a["repo_dir"]), a["slug"], a["memory_scope"]))
    current = {"agent": fixer}

    async def parent_agent(view, caller):
        return current["agent"]

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    monkeypatch.setattr(routing, "caller_agent", parent_agent)
    yield SimpleNamespace(conn=conn, loki=loki, fixer=fixer, stranger=stranger, as_agent=lambda a: current.update(agent=a))
    conn.close()


def _remember(title, text, **extra):
    return asyncio.run(facts.remember(VIEW, None, {"title": title, "scope": "project", "text": text, **extra}))


def _row(conn, fact_id):
    return conn.execute("SELECT * FROM swarm_facts WHERE id = ?", (fact_id,)).fetchone()


def test_a_note_expires_14_days_after_its_last_use_and_a_rule_never_does(env):
    note = _remember("staging db", "the staging db is reset every night at two")
    rule = _remember("release branch", "release work happens on the release branch only", kind="rule")
    used = _remember("deploy window", "deploys go out after six in the evening")
    assert (note["kind"], rule["kind"]) == ("note", "rule")
    now = datetime.now(timezone.utc)
    assert fact_life.expire(env.conn, now) == []
    later = now + timedelta(days=fact_life.NOTE_DAYS, minutes=1)
    fact_life.record_use(env.conn, used["fact_id"], "wake:1", fact_life._stamp(later - timedelta(days=13)))
    env.conn.commit()
    assert fact_life.expire(env.conn, later) == [note["fact_id"]]
    assert _row(env.conn, note["fact_id"])["state"] == "killed"
    assert _row(env.conn, rule["fact_id"])["state"] == "live" and _row(env.conn, used["fact_id"])["state"] == "live"
    assert not (memory.memory_dir(Path(env.fixer["repo_dir"]), env.fixer["slug"], env.fixer["memory_scope"])
                / "facts" / f"{note['fact_id']}.md").exists()


def test_a_note_used_in_three_conversations_becomes_a_rule_and_only_then_posts_a_learned_line(env):
    note = _remember("model swap", "swap models with the model command, never by editing settings")
    learned = lambda: [e for e in question_events._learned(env.conn, env.fixer["id"], 10) if e.get("fact_id") == note["fact_id"]]  # noqa: E731
    assert learned() == []
    for key in ("wake:1", "wake:1", "wake:2"):
        fact_life.record_use(env.conn, note["fact_id"], key)
    env.conn.commit()
    assert _row(env.conn, note["fact_id"])["kind"] == "note"
    env.conn.execute("INSERT INTO swarm_wakes (agent_id, started_at, reason, mode, authority, conversation_uuid) "
                     "VALUES (?, '2026-10-28T00:00:00.000000Z', 'manual', 'fresh', 'owner', 'conv-3')", (env.fixer["id"],))
    env.conn.commit()
    again = _remember("model swap", "swap models with the model command, never by editing settings")
    assert again["fact_id"] == note["fact_id"] and again.get("resaved") is True and again["kind"] == "rule"
    row = _row(env.conn, note["fact_id"])
    assert row["kind"] == "rule" and row["ruled_at"] is not None
    assert env.conn.execute("SELECT COUNT(*) FROM swarm_facts WHERE agent_id = ? AND state = 'live'", (env.fixer["id"],)).fetchone()[0] == 1
    assert [e["text"] for e in learned()] == ["new rule: model swap"]


def test_forget_reaches_own_and_childrens_facts_only(env):
    mine = _remember("flaky test", "the login test flakes under load, rerun it once")
    env.as_agent(env.stranger)
    with pytest.raises(facts.FactRefused):
        asyncio.run(_forget(mine["fact_id"]))
    env.as_agent(env.loki)
    assert asyncio.run(_forget(mine["fact_id"]))["state"] == "killed"


async def _forget(fact_id):
    from src.core.swarm import answers

    return await answers.forget(VIEW, None, {"fact_id": fact_id})
