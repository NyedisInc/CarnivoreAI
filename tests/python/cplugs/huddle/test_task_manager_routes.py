
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cplugs.host import runtime
from src.cplugs.huddle import callers, routes as huddle_routes, rules, service
from src.cplugs.huddle.store import TaskManagerStore
from src.api import one_shot_routes
from src.api.auth import require_auth
from tests.python.cplugs.owner import turn_on

NOW = datetime(2026, 10, 2, 12, 0, 0)


def row(sid: str, project: int, agent: str = "claude", minutes_ago: int = 0):
    session = SimpleNamespace(id=sid, agent_type=agent, last_activity=NOW - timedelta(minutes=minutes_ago))
    return SimpleNamespace(session=session, agent_type=agent, agent_family=None, project_id=project, project_name="carnivore",
                           label=sid, tmux_session=f"cloude_{sid}", activity_status="idle", host_key="local")


@pytest.fixture
def app(tmp_path: Path, monkeypatch) -> FastAPI:
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore"})
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    rows = [row("ses_old", 12, minutes_ago=30), row("ses_new", 12, minutes_ago=1),
            row("ses_codex", 12, agent="codex"), row("ses_other", 99)]

    async def infos():
        return rows

    app.state.session_manager = SimpleNamespace(list_session_infos=infos)
    return app


@pytest.fixture
def client(app: FastAPI):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as test_client:
        yield test_client


def test_every_route_needs_auth(app: FastAPI):
    with TestClient(app) as anonymous:
        for method, path in [("get", "/api/v1/cplugs/huddle/lists"), ("get", "/api/v1/cplugs/huddle/lists/all"), ("get", "/api/v1/cplugs/huddle/aggregate"),
                             ("post", "/api/v1/cplugs/huddle/lists/all/items"), ("patch", "/api/v1/cplugs/huddle/items/1"),
                             ("get", "/api/v1/cplugs/huddle/changes"), ("post", "/api/v1/cplugs/huddle/lists/12/send"),
                             ("post", "/api/v1/cplugs/huddle/lists/all/remove-completed")]:
            assert getattr(anonymous, method)(path).status_code in (401, 403), path


def test_lists_offer_all_first_then_each_project(client):
    lists = client.get("/api/v1/cplugs/huddle/lists").json()["lists"]
    assert [(l["key"], l["name"]) for l in lists] == [("all", None), ("12", "carnivore")]
    assert client.post("/api/v1/cplugs/huddle/lists/77/items", json={"text": "x"}).status_code == 404
    assert client.post("/api/v1/cplugs/huddle/lists/bad/items", json={"text": "x"}).status_code == 400


def test_aggregate_groups_shared_first_then_projects_in_their_own_order(client):
    client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "shared one"})
    a = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "p1"}).json()
    b = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "p2"}).json()
    rev = client.get("/api/v1/cplugs/huddle/lists/12").json()["revision"]
    assert client.put("/api/v1/cplugs/huddle/lists/12/order", json={"ids": [b["id"], a["id"]], "expected_revision": rev}).status_code == 200
    body = client.get("/api/v1/cplugs/huddle/aggregate").json()
    assert [(g["list"], g["name"]) for g in body["groups"]] == [("all", None), ("12", "carnivore")]
    assert [i["text"] for i in body["groups"][1]["items"]] == ["p2", "p1"]
    assert body["groups"][1]["revision"] == client.get("/api/v1/cplugs/huddle/lists/12").json()["revision"]


def test_aggregate_is_empty_with_no_items(client):
    assert client.get("/api/v1/cplugs/huddle/aggregate").json()["groups"] == []


def test_joe_adds_approves_with_a_note_and_a_stale_revision_is_409(client):
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "fix this"}).json()
    assert item["created_by"] == "joe"
    done = client.patch(f"/api/v1/cplugs/huddle/items/{item['id']}",
                        json={"approved": True, "note": "read me", "expected_revision": item["revision"]})
    assert done.status_code == 200 and done.json()["state"] == "done"
    stale = client.patch(f"/api/v1/cplugs/huddle/items/{item['id']}", json={"text": "y", "expected_revision": item["revision"]})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "task_manager_stale"
    assert stale.json()["detail"]["current"]["state"] == "done"


def test_reorder_reply_delete_and_changes(client):
    a = client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "a"}).json()
    b = client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "b"}).json()
    listed = client.get("/api/v1/cplugs/huddle/lists/all").json()
    moved = client.put("/api/v1/cplugs/huddle/lists/all/order", json={"ids": [b["id"], a["id"]], "expected_revision": listed["revision"]})
    assert [i["id"] for i in moved.json()["items"]] == [b["id"], a["id"]]
    again = client.put("/api/v1/cplugs/huddle/lists/all/order", json={"ids": [a["id"], b["id"]], "expected_revision": listed["revision"]})
    assert again.status_code == 409
    cursor = moved.json()["cursor"]
    assert client.post(f"/api/v1/cplugs/huddle/items/{a['id']}/messages", json={"text": "ok"}).status_code == 200
    assert client.delete(f"/api/v1/cplugs/huddle/items/{b['id']}").status_code == 200
    changes = client.get(f"/api/v1/cplugs/huddle/changes?since={cursor}&list=all").json()
    assert {i["id"] for i in changes["items"]} == {a["id"], b["id"]}
    assert [m["text"] for m in changes["messages"]] == ["ok"]


def test_remove_completed_removes_only_checked_items_of_that_list_in_one_change(client):
    ids = [client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": t}).json()["id"] for t in ("a", "b", "c")]
    other = client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "shared"}).json()["id"]
    client.patch(f"/api/v1/cplugs/huddle/items/{ids[0]}", json={"approved": True})
    client.patch(f"/api/v1/cplugs/huddle/items/{ids[2]}", json={"approved": True, "note": "nearly"})
    client.patch(f"/api/v1/cplugs/huddle/items/{other}", json={"approved": True})
    before = client.get("/api/v1/cplugs/huddle/changes").json()["cursor"]
    body = client.post("/api/v1/cplugs/huddle/lists/12/remove-completed").json()
    assert body == {"list": "12", "removed": [ids[0], ids[2]]}
    assert [i["id"] for i in client.get("/api/v1/cplugs/huddle/lists/12").json()["items"]] == [ids[1]]
    assert [i["id"] for i in client.get("/api/v1/cplugs/huddle/lists/all").json()["items"]] == [other]
    assert client.get("/api/v1/cplugs/huddle/changes").json()["cursor"] == before + 1
    assert client.post("/api/v1/cplugs/huddle/lists/12/remove-completed").json()["removed"] == []
    assert client.post("/api/v1/cplugs/huddle/lists/bad/remove-completed").status_code == 400


@pytest.fixture
def pasted(monkeypatch):
    sent = []

    async def paste(request, session_id, text):
        sent.append((session_id, text))
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)
    return sent


def note(app, session_id, list_key, at):
    callers.note_caller(runtime.host_for(app).storage("huddle"), session_id, list_key, at)


def test_tell_with_several_sessions_and_no_huddle_caller_asks_instead_of_picking(client, pasted):
    picks = client.get("/api/v1/cplugs/huddle/lists/12/sessions").json()
    assert [s["id"] for s in picks["sessions"]] == ["ses_codex", "ses_new", "ses_old"]
    assert (picks["default"], picks["reason"]) == (None, "pick")
    refused = client.post("/api/v1/cplugs/huddle/lists/12/send", json={})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "task_manager_pick_session"
    assert pasted == []
    told = client.post("/api/v1/cplugs/huddle/lists/12/send", json={"target": "ses_old"}).json()
    assert (told["target"], told["reason"]) == ("ses_old", "chosen")
    assert "\n" not in pasted[0][1] and "task_manager_changes" in pasted[0][1] and "list 12" in pasted[0][1]
    assert client.post("/api/v1/cplugs/huddle/lists/12/send", json={"target": "ses_other"}).status_code == 404
    assert len(pasted) == 1


def test_the_last_huddle_caller_of_the_list_wins_over_the_most_active(client, app, pasted):
    note(app, "ses_old", "12", 100.0)
    note(app, "ses_codex", "all", 200.0)
    picks = client.get("/api/v1/cplugs/huddle/lists/12/sessions").json()
    assert (picks["default"], picks["reason"]) == ("ses_old", "last_task_manager_caller")
    told = client.post("/api/v1/cplugs/huddle/lists/12/send", json={}).json()
    assert (told["target"], told["reason"]) == ("ses_old", "last_task_manager_caller")
    assert pasted[0][0] == "ses_old"


def test_the_all_list_tells_the_last_huddle_caller_on_any_list(client, app, pasted):
    note(app, "ses_new", "all", 100.0)
    note(app, "ses_other", "99", 300.0)
    note(app, "ses_gone", "12", 400.0)
    picks = client.get("/api/v1/cplugs/huddle/lists/all/sessions").json()
    assert {s["id"] for s in picks["sessions"]} == {"ses_new", "ses_old", "ses_codex", "ses_other"}
    assert (picks["default"], picks["reason"]) == ("ses_other", "last_task_manager_caller")
    assert client.post("/api/v1/cplugs/huddle/lists/all/send", json={}).json()["target"] == "ses_other"


def test_the_all_list_with_no_caller_asks(client, pasted):
    picks = client.get("/api/v1/cplugs/huddle/lists/all/sessions").json()
    assert (picks["default"], picks["reason"]) == (None, "pick")
    assert client.post("/api/v1/cplugs/huddle/lists/all/send", json={}).status_code == 409


def test_a_project_with_one_live_agent_session_defaults_to_it(client, pasted, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore", "99": "other"})
    picks = client.get("/api/v1/cplugs/huddle/lists/99/sessions").json()
    assert (picks["default"], picks["reason"]) == ("ses_other", "only_session")
    assert client.post("/api/v1/cplugs/huddle/lists/99/send", json={}).json()["target"] == "ses_other"


def test_tell_from_all_projects_names_the_lists_that_changed_and_their_own_list_argument(client, app, pasted):
    store = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "in the project list"})
    first = client.post("/api/v1/cplugs/huddle/lists/all/send", json={"target": "ses_old"}).json()["text"]
    assert "the swarm list for carnivore changed" in first and "(list 12, since 0)" in first and "list all" not in first
    store.note_read("ses_old", "12", store.list_heads()["12"])
    client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "a shared item"})
    second = client.post("/api/v1/cplugs/huddle/lists/all/send", json={"target": "ses_old"}).json()["text"]
    assert "the shared swarm list changed" in second and "(list all, since 0)" in second and "list 12" not in second
    for key, head in store.list_heads().items():
        store.note_read("ses_old", key, head)
    third = client.post("/api/v1/cplugs/huddle/lists/all/send", json={"target": "ses_old"}).json()["text"]
    assert "omit list" in third and "\n" not in third


def test_the_tell_button_is_untold_until_a_tell_carries_joes_changes(client, app, pasted):
    def untold(key: str) -> bool:
        return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == key)["untold"]

    assert untold("12") is False
    first = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "new"}).json()["id"]
    assert untold("12") is True and untold("all") is False
    assert client.post("/api/v1/cplugs/huddle/lists/12/send", json={"target": "ses_old"}).status_code == 200
    assert untold("12") is False
    for change in (lambda: client.patch(f"/api/v1/cplugs/huddle/items/{first}", json={"note": "n"}),
                   lambda: client.patch(f"/api/v1/cplugs/huddle/items/{first}", json={"approved": True}),
                   lambda: client.post(f"/api/v1/cplugs/huddle/items/{first}/messages", json={"text": "r"})):
        change()
        assert untold("12") is True
        client.post("/api/v1/cplugs/huddle/lists/12/send", json={"target": "ses_old"})
        assert untold("12") is False
    client.delete(f"/api/v1/cplugs/huddle/items/{first}")
    assert untold("12") is False
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "again"})
    assert client.post("/api/v1/cplugs/huddle/lists/12/send", json={"target": "ses_other"}).status_code == 404
    assert untold("12") is True
    client.post("/api/v1/cplugs/huddle/lists/all/items", json={"text": "shared"})
    assert untold("all") is True
    assert client.post("/api/v1/cplugs/huddle/lists/all/send", json={"target": "ses_old"}).status_code == 200
    assert untold("all") is False and untold("12") is False


def _store(app) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)


def _busy_item(client, app):
    store = _store(app)
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "busy"}).json()
    for n in range(6):
        posted = store.post(item["id"], f"old note {n}", actor="claude", kind="info")
        store.mark_seen(item["id"], posted["message"]["id"])
    return item["id"], store


def test_aggregate_threads_are_slim_and_a_row_opening_reads_the_whole_thread(client, app):
    item_id, store = _busy_item(client, app)
    store.post(item_id, "which one?", actor="claude", kind="question")
    store.post(item_id, "fresh info", actor="claude", kind="info", notify=True)
    full = client.get(f"/api/v1/cplugs/huddle/items/{item_id}").json()
    assert len(full["thread"]) == 8 and "thread_slim" not in full
    slim = client.get("/api/v1/cplugs/huddle/aggregate").json()["groups"][0]["items"][0]
    kept = [m["text"] for m in slim["thread"]]
    assert kept == ["which one?", "fresh info"] and slim["thread_count"] == 8 and slim["thread_slim"] is True
    assert slim["status"] == full["status"] and slim["needs_you"] == full["needs_you"] and slim["unread"] == full["unread"]


def test_aggregate_threads_opt_in_keeps_the_whole_thread(client, app):
    item_id, _store_ = _busy_item(client, app)
    whole = client.get("/api/v1/cplugs/huddle/aggregate?threads=1").json()["groups"][0]["items"][0]
    assert len(whole["thread"]) == 6 and "thread_slim" not in whole


def test_item_read_refuses_an_unknown_item_and_needs_auth(client, app):
    assert client.get("/api/v1/cplugs/huddle/items/9999").status_code == 404
    app.dependency_overrides.clear()
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/cplugs/huddle/items/1").status_code in (401, 403)


def _done_and_open(client):
    base = "/api/v1/cplugs/huddle"
    open_item = client.post(f"{base}/lists/12/items", json={"text": "still open"}).json()
    done = client.post(f"{base}/lists/12/items", json={"text": "ZEBRA-HIDDEN-TEXT"}).json()
    client.post(f"{base}/items/{done['id']}/messages", json={"text": "ZEBRA-HIDDEN-REPLY"})
    client.patch(f"{base}/items/{done['id']}", json={"approved": True, "note": "ZEBRA-HIDDEN-NOTE"})
    return open_item, done


def test_hide_completed_reads_send_a_completed_item_as_a_placeholder_with_no_text(client):
    base = "/api/v1/cplugs/huddle"
    open_item, done = _done_and_open(client)
    for url in (f"{base}/lists/12?hide_completed=1", f"{base}/aggregate?hide_completed=1"):
        response = client.get(url)
        assert "ZEBRA-HIDDEN" not in response.text, url
        body = response.json()
        items = body["items"] if "items" in body else body["groups"][0]["items"]
        ph = next(i for i in items if i["id"] == done["id"])
        assert ph["placeholder"] is True and ph["state"] in rules.APPROVED_STATES
        assert ph["list"] == "12" and isinstance(ph["position"], int) and ph["text"] == "" and ph["thread"] == []
        kept = next(i for i in items if i["id"] == open_item["id"])
        assert kept["text"] == "still open" and "placeholder" not in kept
        assert [i["id"] for i in items] == [open_item["id"], done["id"]]


def test_hide_completed_off_is_byte_identical_and_still_carries_the_text(client):
    base = "/api/v1/cplugs/huddle"
    _done_and_open(client)
    for url in (f"{base}/lists/12", f"{base}/aggregate"):
        plain = client.get(url)
        assert "ZEBRA-HIDDEN-TEXT" in plain.text and "placeholder" not in plain.text
        assert client.get(url + "?hide_completed=0").content == plain.content


def test_reorder_built_from_the_placeholder_read_is_accepted(client):
    base = "/api/v1/cplugs/huddle"
    open_item, done = _done_and_open(client)
    read = client.get(f"{base}/lists/12?hide_completed=1").json()
    ids = [i["id"] for i in read["items"]][::-1]
    moved = client.put(f"{base}/lists/12/order", json={"ids": ids, "expected_revision": read["revision"]})
    assert moved.status_code == 200 and [i["id"] for i in moved.json()["items"]] == ids
