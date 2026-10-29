
from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.swarm import store


def _agent(conn, slug="alpha", rank="alpha", **kw):
    return store.create_agent(
        conn, slug=slug, rank=rank, job="j", display_name=slug, repo_dir="/tmp/swarm-x", effort="high", **kw
    )


def test_v58_migrates_to_v59_and_second_open_wake_raises(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 58)
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'swarm_agents'").fetchone()
        with conn:
            run_chain(conn, 58, 59)
        assert CURRENT_SCHEMA_VERSION >= 59
        for name in ("swarm_agents", "swarm_wakes", "swarm_deliveries", "swarm_repo_visibility", "swarm_one_open_wake"):
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone(), name

        agent = _agent(conn)
        assert agent["thread_key"] == "all" and agent["state"] == "asleep"
        wake = store.open_wake(conn, agent["id"], reason="manual", mode="fresh", authority="owner")
        assert wake and store.get_agent(conn, agent["id"])["state"] == "waking"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO swarm_wakes (agent_id, started_at) VALUES (?, 'x')", (agent["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            store.open_wake(conn, agent["id"], reason="manual", mode="fresh", authority="owner")
        assert store.live_body_count(conn) == 1
        assert store.close_wake(conn, wake, "sleep")
        conn.execute("INSERT INTO swarm_wakes (agent_id, started_at) VALUES (?, 'y')", (agent["id"],))


def test_store_rules(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 59)
        alpha = _agent(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _agent(conn, slug="alpha2")
        feat = _agent(conn, slug="feat-a", rank="feature", parent_id=alpha["id"])
        assert feat["thread_key"] == f"agent:{feat['id']}"
        assert store.cas_state(conn, feat["id"], "asleep", "awake") and not store.cas_state(conn, feat["id"], "asleep", "awake")
        with pytest.raises(sqlite3.IntegrityError):
            _agent(conn, slug="co", rank="company", harness="codex", thread_key="c1")
        with pytest.raises(sqlite3.IntegrityError):
            store.record_delivery(conn, feat["id"], authority="owner", source="owner_chat")
        store.record_delivery(conn, feat["id"], authority="owner", source="owner_chat", owner_message_ref="huddle:msg:1")
        assert store.tear_down(conn, feat["id"])
        _agent(conn, slug="feat-a", rank="feature", parent_id=alpha["id"])
