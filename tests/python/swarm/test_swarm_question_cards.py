
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_qcard_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_qcard_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import swarm_tools
from src.core.swarm import author_path, memory, routing, spawn, store, stream, thread_port
from src.core.swarm.cards import port as card_port
from src.models.swarm import SwarmConversationPage

VIEW = SimpleNamespace(app=SimpleNamespace(state=object()))
QUESTION = ("NOTE 1 red proof as ordered is impossible because the guard in delivery.py line 412 never runs. "
            "Should I drop the red proof or rewrite the guard first?")
SUMMARY = "Can the agent skip the failing-first proof on the trust fix, or must it rewrite the guard first?"


class Port:

    def __init__(self) -> None:
        self.cards, self.thread = [], []

    async def post_card(self, key, kind, title, text, ref):
        self.cards.append(SimpleNamespace(key=key, kind=kind, title=title, text=text, ref=ref))
        return len(self.cards)

    async def settle_cards(self, ref, **kw): ...

    async def read_thread(self, key, limit):
        return list(self.thread)


class Cards:

    def __init__(self, title: str) -> None:
        self.title = title

    async def cards(self, **kw):
        return [{"id": 9, "title": self.title}]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    port = Port()
    thread_port.register(port)
    conn = connect(db_path_for(tmp_path / "state"))
    conn.execute("INSERT INTO companies (id, name, created_at, updated_at) VALUES (1, 'Nyedis', 'x', 'x')")
    conn.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at, company_id) "
                 "VALUES (4, '/tmp/qc-4', '/tmp/qc-4', 'Orchardco', 'test', 'x', 'x', 1)")
    conn.commit()

    def mk(slug, rank, name, parent=None, **extra):
        return store.create_agent(conn, slug=slug, rank=rank, job=f"{slug} job", display_name=name, effort="high",
                                  repo_dir=str(tmp_path / slug), parent_id=parent, **extra)

    alpha = mk("alpha", "alpha", "SysOp")
    boss = mk("nyedis", "company", "Corvale elmhaven", alpha["id"], company_id=1)
    lead = mk("orchard", "project", "Orchardco agent", boss["id"], project_id=4)
    research = mk("research", "feature", "Orchard-Research", lead["id"], project_id=4)
    for a in (alpha, boss, lead, research):
        memory.ensure_layout(memory.memory_dir(Path(a["repo_dir"]), a["slug"], a["memory_scope"]))
    current = {"agent": research}

    async def tell(app_state, agent_id, text, **kw):
        return False

    async def parent_agent(view, caller):
        return current["agent"]

    monkeypatch.setattr(routing, "tell", tell)
    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    yield SimpleNamespace(conn=conn, alpha=alpha, boss=boss, lead=lead, research=research, port=port)
    thread_port.register(None)
    card_port.register(None)
    conn.close()


def run(coro):
    return asyncio.run(coro)


def card_entry(question_id: int) -> dict:
    return {"kind": "card", "id": f"item:{question_id}", "at": 1.0, "card": "question",
            "item": {"id": question_id, "swarm_ref": f"question:{question_id}"}}


def research_path(env, live=True):
    return [{"kind": "company", "name": "Nyedis", "agent_id": env.boss["id"]},
            {"kind": "project", "name": "Orchardco", "agent_id": env.lead["id"]},
            {"kind": "agent", "name": "Orchard-Research", "agent_id": env.research["id"] if live else None}]


def test_ask_stores_summary_task_and_path_and_the_card_reads_them_after_teardown(env):
    card_port.register(Cards("Researching new DLP providers"))
    qid = run(routing.ask(VIEW, None, {"question": QUESTION, "summary": SUMMARY}))["question_id"]

    row = env.conn.execute("SELECT summary, task FROM swarm_questions WHERE id = ?", (qid,)).fetchone()
    assert (row["summary"], row["task"]) == (SUMMARY, "Researching new DLP providers")
    card = env.port.cards[-1]
    assert card.ref == f"question:{qid}" and card.text == f"Orchard-Research: {SUMMARY} (task: Researching new DLP providers)"
    assert "Nobody above them" not in card.text and "word for word" not in card.text

    env.port.thread = [{"kind": "owner", "id": "msg:1", "at": 0.5, "text": "hi"},
                       {"kind": "agent", "id": "msg:2", "at": 0.6, "text": "on it"}, card_entry(qid)]
    page = run(stream.page(env.alpha))
    shown = SwarmConversationPage.model_validate(page).model_dump()["entries"]
    by_id = {e["id"]: e for e in shown}
    assert by_id["msg:1"]["author_path"] == [{"kind": "owner", "name": "you", "agent_id": None}]
    assert by_id["msg:2"]["author_path"] == [{"kind": "sysop", "name": "SysOp", "agent_id": env.alpha["id"]}]
    q = by_id[f"item:{qid}"]
    assert q["author_path"] == research_path(env)
    block = q["question"]
    assert (block["summary"], block["task"], block["details"]) == (SUMMARY, "Researching new DLP providers", QUESTION)
    assert block["askers"] == [{"agent_id": env.research["id"], "name": "Orchard-Research", "author_path": research_path(env)}]
    assert "routing" not in block and isinstance(block["asked_at"], float)
    assert all("author_path" in e for e in shown)

    env.conn.execute("UPDATE swarm_agents SET torn_down_at = 'x', state = 'torn_down' WHERE id = ?", (env.research["id"],))
    env.conn.commit()
    block = next(e for e in run(stream.page(env.alpha))["entries"] if e["id"] == f"item:{qid}")["question"]
    assert block["askers"][0]["agent_id"] is None and block["askers"][0]["author_path"] == research_path(env, live=False)
    assert block["task"] == "Researching new DLP providers"

    env.conn.execute("UPDATE swarm_agents SET torn_down_at = 'x', state = 'torn_down' WHERE id = ?", (env.lead["id"],))
    again = store.create_agent(env.conn, slug="orchard2", rank="project", job="j", display_name="Orchardco agent", effort="high",
                               repo_dir=str(Path(env.lead["repo_dir"]).parent / "orchard2"), parent_id=env.boss["id"], project_id=4)
    env.conn.commit()
    block = next(e for e in run(stream.page(env.alpha))["entries"] if e["id"] == f"item:{qid}")["question"]
    assert block["askers"][0]["author_path"][1] == {"kind": "project", "name": "Orchardco", "agent_id": again["id"]}


def test_task_override_and_job_fallback(env):
    qid = run(routing.ask(VIEW, None, {"question": "which vendor invoices the licence renewal?", "summary": SUMMARY,
                                       "task": "  pick a  vendor "}))["question_id"]
    assert env.conn.execute("SELECT task FROM swarm_questions WHERE id = ?", (qid,)).fetchone()[0] == "pick a vendor"
    qid = run(routing.ask(VIEW, None, {"question": "who signs the quarterly cloud invoice for the staging account?",
                                       "summary": SUMMARY}))["question_id"]
    assert env.conn.execute("SELECT task FROM swarm_questions WHERE id = ?", (qid,)).fetchone()[0] == "research job"


@pytest.mark.parametrize("summary", [None, "", "   "])
def test_ask_without_a_summary_is_refused_and_saves_nothing(env, summary):
    args = {"question": QUESTION} if summary is None else {"question": QUESTION, "summary": summary}
    with pytest.raises(routing.QuestionRefused, match="summary is required: one plain sentence the owner can answer"):
        run(routing.ask(VIEW, None, args))
    assert env.conn.execute("SELECT COUNT(*) FROM swarm_questions").fetchone()[0] == 0 and env.port.cards == []


@pytest.mark.parametrize("summary, rule", [
    ("Should we drop the proof? It cannot go red.", "one sentence"),
    ("Is the bug in routing.py?", "no file names or paths"),
    ("Should src/core keep the old cap?", "no file names or paths"),
    ("Is line 40 the one to change?", "no line numbers"),
    ("Should swarm_card_deal pick the top card?", "no code"),
    ("Do we call `ask` twice?", "no code"),
])
def test_ask_with_a_summary_the_owner_cannot_read_is_refused_and_saves_nothing(env, summary, rule):
    with pytest.raises(routing.QuestionRefused, match=rule):
        run(routing.ask(VIEW, None, {"question": QUESTION, "summary": summary}))
    assert env.conn.execute("SELECT COUNT(*) FROM swarm_questions").fetchone()[0] == 0 and env.port.cards == []


def test_event_entries_carry_the_path_of_who_acted(env):
    lead = dict(env.conn.execute("SELECT * FROM swarm_agents WHERE id = ?", (env.lead["id"],)).fetchone())
    entries = [{"kind": "event", "id": "ev:reported:report:1", "at": 1.0, "event": "reported", "ref": "report:1",
                "text": "Orchard-Research reported to Orchardco agent", "agent_id": env.research["id"], "report_id": 1},
               {"kind": "event", "id": "ev:answered:question:1", "at": 2.0, "event": "answered", "ref": "question:1",
                "text": "the owner answered", "question_id": 1, "answered_by": "owner"},
               {"kind": "event", "id": "ev:answered:question:2", "at": 3.0, "event": "answered", "ref": "question:2",
                "text": "Corvale elmhaven answered", "question_id": 2, "answered_by": f"agent:{env.boss['id']}"}]
    author_path.annotate(env.conn, lead, entries)
    assert [e["author_path"] for e in entries] == [
        research_path(env), [{"kind": "owner", "name": "you", "agent_id": None}],
        [{"kind": "company", "name": "Nyedis", "agent_id": env.boss["id"]}]]


def test_traffic_entries_carry_the_peer_session_uuid_both_ways(env):
    lead = dict(env.conn.execute("SELECT * FROM swarm_agents WHERE id = ?", (env.lead["id"],)).fetchone())
    entries = [{"kind": "traffic", "id": "xt:1", "at": 1.0, "direction": "in", "peer": "bot-Layer1", "peer_key": "uuid-cv",
                "text": "hi"},
               {"kind": "traffic", "id": "xt:2", "at": 2.0, "direction": "out", "peer": "bot-Layer1", "peer_key": "uuid-cv",
                "text": "yo"},
               {"kind": "traffic", "id": "xt:3", "at": 3.0, "direction": "in", "peer": "ghost", "peer_key": None, "text": "?"}]
    author_path.annotate(env.conn, lead, entries)
    assert [e.get("peer_session_uuid") for e in entries] == ["uuid-cv", "uuid-cv", None]
    assert all("peer_key" not in e for e in entries)
    assert entries[0]["author_path"] == [{"kind": "agent", "name": "bot-Layer1", "agent_id": None}]


def test_a_question_with_no_summary_task_or_path_falls_back(env):
    env.conn.execute("INSERT INTO swarm_questions (id, text, state, created_at) VALUES (50, ?, 'open', '2026-10-07T00:00:00Z')", (QUESTION,))
    env.conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (50, ?, 'x')", (env.research["id"],))
    env.conn.commit()
    block = author_path.question_card(env.conn, 50)
    assert block["summary"] == QUESTION.split(". ")[0] + "."
    assert block["task"] == "research job" and block["askers"][0]["author_path"] == research_path(env)


def test_summary_fallback_takes_the_first_sentence_and_cuts_at_a_word():
    assert author_path.summary_fallback("Drop the proof?  The guard\nnever runs.") == "Drop the proof?"
    long = "word " * 60 + "end."
    cut = author_path.summary_fallback(long)
    assert cut.endswith("…") and len(cut) <= author_path.SUMMARY_CHARS + 1 and cut[:-1].split()[-1] == "word"
    assert author_path.summary_fallback("short with no stop") == "short with no stop"


def test_swarm_ask_schema_carries_summary_and_task():
    desc, props, required, _ = swarm_tools.TOOLS["swarm_ask"]
    assert set(props) == {"question", "summary", "task"} and required == ["question", "summary"]
    assert "no file names, line numbers or code" in props["summary"]["description"]
    assert "changes for the owner" in props["summary"]["description"]
    assert "summary" in desc
