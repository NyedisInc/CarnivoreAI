
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from src.api import one_shot_routes
from src.cplugs.host import runtime
from src.cplugs.huddle import held, inbox, inbox_delivery, schedule, send_queue, service
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import Env
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"
CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


@pytest.fixture
def env(app, monkeypatch):
    rig = Env(app, monkeypatch)
    rig.inbox = InboxStore(rig.store)
    monkeypatch.setattr(send_queue, "_arm", lambda ctx: None)
    yield rig
    send_queue.reset()
    held.reset()
    schedule.stop()


def queue(client, text="backlog dark mode and now fix the login bug", key="12", waits: bool = False) -> dict:
    answer = client.post(f"{BASE}/lists/{key}/inbox", json={"text": text}).json()
    if not waits:
        send_queue.reset()
    return answer


def test_rung_29_is_additive_and_old_rows_follow_the_default(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:28]:
            conn.executescript(step)
        conn.execute("INSERT INTO list_prefs (list_key, nudge, updated_at) VALUES ('12', 1, 1)")
        conn.execute("PRAGMA user_version = 28")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    assert InboxStore(store).prefs() == {"12": True}
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert "inbox_id" in [r[1] for r in conn.execute("PRAGMA table_info(items)")]
        assert [r[1] for r in conn.execute("PRAGMA table_info(inbox)")][:3] == ["id", "list_key", "raw_text"]


def test_the_box_queues_the_raw_text_and_makes_no_item(client, env):
    answer = queue(client, "  backlog x\nand y  ")
    assert answer["queued"] is True and answer["item"] is None
    assert answer["entry"]["text"] == "backlog x\nand y" and answer["entry"]["status"] == "queued"
    body = client.get(f"{BASE}/lists/12").json()
    assert body["items"] == [] and [(p["id"], p["status"]) for p in body["inbox"]] == [(answer["entry"]["id"], "queued")]
    groups = client.get(f"{BASE}/aggregate").json()["groups"]
    assert [g["list"] for g in groups] == ["12"] and groups[0]["inbox"][0]["text"] == "backlog x\nand y"
    assert client.post(f"{BASE}/lists/12/inbox", json={"text": "   "}).status_code == 400


def test_the_shared_list_and_a_switched_off_project_add_at_once(client, env):
    shared = queue(client, "shared thing", key="all")
    assert shared["queued"] is False and shared["item"]["text"] == "shared thing" and shared["entry"] is None
    assert client.get(f"{BASE}/lists/12/inbox-prefs").json() == {"list": "12", "file_through_session": True}
    assert client.put(f"{BASE}/lists/12/inbox-prefs", json={"file_through_session": False}).json()["file_through_session"] is False
    off = queue(client, "plain add")
    assert off["queued"] is False and off["item"]["text"] == "plain add" and "from_inbox" not in off["item"]
    assert client.get(f"{BASE}/lists/12").json().get("inbox") is None
    lists = {l["key"]: l["inbox_via_session"] for l in client.get(f"{BASE}/lists").json()["lists"]}
    assert lists["12"] is False and lists["all"] is False
    assert client.put(f"{BASE}/lists/all/inbox-prefs", json={"file_through_session": True}).status_code == 400
    client.put(f"{BASE}/lists/12/inbox-prefs", json={"file_through_session": True})
    assert queue(client)["queued"] is True


def test_the_most_recently_active_session_is_told_once_with_the_entry_id(client, env):
    env.set_rows([row("ses_old", 12, minutes_ago=30), row("ses_new", 12, minutes_ago=1), row("ses_other", 99, minutes_ago=0)])
    entry = queue(client)["entry"]
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx)) == 1
    target, text = env.pasted[0]
    assert target == "ses_new"
    assert f"file entry {entry['id']} with task_manager_entry_import" in text and "backlog dark mode" in text
    stored = env.inbox.get(entry["id"])
    assert (stored["status"], stored["delivered_to"]) == ("filing", "ses_new")
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx)) == 0 and len(env.pasted) == 1


def test_a_busy_session_leaves_it_queued_and_nothing_is_held(client, env, monkeypatch):
    async def busy(request, session_id, text):
        raise HTTPException(status_code=409, detail={"code": "session_busy", "detail": "working"})

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", busy)
    entry = queue(client)["entry"]
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx)) == 0
    assert env.inbox.get(entry["id"])["status"] == "queued" and not held.is_held("12")


def test_no_session_waits_then_the_entry_stays_queued_as_a_question_and_the_raw_text_is_kept(client, env):
    env.set_rows([])
    entry = queue(client, "two things: a and b")["entry"]
    start = time.time()
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx, lambda: start)) == 0
    assert env.inbox.get(entry["id"])["status"] == "queued"
    late = start + inbox.DEFAULT_FALLBACK_S + 1
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx, lambda: late)) == 1
    stuck = env.inbox.get(entry["id"])
    assert stuck["status"] == "stuck" and stuck["item_ids"] == [] and len(env.inbox.carriers(entry["id"])) == 1
    assert client.get(f"{BASE}/inbox/{entry['id']}").json()["text"] == "two things: a and b"


def test_a_told_session_that_never_files_becomes_a_question_too(client, env):
    entry = queue(client)["entry"]
    asyncio.run(inbox_delivery.deliver_pass(env.ctx))
    assert env.inbox.get(entry["id"])["status"] == "filing"
    late = time.time() + inbox.DEFAULT_FALLBACK_S + 5
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx, lambda: late)) == 1
    assert env.inbox.get(entry["id"])["status"] == "stuck"


def test_the_scheduler_is_armed_only_while_an_entry_is_open(client, env):
    scheduler = schedule.Scheduler(env.ctx)
    assert scheduler._timeout() is None
    queue(client)
    assert scheduler._timeout() == pytest.approx(inbox.POLL_S, abs=0.5)


def test_the_owner_route_files_several_items_and_links_each(client, env):
    entry = queue(client)["entry"]
    items = [{"title": "Dark mode", "text": "add dark mode", "state": "todo", "group": "ui"}, {"title": "Login bug", "text": "fix the login bug"}]
    filed = client.post(f"{BASE}/inbox/{entry['id']}/file", json={"items": items}).json()
    assert [i["state"] for i in filed["items"]] == ["todo", "open"] and [i["title"] for i in filed["items"]] == ["Dark mode", "Login bug"]
    assert all(i["from_inbox"]["text"] == entry["text"] for i in filed["items"])
    assert filed["entry"]["status"] == "filed" and filed["entry"]["item_ids"] == [i["id"] for i in filed["items"]]
    assert client.post(f"{BASE}/inbox/{entry['id']}/file", json={"items": items}).status_code == 400
    again = queue(client)["entry"]
    assert client.post(f"{BASE}/inbox/{again['id']}/file", json={"items": [{"title": "t", "text": "x", "state": "working"}]}).status_code == 400
    assert env.inbox.get(again["id"])["status"] == "queued"


def test_a_filed_item_is_direct_and_an_item_merely_carrying_the_link_is_not(client, env):
    entry = queue(client)["entry"]
    filed = client.post(f"{BASE}/inbox/{entry['id']}/file", json={"items": [{"title": "Login bug", "text": "fix the login bug"}]}).json()
    assert filed["items"][0]["from_inbox"]["direct"] is True
    carried = env.store.add("12", "a task claude made while working on it", actor="claude")["id"]
    with closing(env.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET inbox_id = ? WHERE id = ?", (entry["id"], carried))
    assert env.store.item(carried)["from_inbox"] == {"id": entry["id"], "text": entry["text"], "direct": False}



@pytest.fixture
def manager(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    own = SimpleNamespace(session=SimpleNamespace(id="ses_1"), project_id=12, host_key="local", tmux_session="")

    async def infos():
        return [own]

    return SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)


def call(manager, name, args):
    result = asyncio.run(tools.call_tool(manager, CALLER, name, args))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def tool_store(manager) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(manager.app).storage("huddle"), notify=lambda key: None)


def test_the_tools_exist_and_the_list_shows_only_pending_entries(manager):
    names = {d["name"] for d in tools.tool_definitions()}
    assert {"task_manager_entries_list", "task_manager_entry_import"} <= names
    read_only = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    assert "task_manager_entries_list" in read_only and "task_manager_entry_import" not in read_only
    inboxes = InboxStore(tool_store(manager))
    first, second = inboxes.add("12", "one"), inboxes.add("12", "two")
    inboxes.claim(first["id"], inbox.FILED, 1.0)
    ok, listed = call(manager, "task_manager_entries_list", {"list": "mine"})
    assert ok and [e["id"] for e in listed["entries"]] == [second["id"]] and listed["entries"][0]["text"] == "two"


def test_a_session_splits_one_entry_into_items_and_obeys_the_directions(manager):
    store = tool_store(manager)
    entry = InboxStore(store).add("12", "backlog dark mode. now fix the login bug. ask me which db")
    ok, filed = call(manager, "task_manager_entry_import", {"inbox_id": entry["id"], "items": [
        {"title": "Dark mode", "text": "add dark mode", "state": "todo", "group": "ui"},
        {"title": "Login bug", "text": "fix the login bug", "state": "working"},
        {"title": "Which db", "text": "which database should this use?", "state": "question"}]})
    assert ok, filed
    assert filed["status"] == "filed" and [i["state"] for i in filed["items"]] == ["todo", "working", "question"]
    ids = [i["item_id"] for i in filed["items"]]
    items = [store.item(i) for i in ids]
    assert items[0]["state"] == "todo" and items[1]["status"] == "working" and items[2]["status"] == "question"
    assert [i["title"] for i in items] == ["Dark mode", "Login bug", "Which db"]
    assert all(i["from_inbox"] == {"id": entry["id"], "text": entry["text"], "direct": True} for i in items)
    final = InboxStore(store).get(entry["id"])
    assert final["status"] == "filed" and final["item_ids"] == ids and final["text"] == entry["text"]


def test_an_ask_item_carries_its_typed_questions(manager):
    store = tool_store(manager)
    entry = InboxStore(store).add("12", "ask me which db")
    ok, filed = call(manager, "task_manager_entry_import", {"inbox_id": entry["id"], "items": [{
        "title": "Pick the db", "text": "choose a db", "state": "question",
        "ask": {"context": "needs a decision", "questions": [{"id": "db", "type": "single", "prompt": "which?", "options": ["sqlite", "postgres"]}]}}]})
    assert ok, filed
    assert store.item(filed["items"][0]["item_id"])["status"] == "question"


def test_a_late_session_is_told_the_entry_already_fell_back(manager):
    inboxes = InboxStore(tool_store(manager))
    entry = inboxes.add("12", "x")
    inboxes.file_plain(entry["id"], time.time(), inbox.REASON_TIMEOUT)
    ok, text = call(manager, "task_manager_entry_import", {"inbox_id": entry["id"], "items": [{"title": "t", "text": "x"}]})
    assert not ok and "already fallback" in text


def test_bad_arguments_claim_nothing(manager):
    inboxes = InboxStore(tool_store(manager))
    entry = inboxes.add("12", "x")
    for bad in ({"inbox_id": entry["id"], "items": []}, {"inbox_id": entry["id"], "items": [{"title": "", "text": "x"}]},
                {"inbox_id": entry["id"], "items": [{"title": "t", "text": "x", "state": "done"}]},
                {"inbox_id": entry["id"], "items": [{"title": "t", "text": "x", "color": "red"}]}, {"items": [{"title": "t", "text": "x"}]}):
        ok, _text = call(manager, "task_manager_entry_import", bad)
        assert not ok
    assert inboxes.get(entry["id"])["status"] == "queued" and inboxes.get(entry["id"])["item_ids"] == []
    ok, text = call(manager, "task_manager_entry_import", {"inbox_id": 999, "items": [{"title": "t", "text": "x"}]})
    assert not ok and "no inbox entry" in text


def test_filing_gives_each_item_its_perceived_ask(manager):
    store = tool_store(manager)
    entry = InboxStore(store).add("12", "backlog dark mode. fix the login bug")
    ok, filed = call(manager, "task_manager_entry_import", {"inbox_id": entry["id"], "items": [
        {"title": "Dark mode", "text": "add dark mode", "state": "todo", "perceived_ask": "the owner wants a dark theme, later"},
        {"title": "Login bug", "text": "fix the login bug"}]})
    assert ok, filed
    items = [store.item(i["item_id"]) for i in filed["items"]]
    assert [i["perceived_ask"] for i in items] == ["the owner wants a dark theme, later", None]
