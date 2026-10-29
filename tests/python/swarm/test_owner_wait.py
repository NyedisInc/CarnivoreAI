
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_owait_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_owait_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import alerts, owner_wait, store, thread_port, views


class Port:

    def __init__(self) -> None:
        self.cards, self.settled = [], []

    async def open_cards(self):
        return list(self.cards)

    async def settle_cards(self, ref, **kw):
        self.settled.append(ref)


def _ask(conn, agent_id: int, asked_at: str) -> int:
    qid = conn.execute("INSERT INTO swarm_questions (text, state, created_at) VALUES ('q', 'open', ?)", (asked_at,)).lastrowid
    conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (?, ?, ?)", (qid, agent_id, asked_at))
    return int(qid)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    port = Port()
    thread_port.register(port)
    conn = connect(db_path_for(tmp_path / "state"))

    def mk(slug, rank, parent=None):
        return store.create_agent(conn, slug=slug, rank=rank, job=f"{slug} job", display_name=slug, effort="high",
                                  repo_dir=str(tmp_path / slug), parent_id=parent)

    alpha = mk("alpha", "alpha")
    lead = mk("lead", "project", alpha["id"])
    fresh, skipped, gone = (mk(s, "feature", lead["id"]) for s in ("fresh", "skipped", "gone"))
    q_fresh = _ask(conn, fresh["id"], "2026-10-27T10:00:00Z")
    q_skipped = _ask(conn, skipped["id"], "2026-10-08T01:00:00Z")
    conn.execute("INSERT INTO swarm_wakes (agent_id, started_at, ended_at, reason, mode, authority, end_reason) "
                 "VALUES (?, '2026-10-12T21:00:00Z', '2026-10-12T22:00:00Z', 'manual', 'fresh', 'data', 'sleep')", (skipped["id"],))
    q_gone = _ask(conn, gone["id"], "2026-10-27T10:00:00Z")
    conn.commit()
    assert store.tear_down(conn, gone["id"])
    port.cards = [{"thread_key": alpha["thread_key"], "kind": "question", "swarm_ref": f"question:{q}", "title": f"q{q}", "text": "q"}
                  for q in (q_fresh, q_skipped, q_gone)]
    yield SimpleNamespace(conn=conn, port=port, alpha=alpha, lead=lead, fresh=fresh, skipped=skipped, gone=gone,
                          q=SimpleNamespace(fresh=q_fresh, skipped=q_skipped, gone=q_gone))
    thread_port.register(None)
    conn.close()


def _entry(qid: int) -> dict:
    return {"kind": "card", "item": {"swarm_ref": f"question:{qid}", "state": "open", "status": "question", "thread": []}}


def test_stale_never_counts_fresh_counts_and_the_node_matches_the_chat(env):
    live = owner_wait.live_questions(env.conn)
    assert set(live) == {env.q.fresh}, "only the question whose asker still waits is live"
    assert [owner_wait.entry_waits(_entry(q), live) for q in (env.q.fresh, env.q.skipped, env.q.gone)] == [True, False, False]
    review = {"kind": "card", "item": {"swarm_ref": "", "state": "review", "status": "review", "thread": []}}
    assert owner_wait.entry_waits(review, live) is False, "a card in Review is the board's, never a wait"

    agents = store.list_agents(env.conn)
    fields = asyncio.run(views._live_fields(agents))
    chat_waits = {env.fresh["id"]} if owner_wait.entry_waits(_entry(env.q.fresh), live) else set()
    assert {a for a, f in fields.items() if f["question_waiting"]} == chat_waits, "the node's tell is the chat's answer"
    assert fields[env.alpha["id"]]["alert"] == "priority" and fields[env.alpha["id"]]["alert_reason"] == f"q{env.q.fresh}"

    env.port.cards = [c for c in env.port.cards if c["swarm_ref"] != f"question:{env.q.fresh}"]
    env.port.cards.append({"thread_key": env.lead["thread_key"], "kind": "info", "swarm_ref": f"wake_failed:{env.gone['id']}:7",
                           "title": "wake failed", "text": "x"})
    fields = asyncio.run(views._live_fields(agents))
    assert fields[env.alpha["id"]]["alert"] is None
    assert fields[env.lead["id"]]["alert"] is None, "a wake card about a torn-down child never shakes its parent"


def test_settle_stale_closes_with_a_record_and_keeps_the_fresh_one(env):
    env.port.cards.append({"thread_key": env.lead["thread_key"], "kind": "info", "swarm_ref": f"wake_failed:{env.gone['id']}:7",
                           "title": "wake failed", "text": "x"})
    asyncio.run(alerts.settle_stale())
    states = dict(env.conn.execute("SELECT id, state FROM swarm_questions").fetchall())
    assert states == {env.q.fresh: "open", env.q.skipped: "closed", env.q.gone: "closed"}, "closed, never deleted"
    assert sorted(env.port.settled) == sorted([f"question:{env.q.skipped}", f"question:{env.q.gone}", f"wake_failed:{env.gone['id']}:7"])


def test_only_a_card_that_asks_the_owner_spikes_and_a_woken_agent_clears_its_wake_cards(env):
    lead_key, child = env.lead["thread_key"], env.fresh["id"]
    env.port.cards = [{"thread_key": lead_key, "kind": k, "swarm_ref": r, "title": t, "text": t} for k, r, t in (
        ("info", f"wake_refused:{child}", "cannot wake yet"), ("info", f"wake_failed:{child}:3", "wake failed"),
        ("info", f"dead:{child}:3", "body died"), ("done", "report:9", "report"), ("info", "spawn_refused:4", "cannot spawn yet"))]
    agents = store.list_agents(env.conn)
    assert asyncio.run(views._live_fields(agents))[env.lead["id"]]["alert"] is None, "nothing here waits on the owner"
    env.port.cards.append({"thread_key": lead_key, "kind": "question", "swarm_ref": "promotion:1", "title": "promoted: x", "text": "x"})
    assert asyncio.run(views._live_fields(agents))[env.lead["id"]]["alert"] == "priority", "a decision card asks him"
    env.port.cards.append({"thread_key": lead_key, "kind": "info", "swarm_ref": f"stuck:{child}:ab", "title": "stuck", "text": "x"})
    assert asyncio.run(views._live_fields(agents))[env.lead["id"]]["alert"] == "immediate", "a stuck dialog asks him"

    env.conn.execute("UPDATE swarm_agents SET state = 'awake' WHERE id = ?", (child,))
    env.conn.commit()
    asyncio.run(alerts.settle_stale())
    assert {f"wake_refused:{child}", f"wake_failed:{child}:3"} <= set(env.port.settled), "the agent woke: its wake cards close"
    assert f"stuck:{child}:ab" not in env.port.settled and "promotion:1" not in env.port.settled
