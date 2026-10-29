
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from contextlib import closing
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_c2_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_c2_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import swarm_card_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import card_capacity_tools, card_tools, card_validate_tools, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.crosstalk import bus, store as crosstalk_store
from src.core.swarm import body, create, delivery, guard, reports, spawn, store, teardown, thread_port
from src.core.swarm.cards import deliver, ops, permits, port as card_port
from src.core.swarm.cards.names import CARD_TOOLS, OWNER_ONLY_CARD_TOOLS
from src.cplugs.huddle import rules, service
from src.cplugs.huddle.cards import policy
from src.cplugs.huddle.cards.port import TaskManagerCardPort
from src.core.work.storage import WorkStorage
from src.cplugs.sdk.cards import CardRefused

LIST = "16"
_STATE: List[Any] = [None]
APPROVED = tuple(sorted(rules.APPROVED_STATES))


class Port:

    def __init__(self) -> None:
        self.cards: List[Any] = []
        self.traffic: List[Any] = []
        self.owner: List[Any] = []

    async def ensure_thread(self, key, title): ...
    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)

    async def post_traffic(self, key, text, ref):
        self.traffic.append((key, text, ref))
        return f"huddle:msg:t{len(self.traffic)}"

    async def post_owner_message(self, key, text):
        self.owner.append((key, text))
        return f"huddle:msg:o{len(self.owner)}"

    async def close_card(self, item_id, state): ...
    async def archive_thread(self, key): ...


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    repo = tmp_path / "repo"
    repo.mkdir()
    policy.drain_kicks()
    ctx = SimpleNamespace(storage=WorkStorage(tmp_path / "huddle"), settings={"view": "area"}, swarm=None, notify=lambda *a, **k: None)
    huddle = service.store(ctx)
    card_port.register(TaskManagerCardPort(ctx))
    port = Port()
    thread_port.register(port)
    told: List[Dict[str, Any]] = []
    woke: List[int] = []
    keys: List[str] = []

    async def deliver_text(app_state, agent_id, text, **kw):
        told.append({"agent": agent_id, "text": text, **kw})
        return "delivered"

    async def wake(app_state, agent_id, *a, **kw):
        woke.append(agent_id)

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    monkeypatch.setattr(delivery, "record_for_session_row", lambda *a, **k: None)
    async def torn(app_state, agent):
        torn_down.append(agent["id"])

    torn_down: List[int] = []
    monkeypatch.setattr(body, "wake", wake)
    monkeypatch.setattr(teardown, "run", torn)
    rows: Dict[str, int] = {}
    agents: Dict[str, Dict[str, Any]] = {}
    with closing(connect(db_path_for(tmp_path / "state"), create=False)) as conn:
        conn.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at) VALUES (16, ?, ?, 'Zeta', 'test',"
                     " '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z')", (str(repo), str(repo)))

        def agent(slug, rank, parent=None, **extra):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created', 'running',"
                         " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{slug}", f"cloude_{slug}", str(repo)))
            rows[slug] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{slug}",)).fetchone()[0]
            row = store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(), repo_dir=str(repo), effort="high",
                                     parent_id=parent, goal=f"goal of {slug}", task_type="refactor", **extra)
            store.set_session_row(conn, row["id"], rows[slug])
            store.cas_state(conn, row["id"], "asleep", "awake")
            agents[slug] = store.get_agent(conn, row["id"])

        agent("boss", "project", project_id=16)
        agent("fixer", "task", agents["boss"]["id"])
        agent("builder", "feature", agents["boss"]["id"])
        agent("kid", "task", agents["builder"]["id"])
    infos = [SimpleNamespace(session=SimpleNamespace(id=f"ses_{s}"), tmux_session=f"cloude_{s}", session_row_id=rows[s]) for s in rows]

    async def list_infos():
        return infos

    async def send_input(data, session_id):
        keys.append(f"{session_id}:{data!r}")

    state = SimpleNamespace(session_manager=SimpleNamespace(list_session_infos=list_infos, send_input=send_input))
    view = SimpleNamespace(list_session_infos=list_infos, app=SimpleNamespace(state=state), fresh=lambda: view)
    _STATE[0] = state
    yield SimpleNamespace(huddle=huddle, port=port, told=told, woke=woke, torn=torn_down, keys=keys, agents=agents, rows=rows, view=view, state=state, tmp=tmp_path,
                          repo=repo)
    card_port.register(None)
    thread_port.register(None)


def caller(slug: str) -> AgentCaller:
    return AgentCaller(session_id=f"ses_{slug}", tmux_name=f"cloude_{slug}", current_session_id=f"ses_{slug}")


def call(w, slug: str, name: str, **args: Any) -> Dict[str, Any]:
    import json

    args.setdefault("detail", True)

    handler = tools._TOOLS[name][3]
    out = asyncio.run(handler(w.view, caller(slug), args))
    return json.loads(out["content"][0]["text"])


def refused(w, slug: str, name: str, **args: Any) -> str:
    with pytest.raises(ToolError) as exc:
        call(w, slug, name, **args)
    return str(exc.value)


def owner(op, card_id: Optional[int], **args: Any) -> Any:
    return asyncio.run(op(_STATE[0], card_id, args, by="owner"))


def sql_rows(w, query: str, *args: Any) -> List[Any]:
    conn = w.huddle._connect(False)
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def approved_rows(w) -> List[Any]:
    return sql_rows(w, f"SELECT id, state FROM work_items WHERE state IN ({', '.join('?' for _ in APPROVED)})", *APPROVED)


def dealt_to(w, slug: str, title: str = "work", reason: str = "", **extra: Any) -> int:
    card = call(w, "boss", "swarm_card_create", summary="a plain line", title=title, project_id=16, **extra)["card"]
    asyncio.run(ops.set_column(w.state, card["id"], {"column": "in_progress"}, by="owner"))
    call(w, "boss", "swarm_card_deal", card_id=card["id"], agent_id=w.agents[slug]["id"], **({"reason": reason} if reason else {}))
    call(w, slug, "swarm_card_start", card_id=card["id"])
    return card["id"]


def col(w, card_id: int) -> str:
    return asyncio.run(card_port.get().card(card_id))["column"]


def test_finish_needs_how_to_validate_and_ties_the_report_to_the_card(world):
    w, fixer = world, world.agents["fixer"]
    cid = dealt_to(w, "fixer")
    assert col(w, cid) == "in_progress"
    assert any(t["agent"] == fixer["id"] and "were dealt card" in t["text"] for t in w.told)
    call(w, "fixer", "swarm_card_handoff", card_id=cid, handoff="half done", progress=40)
    assert "no_how_to_validate" in refused(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="done", how_to_validate="   ")
    assert col(w, cid) == "in_progress" and not asyncio.run(_pending(w, fixer))
    assert "not_allowed" in refused(w, "builder", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="x", how_to_validate="y")
    done = call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="all fixed", how_to_validate="run the suite", validate_link="http://x/y")["card"]
    assert done["column"] == "review" and done["state"] == "review" and done["holder"] is None and done["last_holder"] == fixer["id"]
    assert done["how_to_validate"] == "run the suite" and done["report_id"]
    tied = asyncio.run(card_port.get().card_for_report(done["report_id"]))
    assert tied["id"] == cid
    assert [r["agent_id"] for r in asyncio.run(_pending(w, fixer))] == [fixer["id"]]
    assert asyncio.run(card_port.get().card_for_report(99999)) is None


async def _pending(w, agent) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: store.list_reports(c, agent_id=agent["id"]))


def test_a_reporter_holding_no_card_reports_as_today_and_a_holder_reports_through_the_card(world):
    w = world
    out = call(w, "builder", "swarm_report", summary="no card here")
    assert out["state"] == "pending" and asyncio.run(card_port.get().card_for_report(out["report_id"])) is None
    cid = dealt_to(w, "fixer", "held work")
    assert "how to validate" in refused(w, "fixer", "swarm_report", summary="done").lower()
    via = call(w, "fixer", "swarm_report", summary="done", how_to_validate="open it")
    assert via["card_id"] == cid and via["state"] == "pending" and col(w, cid) == "review"
    assert asyncio.run(card_port.get().card_for_report(via["report_id"]))["id"] == cid


async def owner_approves(manager: Any, caller: AgentCaller, target_id: str, target_tmux: str, action: str, summary: str, args: dict,
                         run: Any, *rest: Any, **kw: Any) -> dict:
    return await run(True)


def test_no_card_tool_and_no_agent_op_reaches_an_approved_state(world, monkeypatch):
    w = world
    monkeypatch.setattr(card_capacity_tools.write_tools, "park", owner_approves)
    review = dealt_to(w, "fixer", "in review")
    call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=review, result="r", how_to_validate="v")
    waiting = call(w, "boss", "swarm_card_create", summary="a plain line", title="waiting", project_id=16)["card"]["id"]
    held = dealt_to(w, "builder", "held")
    write_tools = {n for n in CARD_TOOLS if n in tools.WRITE_TOOLS}
    assert write_tools == card_tools.WRITE_TOOLS | card_validate_tools.WRITE_TOOLS | card_capacity_tools.WRITE_TOOLS
    args = {
        "swarm_card_create": {"title": "t", "summary": "s", "project_id": 16}, "swarm_card_start": {"card_id": review},
        "swarm_card_handoff": {"card_id": review, "handoff": "h", "progress": 100},
        "swarm_card_finish": {"card_id": review, "result": "r", "how_to_validate": "v", "needs_owner": True, "owner_ask": "a"},
        "swarm_card_close": {"card_id": review, "reason": "r"},
        "swarm_card_release": {"card_id": review, "reason": "r"}, "swarm_card_reorder": {"card_id": review, "before_id": None, "reason": "r"},
        "swarm_card_deal": {"card_id": review, "agent_id": w.agents["kid"]["id"]},
        "swarm_card_verdict": {"card_id": review, "verdict": "pass", "proof": "p"},
        "swarm_card_grant": {"scope": "project:16", "slots": 5, "reason": "r"}, "swarm_card_pace": {"project_id": 16, "pace": "normal"},
        "swarm_card_auto_promote": {"card_id": review, "on": True, "reason": "r"},
        "swarm_card_queue": {"card_id": review, "reason": "r"},
        "swarm_card_archive": {"card_id": review, "reason": "r"}, "swarm_card_delete": {"card_id": review, "reason": "r"},
    }
    assert set(args) == write_tools, "a new card write tool needs a case here"
    for slug in w.agents:
        for name, a in args.items():
            if name in ("swarm_card_close", "swarm_card_archive", "swarm_card_delete") and slug == "boss":
                continue
            for target in (review, waiting, held):
                try:
                    call(w, slug, name, **({**a, "card_id": target} if "card_id" in a else a))
                except ToolError:
                    pass
        for op, extra in ((ops.done, {}), (ops.send_back, {"note": "n"}), (ops.pause, {"mode": "now"}), (ops.pin, {"place": True}),
                          (ops.move, {"before_id": None}), (ops.set_column, {"column": "done"}), (ops.archive, {"on": True}), (ops.set_rules, {"list_key": LIST, "changes": {"auto_done": True}})):
            with pytest.raises(CardRefused) as exc:
                asyncio.run(op(w.state, review if op is not ops.set_rules else None, extra, by=f"agent:{w.agents[slug]['id']}"))
            assert exc.value.code == "not_allowed"
    assert not approved_rows(w)
    assert col(w, review) == "review"
    fresh = call(w, "boss", "swarm_card_create", summary="a plain line", title="fresh", project_id=16)["card"]["id"]
    with pytest.raises(CardRefused) as exc:
        owner(ops.done, fresh)
    assert exc.value.code == "not_in_review"
    owner(ops.done, review)
    assert [r["id"] for r in approved_rows(w)] == [review]


def test_last_child_accepted_rolls_the_parent_into_review_and_the_owner_done_cascades(world):
    w = world
    parent = dealt_to(w, "builder", "the parent")
    child = call(w, "builder", "swarm_card_create", summary="a plain line", title="the child", parent=parent)["card"]
    assert child["parent"] == parent and child["origin"]["kind"] == "agent"
    call(w, "boss", "swarm_card_deal", card_id=child["id"], agent_id=w.agents["kid"]["id"])
    call(w, "kid", "swarm_card_start", card_id=child["id"])
    fin = call(w, "kid", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=child["id"], result="child done", how_to_validate="check the child")["card"]
    assert fin["column"] == "review" and col(w, parent) == "in_progress"
    builder_view = w.view
    out = asyncio.run(reports.accept(builder_view, caller("builder"), {"report_id": fin["report_id"], "decision": "accept"}))
    assert out["decision"] == "accept"
    kid_card = asyncio.run(card_port.get().card(child["id"]))
    assert kid_card["column"] == "done" and kid_card["accepted_at"] and kid_card["state"] == "review"
    rolled = asyncio.run(card_port.get().card(parent))
    assert rolled["column"] == "review" and "1 of 1 done" in rolled["how_to_validate"] and "check the child" in rolled["how_to_validate"]
    assert not approved_rows(w)
    owner(ops.done, parent)
    assert asyncio.run(card_port.get().card(parent))["state"] == "done"
    assert asyncio.run(card_port.get().card(child["id"]))["state"] == "done"


def test_accepting_a_top_level_card_report_tears_the_agent_down_and_leaves_the_card_for_the_owner(world):
    w, fixer = world, world.agents["fixer"]
    cid = dealt_to(w, "fixer", "top level")
    fin = call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="done", how_to_validate="look")["card"]
    out = asyncio.run(reports.accept(w.view, caller("boss"), {"report_id": fin["report_id"], "decision": "accept"}))
    assert out["outcome"] == "torn_down" and w.torn == [fixer["id"]]
    assert col(w, cid) == "review" and not approved_rows(w)


def test_accepting_after_the_owner_already_made_the_child_done_still_tears_down(world):
    w, kid = world, world.agents["kid"]
    parent = dealt_to(w, "builder", "the parent")
    child = call(w, "builder", "swarm_card_create", summary="a plain line", title="the child", parent=parent)["card"]["id"]
    call(w, "boss", "swarm_card_deal", card_id=child, agent_id=kid["id"])
    call(w, "kid", "swarm_card_start", card_id=child)
    fin = call(w, "kid", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=child, result="r", how_to_validate="v")["card"]
    owner(ops.done, child)
    assert asyncio.run(card_port.get().card(child))["state"] == "done"
    out = asyncio.run(reports.accept(w.view, caller("builder"), {"report_id": fin["report_id"], "decision": "accept"}))
    assert out["outcome"] == "torn_down" and w.torn == [kid["id"]]


def test_send_back_refuses_a_card_that_is_not_in_review(world):
    w = world
    todo = call(w, "boss", "swarm_card_create", summary="a plain line", title="waiting", project_id=16)["card"]["id"]
    held = dealt_to(w, "fixer", "held")
    for cid in (todo, held):
        with pytest.raises(CardRefused) as exc:
            owner(ops.send_back, cid, note="a note")
        assert exc.value.code == "not_in_review"
    assert not asyncio.run(body.run_db(lambda c: c.execute("SELECT id FROM swarm_facts").fetchall()))
    app = FastAPI()
    app.state = w.state
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(swarm_card_routes.router, prefix="/api/v1")
    assert TestClient(app).post(f"/api/v1/swarm/cards/{todo}/send-back", json={"note": "a note"}).status_code == 409


def test_a_dealer_deals_only_inside_its_own_hierarchy(world):
    w = world
    stray = asyncio.run(body.run_db(lambda c: store.create_agent(c, slug="stray", rank="task", job="j", display_name="Stray", repo_dir=str(w.repo),
                                                                  effort="high", parent_id=None, goal="g", task_type="refactor")))
    card = call(w, "boss", "swarm_card_create", summary="a plain line", title="x", project_id=16)["card"]["id"]
    asyncio.run(ops.set_column(w.state, card, {"column": "in_progress"}, by="owner"))
    assert "not_allowed" in refused(w, "boss", "swarm_card_deal", card_id=card, agent_id=stray["id"])
    assert call(w, "boss", "swarm_card_deal", card_id=card, agent_id=w.agents["kid"]["id"])["card"]["holder"]["agent_id"] == w.agents["kid"]["id"]


def test_an_orphaned_holder_finishes_into_review_without_a_report(world):
    w = world
    cid = dealt_to(w, "kid", "orphan work")
    asyncio.run(body.run_db(lambda c: store.tear_down(c, w.agents["builder"]["id"])))
    done = call(w, "kid", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v")["card"]
    assert done["column"] == "review" and not done["report_id"]


def test_auto_done_is_passed_only_by_effects_and_never_for_a_child(world):
    w = world
    solo = dealt_to(w, "fixer", "solo")
    owner(ops.set_rules, None, list_key=LIST, changes={"auto_done": True})
    call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=solo, result="r", how_to_validate="v")
    assert asyncio.run(card_port.get().card(solo))["state"] == "done" and col(w, solo) == "done"
    assert any("auto-done" in t[1] for t in w.port.traffic)
    parent = dealt_to(w, "builder", "p")
    child = call(w, "builder", "swarm_card_create", summary="a plain line", title="c", parent=parent)["card"]["id"]
    call(w, "boss", "swarm_card_deal", card_id=child, agent_id=w.agents["kid"]["id"])
    call(w, "kid", "swarm_card_start", card_id=child)
    call(w, "kid", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=child, result="r", how_to_validate="v")
    assert col(w, child) == "review"


def test_send_back_is_one_post_that_reholds_the_last_holder_and_becomes_a_fact(world):
    w, fixer = world, world.agents["fixer"]
    cid = dealt_to(w, "fixer", "fix login")
    call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="r", how_to_validate="v")
    before = len(sql_rows(w, "SELECT id FROM work_messages WHERE item_id = ? AND author_key != 'status'", cid))
    back = owner(ops.send_back, cid, note="use the new session api, not the old one")
    assert back["column"] == "in_progress" and back["holder"]["agent_id"] == fixer["id"] and back["state"] == "open"
    posts = sql_rows(w, "SELECT id, author_key FROM work_messages WHERE item_id = ? AND author_key != 'status'", cid)
    assert len(posts) == before + 1 and posts[-1]["author_key"] == "owner"
    events = [(r["kind"], r["by"]) for r in sql_rows(w, "SELECT kind, by FROM work_card_events WHERE item_id = ? ORDER BY id", cid)]
    assert events.count(("sent_back", "owner")) == 1 and events[-1] == ("sent_back", "owner")
    assert any(t["agent"] == fixer["id"] and "was sent back" in t["text"] and t["authority"] == "data" for t in w.told)
    assert w.port.owner[-1] == (fixer["thread_key"], "use the new session api, not the old one")
    facts = asyncio.run(body.run_db(lambda c: c.execute("SELECT origin, owner_message_ref, scope, title, kind FROM swarm_facts").fetchall()))
    assert len(facts) == 1 and facts[0]["origin"] == "owner" and facts[0]["scope"] == "project" and facts[0]["title"] == "send-back on fix login"
    assert facts[0]["kind"] == "note"
    assert facts[0]["owner_message_ref"] == f"huddle:msg:{posts[-1]['id']}"
    assert not any(t[2] == f"card:learned:{cid}" for t in w.port.traffic)
    other = dealt_to(w, "fixer", "second")
    call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=other, result="r", how_to_validate="v")
    asyncio.run(body.run_db(lambda c: store.tear_down(c, fixer["id"])))
    waiting = owner(ops.send_back, other, note="again")
    assert waiting["column"] == "in_progress" and waiting["queued"] and waiting["holder"] is None


def test_pause_cascades_swap_hands_over_and_pins_hold(world):
    w, fixer, builder = world, world.agents["fixer"], world.agents["builder"]
    parent = dealt_to(w, "fixer", "parent")
    child = call(w, "fixer", "swarm_card_create", summary="a plain line", title="child", parent=parent)["card"]["id"]
    call(w, "boss", "swarm_card_deal", card_id=child, agent_id=builder["id"])
    call(w, "builder", "swarm_card_start", card_id=child)
    paused = owner(ops.pause, parent, mode="now")
    assert paused["cascaded"] == [child] and set(paused["agents"]) == {fixer["id"], builder["id"]}
    assert len([k for k in w.keys if "\\x1b" in k]) == 2 and paused["card"]["paused"]["mode"] == "now"
    assert any("Stop now" in t["text"] for t in w.told)
    resumed = owner(ops.resume, parent)
    assert resumed["card"]["paused"] is None and any("Resume card" in t["text"] for t in w.told)
    swapped = call(w, "boss", "swarm_card_deal", card_id=parent, agent_id=builder["id"])["card"]
    assert swapped["dealt_to"] == builder["id"] and swapped["mark"]["name"] == "handing_off"
    assert any("moves to Builder" in t["text"] for t in w.told)
    handed = call(w, "fixer", "swarm_card_release", card_id=parent, reason="swapped")["card"]
    assert handed["holder"]["agent_id"] == builder["id"] and handed["last_holder"] == fixer["id"]
    waiting = call(w, "boss", "swarm_card_create", summary="a plain line", title="pinned", project_id=16)["card"]["id"]
    owner(ops.pin, waiting, agent_id=fixer["id"], place=True)
    assert "pinned_elsewhere" in refused(w, "boss", "swarm_card_deal", card_id=waiting, agent_id=builder["id"])
    top = call(w, "boss", "swarm_card_create", summary="a plain line", title="behind", project_id=16)["card"]["id"]
    owner(ops.set_rules, None, list_key=LIST, changes={"reorder": "auto"})
    assert "pinned" in refused(w, "boss", "swarm_card_reorder", card_id=top, before_id=waiting, reason="urgent")


def test_reorder_suggests_unless_auto_and_the_owner_settles_it(world):
    w = world
    first = call(w, "boss", "swarm_card_create", summary="a plain line", title="first", project_id=16)["card"]["id"]
    second = call(w, "boss", "swarm_card_create", summary="a plain line", title="second", project_id=16)["card"]["id"]
    call(w, "boss", "swarm_card_reorder", card_id=second, before_id=first, reason="blocks the rest")
    assert asyncio.run(card_port.get().card(second))["queue_index"] == 2
    row = sql_rows(w, "SELECT id, state FROM work_card_suggestions")[0]
    assert any("suggests moving" in t[1] and "blocks the rest" in t[1] for t in w.port.traffic)
    settled = owner(ops.settle_suggestion, None, suggestion_id=row["id"], action="apply")
    assert settled["suggestion"]["state"] == "applied" and asyncio.run(card_port.get().card(second))["queue_index"] == 1
    with pytest.raises(CardRefused) as exc:
        owner(ops.settle_suggestion, None, suggestion_id=row["id"], action="dismiss")
    assert exc.value.code == "stale"


def test_who_may_create_and_deal(world):
    w = world
    assert "child cards of the card it holds" in refused(w, "fixer", "swarm_card_create", summary="a plain line", title="loose", project_id=16)
    assert "not_allowed" in refused(w, "fixer", "swarm_card_deal", card_id=call(w, "boss", "swarm_card_create", summary="a plain line", title="x", project_id=16)["card"]["id"],
                                    agent_id=w.agents["kid"]["id"])
    assert "not_a_swarm_agent" in _ghost(w)
    spawned = asyncio.run(ops.mint_for_spawn(w.state, w.agents["boss"], w.agents["kid"], title="spawned work", text="the goal"))
    assert spawned["origin"] == {"kind": "spawn", "ref": str(w.agents["boss"]["id"])} and spawned["holder"]["agent_id"] == w.agents["kid"]["id"]
    assert not [t for t in w.told if t["agent"] == w.agents["kid"]["id"] and "were dealt card" in t["text"]]


def test_a_long_goal_with_control_characters_still_mints_a_card_for_the_child(world):
    w = world
    goal = ("line one\r\nline two\x07 " * 200)[:3000]
    assert len(goal) == 3000 and "\r" in goal
    spawned = asyncio.run(ops.mint_for_spawn(w.state, w.agents["boss"], w.agents["kid"], title="spawned\x00 work", text=goal))
    assert spawned["holder"]["agent_id"] == w.agents["kid"]["id"] and "\r" not in spawned["text"]
    assert 0 < len(spawned["text"]) <= ops.MAX_CARD_TEXT == rules.MAX_TEXT


def test_a_company_or_alpha_child_card_names_a_project_not_its_own_list():
    parent = {"holder": {"agent_id": 1}, "list_key": "agent:9"}
    for rank in ("company", "alpha"):
        agent = {"id": 9, "rank": rank, "thread_key": "agent:9", "company_id": 3}
        assert "name the project" in permits.can_create(agent, "agent:9", parent, company_id=None)
        assert "name the project" in permits.can_create(agent, "all", parent, company_id=None)
    assert permits.can_create({"id": 9, "rank": "alpha", "thread_key": "agent:9"}, "16", parent) is None


def test_rejecting_a_report_whose_card_the_owner_already_closed_still_rejects(world):
    w = world
    cid = dealt_to(w, "fixer", "closed early")
    fin = call(w, "fixer", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=cid, result="done", how_to_validate="look")["card"]
    owner(ops.done, cid)
    out = asyncio.run(reports.accept(w.view, caller("boss"), {"report_id": fin["report_id"], "decision": "reject", "note": "no"}))
    assert out["outcome"] == "rejected" and not asyncio.run(_pending(w, w.agents["fixer"]))
    assert asyncio.run(body.run_db(lambda c: store.get_report(c, fin["report_id"])))["state"] == "rejected"


def _spawn_world(w, monkeypatch):
    sent: List[Dict[str, Any]] = []
    slept: List[int] = []
    made: List[Dict[str, Any]] = []

    async def make(req):
        row = await body.run_db(lambda c: store.create_agent(c, slug=f"spawned{len(made)}", rank=req["rank"], job=req["job"], display_name="Spawned",
                                                             repo_dir=str(w.repo), effort="high", parent_id=req["parent_id"], goal=req["goal"],
                                                             task_type=req["task_type"]))
        made.append(row)
        return row

    async def identities(view, caller_, to):
        return {"key": "k-b", "epoch": 1}, {"key": "k-c", "epoch": 1, "id": to}

    async def send(view, caller_, **kw):
        sent.append(kw)
        return {"id": "m1"}

    async def sleep(app_state, agent_id, reason):
        slept.append(agent_id)

    monkeypatch.setattr(create, "create_agent", make)
    monkeypatch.setattr(body, "sleep", sleep)
    monkeypatch.setattr(bus, "identities", identities)
    monkeypatch.setattr(bus, "send", send)
    monkeypatch.setattr(crosstalk_store, "grant_contact", lambda *a, **kw: None)
    return sent, slept, made


def _spawn(w, **extra: Any) -> "spawn.SpawnPlan":
    args = {"job": "spawned job", "goal": "the spawned goal", "task_type": "refactor", "rank": "task", **extra}
    return asyncio.run(spawn.prepare(w.view, caller("boss"), args))


def _retired(made: List[Dict[str, Any]]) -> bool:
    return asyncio.run(body.run_db(lambda c: store.get_agent(c, made[-1]["id"])))["torn_down_at"] is not None


def test_spawn_deals_a_named_card_into_the_first_message_and_a_lost_card_retires_the_child(world, monkeypatch):
    w = world
    sent, slept, made = _spawn_world(w, monkeypatch)
    card = call(w, "boss", "swarm_card_create", summary="a plain line", title="named work", project_id=16)["card"]["id"]
    plan = _spawn(w, card=card)
    out = asyncio.run(spawn.run(w.view, caller("boss"), plan))
    assert f"Your card is #{card}: named work" in sent[0]["text"] and sent[0]["text"].startswith(plan.first_message)
    assert asyncio.run(card_port.get().card(card))["holder"]["agent_id"] == out["agent_id"] and not slept
    taken = call(w, "boss", "swarm_card_create", summary="a plain line", title="taken in between", project_id=16)["card"]["id"]
    plan = _spawn(w, card=taken)
    asyncio.run(ops.set_column(w.state, taken, {"column": "in_progress"}, by="owner"))
    call(w, "boss", "swarm_card_deal", card_id=taken, agent_id=w.agents["fixer"]["id"])
    call(w, "fixer", "swarm_card_start", card_id=taken)
    sent.clear()
    with pytest.raises(spawn.SpawnRefused, match="could not be dealt"):
        asyncio.run(spawn.run(w.view, caller("boss"), plan))
    assert _retired(made) and slept == [made[-1]["id"]] and not sent


def test_spawn_refuses_a_card_the_parent_may_not_deal_before_anything_is_created(world, monkeypatch):
    w = world
    _, _, made = _spawn_world(w, monkeypatch)
    held = dealt_to(w, "fixer", "already held")
    for bad in (held, 99999, 0, "3"):
        with pytest.raises(spawn.SpawnRefused):
            _spawn(w, card=bad)
    assert not made


def test_spawn_with_a_card_store_that_cannot_open_retires_the_child_and_refuses(world, monkeypatch):
    w = world
    sent, slept, made = _spawn_world(w, monkeypatch)

    async def broken(*a, **kw):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(ops, "mint_for_spawn", broken)
    plan = _spawn(w)
    with pytest.raises(spawn.SpawnRefused, match="could not be dealt"):
        asyncio.run(spawn.run(w.view, caller("boss"), plan))
    assert _retired(made) and slept == [made[-1]["id"]] and not sent


def test_an_agent_cannot_create_a_card_above_one_the_owner_pinned_in_place(world):
    w = world
    pinned = call(w, "boss", "swarm_card_create", summary="a plain line", title="pinned place", project_id=16)["card"]["id"]
    owner(ops.pin, pinned, place=True)
    before = len(asyncio.run(card_port.get().cards()))
    assert "pinned" in refused(w, "boss", "swarm_card_create", summary="a plain line", title="cuts in", project_id=16, before_id=pinned)
    assert len(asyncio.run(card_port.get().cards())) == before
    assert call(w, "boss", "swarm_card_create", summary="a plain line", title="goes last", project_id=16)["card"]["id"]


def test_an_accepted_child_cannot_be_sent_back_even_when_the_owner_read_it_before_the_accept(world):
    w = world
    parent = dealt_to(w, "builder", "the parent")
    child = call(w, "builder", "swarm_card_create", summary="a plain line", title="the child", parent=parent)["card"]["id"]
    call(w, "boss", "swarm_card_deal", card_id=child, agent_id=w.agents["kid"]["id"])
    call(w, "kid", "swarm_card_start", card_id=child)
    fin = call(w, "kid", "swarm_card_finish", needs_owner=True, owner_ask="check it", card_id=child, result="r", how_to_validate="v")["card"]
    asyncio.run(reports.accept(w.view, caller("builder"), {"report_id": fin["report_id"], "decision": "accept"}))
    with pytest.raises(CardRefused) as exc:
        asyncio.run(card_port.get().act("send_back", child, {"note": "late", "rehold": None}, "owner"))
    assert exc.value.code == "not_in_review" and col(w, child) == "done"


def test_swarm_report_falls_back_when_the_card_store_cannot_open(world, monkeypatch):
    from src.core.mcp import swarm_tools

    async def broken(agent_id):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(ops, "held_cards", broken)
    assert asyncio.run(swarm_tools._held_cards(world.view, caller("fixer"))) == []


def _ghost(w) -> str:
    ghost = AgentCaller(session_id="ses_none", tmux_name="cloude_none", current_session_id="ses_none")
    with pytest.raises(ToolError) as exc:
        asyncio.run(tools._TOOLS["swarm_card_get"][3](w.view, ghost, {"card_id": 1}))
    return str(exc.value)


def test_routes_are_owner_moves_with_codes(world):
    w = world
    app = FastAPI()
    app.state = w.state
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(swarm_card_routes.router, prefix="/api/v1")
    api = TestClient(app)
    made = api.post("/api/v1/swarm/cards/", json={"project_id": 16, "title": "from the owner", "summary": "a plain line"})
    assert made.status_code == 201 and made.json()["origin"] == {"kind": "owner", "ref": ""}
    cid = made.json()["id"]
    assert api.post("/api/v1/swarm/cards/", json={"project_id": 16, "title": ""}).status_code == 422
    assert api.post("/api/v1/swarm/cards/", json={"project_id": 16, "title": "x", "surprise": 1}).status_code == 422
    assert api.post(f"/api/v1/swarm/cards/{cid}/done", json={}).status_code == 409
    assert api.post("/api/v1/swarm/cards/9999/done", json={}).status_code == 404
    assert api.put("/api/v1/swarm/cards/rules/16", json={"reorder": "sometimes"}).status_code == 422
    assert api.put("/api/v1/swarm/cards/rules/16", json={"auto_done": True}).json()["auto_done"] is True
    assert api.get("/api/v1/swarm/cards/rules/16").json()["auto_done"] is True
    deal = api.post(f"/api/v1/swarm/cards/{cid}/swap", json={"agent_id": w.agents["fixer"]["id"]})
    assert deal.status_code == 409 and deal.json()["detail"]["code"] == "not_held"
    paused = api.post(f"/api/v1/swarm/cards/{cid}/pause", json={"mode": "after_step"})
    assert paused.status_code == 200 and paused.json()["card"]["paused"]["mode"] == "after_step"
    assert api.post(f"/api/v1/swarm/cards/{cid}/resume").json()["card"]["paused"] is None
    assert api.post(f"/api/v1/swarm/cards/{cid}/move", json={"before_id": None, "pin_place": True}).json()["pin"]["place"] is True
    assert api.get(f"/api/v1/swarm/cards/{cid}").json()["id"] == cid
    held = dealt_to(w, "fixer", "owner takes it back")
    assert api.post(f"/api/v1/swarm/cards/{held}/release", json={"reason": "enough"}).json()["holder"] is None
    assert any("took card #" in t["text"] and "went quiet" not in t["text"] for t in w.told)


def test_guard_admits_every_card_tool_in_a_data_turn_but_grant_pace_and_delete():
    assert OWNER_ONLY_CARD_TOOLS == {"swarm_card_grant", "swarm_card_pace", "swarm_card_delete"}
    assert CARD_TOOLS - OWNER_ONLY_CARD_TOOLS <= guard.DATA_SAFE
    assert not OWNER_ONLY_CARD_TOOLS & guard.DATA_SAFE
    assert deliver.SOURCE == "huddle_tell"
