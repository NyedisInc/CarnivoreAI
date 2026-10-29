
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.core.crosstalk import bus, store as xstore
from src.core.db import connect, db_path_for
from src.core.mcp import byoai_tools, lean_answers, read_tools, session_target, tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import store as swarm_store, stream
from tests.crosstalk.test_inbox_newest_first import ALICE, BOB, messages  # noqa: F401
from tests.python.swarm.test_swarm_api_reads import world  # noqa: F401

CALLER = AgentCaller("ses_1", "cloude_a", "ses_1", scope="write")


class _Manager:

    async def list_session_infos(self) -> list:
        return []


async def ask(name: str, args: dict, manager: object = None) -> dict:
    answer = await tools.call_tool(manager or _Manager(), CALLER, name, args)
    assert not answer.get("isError"), answer
    return json.loads(answer["content"][0]["text"])


def sizes(name: str, lean: object, full: object) -> tuple:
    pair = (len(json.dumps(lean)), len(json.dumps(full)))
    print(f"SIZE {name} lean={pair[0]} full={pair[1]}")
    return pair


@pytest.mark.asyncio
async def test_swarm_roster_lean_keeps_what_addresses_an_agent(world):
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        for n in range(12):
            swarm_store.create_agent(conn, slug=f"agent-{n}", rank="feature", job="fix the login flow", display_name=f"Agent {n}",
                                     repo_dir=str(world.state), effort="high", persona="a long persona " * 20)
    lean = await ask("swarm_roster", {}, world.manager)
    full = await ask("swarm_roster", {"detail": True}, world.manager)
    row = lean["agents"][0]
    assert set(row) <= set(lean_answers._ROSTER_KEYS) and {"id", "slug", "display_name", "rank", "state"} <= set(row)
    for dropped in ("persona", "repo_dir", "thread_key", "character_seed", "placement_reason", "session_uuid"):
        assert dropped not in row and dropped in full["agents"][0]
    assert lean["limits"] == full["limits"] and "threads_ready" in full
    assert [a["id"] for a in lean["agents"]] == [a["id"] for a in full["agents"]]
    lean_size, full_size = sizes("swarm_roster", lean, full)
    assert lean_size < full_size


@pytest.mark.asyncio
async def test_swarm_conversation_defaults_to_twenty_and_detail_to_fifty(monkeypatch):
    seen = []

    async def page(agent, *, since=None, limit=0, **_):
        seen.append(limit)
        return {"entries": [], "cursor": None}

    async def agent_row(agent_id):
        return {"id": agent_id}

    monkeypatch.setattr(stream, "page", page)
    monkeypatch.setattr("src.core.swarm.views.get_agent_row", agent_row)
    await ask("swarm_conversation", {"agent_id": 1})
    await ask("swarm_conversation", {"agent_id": 1, "detail": True})
    await ask("swarm_conversation", {"agent_id": 1, "limit": 200})
    await ask("swarm_conversation", {"agent_id": 1, "since": "e1"})
    assert seen == [20, 50, 200, 50]
    bad = await tools.call_tool(_Manager(), CALLER, "swarm_conversation", {"agent_id": 1, "detail": "yes"})
    assert bad["isError"]


def _inbox_caller(monkeypatch) -> None:
    async def identity(_view, _caller):
        return BOB

    monkeypatch.setattr(bus, "caller_identity", identity)


@pytest.mark.asyncio
async def test_crosstalk_inbox_lean_drops_internal_columns_and_keeps_every_word(messages, monkeypatch):
    _inbox_caller(monkeypatch)
    lean = await ask("crosstalk_inbox", {})
    full = await ask("crosstalk_inbox", {"detail": True})
    assert [m["text"] for m in lean["messages"]] == [m["text"] for m in full["messages"]]
    for dropped in ("sender_key", "receiver_epoch", "sender_uuid", "native_key", "landed_anchor", "delivery_path"):
        assert dropped not in lean["messages"][0] and dropped in full["messages"][0]
    assert {"id", "thread", "sender_id", "sender_name", "text", "status", "created_at"} <= set(lean["messages"][0])
    lean_size, full_size = sizes("crosstalk_inbox", lean, full)
    assert lean_size < full_size


@pytest.mark.asyncio
async def test_a_held_message_is_marked_delivered_only_with_its_full_text_in_the_answer(messages, monkeypatch):
    _inbox_caller(monkeypatch)
    long_text = ("every word counts " * 1200)[:20000]
    carol = {**ALICE, "key": "uuid-c", "id": "sc", "uuid": "uuid-c", "name": "Carol"}
    xstore.grant_contact(carol["key"], BOB["key"], carol["epoch"], BOB["epoch"])
    held = xstore.reserve(sender=carol, receiver=BOB, text=long_text, expect_reply=False)
    with closing(xstore._conn()) as conn:
        conn.execute("UPDATE crosstalk_messages SET status='held', reason='native_receipt_pending:x' WHERE id=?", (held["id"],))
    lean = await ask("crosstalk_inbox", {"limit": 5})
    with closing(xstore._conn()) as conn:
        settled = {r[0] for r in conn.execute("SELECT id FROM crosstalk_messages WHERE status='delivered' AND delivered_at IS NOT NULL "
                                              "AND id=?", (held["id"],))}
    assert settled == {held["id"]}
    row = next(m for m in lean["messages"] if m["id"] == held["id"])
    assert row["text"] == long_text and row["status"] == "delivered"


@pytest.mark.asyncio
async def test_projects_list_lean_shortens_the_description_and_keeps_the_path(monkeypatch):
    from src.api import projects_service

    rows = [SimpleNamespace(id=n, name=f"p{n}", path=f"/work/p{n}", description="a long description " * 40, company_id=1,
                            company_name="Co", color="blue", archived_at=None, parent_project_id=None, storage=None)
            for n in range(10)]
    monkeypatch.setattr(projects_service, "current_view", lambda *a, **k: rows)
    monkeypatch.setattr(projects_service, "views_to_responses", lambda view, _cls: view)
    lean = await ask("projects_list", {})
    full = await ask("projects_list", {"detail": True})
    assert lean["projects"][0]["path"] == "/work/p0" and len(lean["projects"][0]["description"]) <= 120
    assert full["projects"][0]["description"] == "a long description " * 40
    assert {k: v for k, v in lean["projects"][0].items() if k != "description"} == \
        {k: v for k, v in full["projects"][0].items() if k != "description"}
    lean_size, full_size = sizes("projects_list", lean, full)
    assert lean_size < full_size


@pytest.mark.asyncio
async def test_sessions_list_lean_cuts_to_fifty_and_detail_keeps_two_hundred(monkeypatch):
    infos = [SimpleNamespace(session=SimpleNamespace(id=f"ses_{n}", working_dir="/w", agent_type="claude"), tmux_session=f"t{n}",
                             label=f"l{n}", agent_type="claude", project_name="p", activity_status="idle", unread=False,
                             host_key="local", host_label=None, host_state=None, task_lead=None, do_not_disturb=None) for n in range(230)]

    class Resolver:
        def __init__(self, _manager): ...
        async def infos(self): return infos
        async def asleep_rows(self): return []

    monkeypatch.setattr(session_target, "TargetResolver", Resolver)
    lean = await ask("sessions_list", {})
    full = await ask("sessions_list", {"detail": True})
    few = await ask("sessions_list", {"limit": 3})
    assert len(lean["sessions"]) == 50 and lean["truncated"] and lean["total"] == 230
    assert len(full["sessions"]) == 200 and full["truncated"] and "total" not in full
    assert len(few["sessions"]) == 3
    assert lean["sessions"][0] == full["sessions"][0]
    lean_size, full_size = sizes("sessions_list", lean, full)
    assert lean_size < full_size


@pytest.mark.asyncio
async def test_perf_profile_lean_is_a_top_fifteen_summary(monkeypatch):
    from src.core.perf_hooks import sampler

    def table(key, n):
        return [{key: f"{key}{i}", "weight": 1.0} for i in range(n)]

    seen = {}

    async def fake_profile(request):
        seen["top"] = request.top
        top = request.top
        return {"seconds": 5.0, "process_cpu_seconds": 1.0, "threads": table("thread", top),
                "stacks": [{"thread": "t", "weight": 1.0, "samples": 3, "frames_leaf_first": [f"f{j}" for j in range(40)]}
                           for _ in range(top)],
                "functions_inclusive": table("function", top), "functions_self": table("line", top),
                "calls": {"subprocess": table("detail", top), "totals": [{"event": "subprocess", "count": 9}]}, "gc": {}}

    monkeypatch.setattr(sampler, "profile", fake_profile)
    lean = await ask("perf_profile", {"seconds": 3})
    assert seen["top"] == 15
    full = await ask("perf_profile", {"seconds": 3, "detail": True})
    assert seen["top"] == 25
    assert len(lean["stacks"]) == 15 and len(lean["stacks"][0]["frames_leaf_first"]) == 8 and lean["stacks"][0]["frames_total"] == 40
    assert len(full["stacks"][0]["frames_leaf_first"]) == 40 and "frames_total" not in full["stacks"][0]
    assert lean["process_cpu_seconds"] == 1.0 and lean["calls"]["totals"] == full["calls"]["totals"]
    lean_size, full_size = sizes("perf_profile", lean, full)
    assert lean_size < full_size
    named = await ask("perf_profile", {"seconds": 3, "top": 5})
    assert seen["top"] == 5 and len(named["threads"]) == 5


@pytest.mark.asyncio
async def test_ai_models_list_caps_at_twenty_five_with_the_total(monkeypatch):
    from src.api import ai_routes

    models = [{"id": f"model-{n}", "name": f"Model {n}"} for n in range(80)]

    async def connection_models(connection_id, refresh, cached_only=False):
        return {"fetched_at": 1, "models": models, "recent": ["model-1"]}

    monkeypatch.setattr(ai_routes, "connection_models", connection_models)
    lean = await ask("ai_models_list", {"connection_id": "c1"})
    full = await ask("ai_models_list", {"connection_id": "c1", "detail": True})
    assert len(lean["models"]) == 25 and lean["models_total"] == 80 and "detail true" in lean["models_note"]
    assert full["models"] == models and "models_total" not in full
    lean_size, full_size = sizes("ai_models_list", lean, full)
    assert lean_size < full_size
    small = lean_answers.models({"models": models[:5]})
    assert small == {"models": models[:5]}


def test_detail_must_be_a_boolean():
    from src.core.mcp.common import ToolError

    assert lean_answers.detail_flag({}) is False and lean_answers.detail_flag({"detail": True}) is True
    with pytest.raises(ToolError, match="detail"):
        lean_answers.detail_flag({"detail": 1})
