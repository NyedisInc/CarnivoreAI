
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s7fix_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s7fix_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.companies import store as companies
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import beast_mode, swarm_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.swarm import body, body_create, brief, definition, delivery, routing, store, thread_port, wake_prompt
from src.core.swarm.facade import SwarmFacade
from tests.python.swarm.test_swarm_card_settle_and_retry import _dialog, _item, world  # noqa: F401

OWNER_REF = "huddle:msg:7"
OWNER_WORDS = "build a tiny site for a coffee shop, nothing fancy"


class Port:

    def __init__(self) -> None:
        self.cards = []

    async def ensure_thread(self, key, title): ...
    async def settle_cards(self, ref, **kw): ...
    async def close_open_cards(self, thread_key, prefix): ...

    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref, text))
        return len(self.cards)

    async def owner_message(self, thread_key, ref):
        return OWNER_WORDS if (thread_key, ref) == ("all", OWNER_REF) else None


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state, root = tmp_path / "state", tmp_path / "carnivore-projects"
    state.mkdir()
    root.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: root, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    port, woke, told = Port(), [], []
    thread_port.register(port)

    async def wake(app_state, agent_id, reason, authority, orders="", owner_message_ref=None, **kw):
        woke.append(SimpleNamespace(agent_id=agent_id, authority=authority, orders=orders, ref=owner_message_ref))

    async def deliver(app_state, agent_id, text, **kw):
        told.append(SimpleNamespace(agent_id=agent_id, text=text, **kw))
        return "delivered"

    monkeypatch.setattr(body, "wake", wake)
    monkeypatch.setattr(delivery, "deliver_text", deliver)
    rows, agents = {}, {}
    with closing(connect(db_path_for(state), create=False)) as conn:
        acme = companies.create_company(conn, "Acme")

        def agent(slug, rank, **kw):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created', 'running',"
                         " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{slug}", f"cloude_{slug}", str(tmp_path)))
            rows[slug] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{slug}",)).fetchone()[0]
            row = store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(),
                                     repo_dir=str(tmp_path / slug), effort="high", **kw)
            store.set_session_row(conn, row["id"], rows[slug])
            conn.execute("UPDATE swarm_agents SET state = 'awake' WHERE id = ?", (row["id"],))
            agents[slug] = store.get_agent(conn, row["id"])

        agent("alpha", "alpha")
        hq = root / "Acme HQ"
        hq.mkdir()
        hq_project = body_create.register_project(conn, str(hq), "Acme HQ")
        companies.assign_project(conn, hq_project["id"], acme["id"])
        companies.set_hq_project(conn, acme["id"], hq_project["id"])
        agent("acmeboss", "company", company_id=acme["id"], project_id=hq_project["id"])
    yield SimpleNamespace(state=state, root=root, port=port, woke=woke, told=told, rows=rows, agents=agents, acme=acme, hq=hq_project)
    thread_port.register(None)


def _db(env, work):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        return work(conn)


def _suggest(env, slug, **args):
    info = SimpleNamespace(session=SimpleNamespace(id=f"ses_{slug}"), tmux_session=f"cloude_{slug}", session_row_id=env.rows[slug])

    async def infos():
        return [info]

    view = SimpleNamespace(list_session_infos=infos, app=SimpleNamespace(state=SimpleNamespace()))
    caller = AgentCaller(session_id=f"ses_{slug}", tmux_name=f"cloude_{slug}", current_session_id=f"ses_{slug}")
    result = asyncio.run(swarm_tools.swarm_suggest(view, caller, args))
    text = result["content"][0]["text"]
    if result.get("isError"):
        raise ToolError(text)
    return json.loads(text)


def _decide(env, ref, decision="approve"):
    asyncio.run(SwarmFacade(env.state, lambda: asyncio.sleep(0, []), SimpleNamespace()).card_decided(ref, decision, "", ""))


def _owner_said(env, ref=OWNER_REF):
    _db(env, lambda c: store.record_delivery(c, env.agents["alpha"]["id"], authority="owner", source="owner_chat", owner_message_ref=ref))


def test_n1_approval_delivers_the_owners_exact_words_and_tells_the_suggester(env):
    _owner_said(env)
    made = _suggest(env, "alpha", kind="company", name="Beans", reason="a coffee shop is a company of its own")
    assert _db(env, lambda c: c.execute("SELECT owner_message_ref FROM swarm_suggestions").fetchone()[0]) == OWNER_REF
    _decide(env, made["card_ref"])
    first = env.woke[-1]
    company_agent = _db(env, lambda c: c.execute("SELECT id FROM swarm_agents WHERE rank = 'company' AND display_name = 'Beans agent'").fetchone()[0])
    assert first.agent_id == company_agent and first.authority == "owner" and first.ref == OWNER_REF
    assert OWNER_WORDS in first.orders and "a coffee shop is a company of its own" in first.orders
    note = next(t for t in env.told if t.agent_id == env.agents["alpha"]["id"])
    assert note.authority == "data" and "Beans" in note.text and "owner_message_ref" not in vars(note)


def test_n1_a_suggestion_with_no_cited_owner_message_delivers_as_data(env):
    made = _suggest(env, "alpha", kind="company", name="Beans", reason="a coffee shop is a company of its own")
    assert _db(env, lambda c: c.execute("SELECT owner_message_ref FROM swarm_suggestions").fetchone()[0]) is None
    _decide(env, made["card_ref"])
    first = env.woke[-1]
    assert first.authority == "data" and first.ref is None and OWNER_WORDS not in first.orders
    assert "a coffee shop is a company of its own" in first.orders


def test_n4_a_project_agent_from_a_company_suggestion_has_the_company_agent_as_parent(env):
    _db(env, lambda c: c.execute(
        "INSERT INTO swarm_suggestions (by_agent_id, kind, name, reason, company_id, state, created_at, owner_message_ref)"
        " VALUES (?, 'company', 'Acme', 'r', ?, 'approved', '2026-10-05T00:00:00Z', ?)", (env.agents["alpha"]["id"], env.acme["id"], OWNER_REF)))
    made = _suggest(env, "acmeboss", kind="project", name="Bean There", reason="the first site")
    _decide(env, made["card_ref"])
    boss = env.agents["acmeboss"]
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        project = conn.execute("SELECT id FROM projects WHERE display_name = 'Bean There'").fetchone()
        agent = store.get_project_agent(conn, project["id"])
        assert agent["parent_id"] == boss["id"] and agent["company_id"] == env.acme["id"]
        assert [t["id"] for t in routing.chain_for(conn, agent)][0] == boss["id"]
        first = env.woke[-1]
        assert first.agent_id == agent["id"] and first.ref == OWNER_REF and OWNER_WORDS in first.orders
        conn.execute("UPDATE swarm_agents SET parent_id = NULL, company_id = NULL WHERE id = ?", (agent["id"],))
        orphan = store.get_agent(conn, agent["id"])
        ranks = [t["rank"] for t in routing.chain_for(conn, orphan)]
        assert ranks == ["company", "alpha"]


def test_n3_the_hq_or_a_project_with_an_agent_is_refused_and_an_agentless_one_is_not(env):
    with pytest.raises(ToolError):
        _suggest(env, "acmeboss", kind="project", name="Acme HQ", reason="turn on its agent")
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        (env.root / "Owned").mkdir()
        (env.root / "Free").mkdir()
        owned = body_create.register_project(conn, str(env.root / "Owned"), "Owned")
        free = body_create.register_project(conn, str(env.root / "Free"), "Free")
        for project in (owned, free):
            companies.assign_project(conn, project["id"], env.acme["id"])
        store.create_agent(conn, slug="owned-agent", rank="project", job="j", display_name="Owned agent", repo_dir=str(env.root / "Owned"),
                           effort="high", project_id=owned["id"])
    with pytest.raises(ToolError):
        _suggest(env, "acmeboss", kind="project", name="Owned", reason="again")
    assert _suggest(env, "acmeboss", kind="project", name="Free", reason="agentless, so allowed")["suggestion_id"]


def test_n2_a_second_post_of_an_open_dialog_card_posts_nothing_new(world):  # noqa: F811
    from src.core.db import connect as connect_db

    agent = store.get_agent(connect_db(db_path_for(world.tmp), create=False), world.boss["id"])
    dialog = _dialog("Allow external CLAUDE.md file imports?", "import ~/x/SKILL.md")
    first = asyncio.run(delivery.post_dialog_card(agent, delivery.IMPORT_PREFIX, "fp1", dialog))
    second = asyncio.run(delivery.post_dialog_card(agent, delivery.IMPORT_PREFIX, "fp1", dialog))
    assert second == first and _item(world, first)["state"] == "open"
    items = world.client.get(f"/api/v1/cplugs/huddle/lists/{world.boss['thread_key']}").json()["items"]
    assert [i["id"] for i in items if (i.get("swarm_ref") or "").startswith("import:")] == [first]
    asyncio.run(world.port.close_card(first, "done"))
    assert asyncio.run(delivery.post_dialog_card(agent, delivery.IMPORT_PREFIX, "fp1", dialog)) != first


def _row(rank, **kw):
    base = {"slug": "x", "display_name": "Espresso", "job": "the job", "goal": None, "rank": rank, "effort": "high", "effort_reason": None,
            "persona": None, "naming_state": "none"}
    return {**base, **kw}


def test_n5_project_and_task_orders_say_to_delegate_and_keep_work_small(env):
    project = _row("project")
    assert definition.PROJECT_RULES in body_create.brief_for(project)
    assert definition.PROJECT_RULES in wake_prompt.resume_message("manual", "", project)
    assert definition.PROJECT_RULES in wake_prompt.render_desk(project, "spawn", "", _empty_desk())
    task = _row("task", goal="add a footer", effort="medium")
    text = body_create.brief_for(task, "Espresso", "/m")
    assert definition.WORK_RULES in text and "add no new test infrastructure" in text
    assert definition.WORK_RULES in wake_prompt.resume_message("manual", "", task)
    assert definition.PROJECT_RULES not in brief.render_brief(brief.BriefSpec(
        slug="x", display_name="X", persona="p", name_reason="r", job="j", rank="task", order="o", goal="g", effort="medium",
        effort_reason="", parent_name="Boss", memory_dir="/m")).body


def _empty_desk():
    from src.core.swarm import desk

    return desk.Desk()


def test_n6_a_beast_mode_failure_logs_its_reason_and_stars_a_credential(monkeypatch, tmp_path):
    from src.core.mcp import pending

    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    caller = AgentCaller("ses_a", "cloude_a", "ses_a")

    async def refuse():
        raise ToolError("no contact granted with sk-ant-api03-" + "A" * 40)

    with structlog.testing.capture_logs() as logs, pytest.raises(ToolError):
        asyncio.run(beast_mode.run_unprompted(caller, "crosstalk_send", refuse))
    entry = next(e for e in logs if e["event"] == "mcp_action_failed_under_beast_mode")
    assert entry["error_type"] == "ToolError" and "no contact granted" in entry["reason"] and "A" * 40 not in entry["reason"]
