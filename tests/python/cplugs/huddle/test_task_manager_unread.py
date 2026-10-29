
from __future__ import annotations

from tests.python.cplugs.huddle.test_task_manager_focus import FOCUS, add, call, client, setup  # noqa: F401

LIST = "/api/v1/cplugs/huddle/lists/12"
ITEMS = "/api/v1/cplugs/huddle/items"


def row(client, item_id: int) -> dict:
    return next(i for i in client.get(LIST).json()["items"] if i["id"] == item_id)


def unread_count(client) -> int:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == "12")["unread"]


def test_claude_writes_mark_unread_and_seen_clears_it_everywhere(client, setup):
    ok, added = call(setup.manager, "task_manager_add", {"list": "12", "text": "shipped it"})
    assert ok and added["unread"] is False
    assert call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "look", "notify": True})[0]
    mine = add(client, "12", "joe's own")
    assert row(client, mine)["unread"] is False
    assert row(client, added["id"])["unread"] is True and unread_count(client) == 1

    revision = client.get(LIST).json()["revision"]
    setup.published.clear()
    seen = client.post(f"{ITEMS}/{added['id']}/seen")
    assert seen.status_code == 200 and seen.json()["unread"] is False
    assert setup.published == ["cplug.huddle.list:12", "cplug.huddle.cards:12"]
    assert client.get(LIST).json()["revision"] == revision
    assert unread_count(client) == 0
    setup.published.clear()
    assert client.post(f"{ITEMS}/{added['id']}/seen").status_code == 200
    assert setup.published == []
    assert client.post(f"{ITEMS}/9999/seen").status_code == 404

    for name, args in (("task_manager_update", {"state": "review"}),
                       ("task_manager_reply", {"text": "see the log", "notify": True}), ("task_manager_ask", {"text": "ok to merge?"})):
        assert call(setup.manager, name, {"item": added["id"], **args})[0]
        assert row(client, added["id"])["unread"] is True, name
        client.post(f"{ITEMS}/{added['id']}/seen")
    call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "one more"})
    client.post(f"{ITEMS}/{added['id']}/messages", json={"text": "yes"})
    assert row(client, added["id"])["unread"] is False
    call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "merged"})
    current = row(client, added["id"])
    client.patch(f"{ITEMS}/{added['id']}", json={"approved": True, "expected_revision": current["revision"]})
    assert row(client, added["id"])["unread"] is False


def test_claude_focus_marks_unread_the_owners_focus_does_not(client, setup):
    a, b, c = add(client, "12", "one"), add(client, "12", "two"), add(client, "12", "three")
    assert client.post(FOCUS, json={"list": "12", "items": [a]}).status_code == 200
    assert row(client, a)["unread"] is False
    setup.published.clear()
    ok, _ = call(setup.manager, "huddle_focus", {"list": "12", "items": [b], "open": c})
    assert ok
    assert [row(client, i)["unread"] for i in (a, b, c)] == [False, True, True]
    assert "cplug.huddle.list:12" in setup.published and "cplug.huddle.focus" in setup.published


def test_claude_reads_unread_in_list_and_changes(client, setup):
    _, added = call(setup.manager, "task_manager_add", {"list": "12", "text": "need your call"})
    call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "look", "notify": True})
    ok, changed = call(setup.manager, "task_manager_changes", {"since": 0, "list": "12"})
    assert ok and changed["items"][0]["unread"] is True
    ok, listed = call(setup.manager, "task_manager_tasks_list", {"list": "12"})
    assert ok and listed["items"][0]["unread"] is True
    client.post(f"{ITEMS}/{added['id']}/seen")
    _, listed = call(setup.manager, "task_manager_tasks_list", {"list": "12"})
    assert listed["items"][0]["unread"] is False


def test_the_badge_counts_open_items_only(client, setup):
    kept = call(setup.manager, "task_manager_add", {"list": "12", "text": "open one"})[1]["id"]
    done = call(setup.manager, "task_manager_add", {"list": "12", "text": "ticked"})[1]["id"]
    gone = call(setup.manager, "task_manager_add", {"list": "12", "text": "deleted"})[1]["id"]
    asked = call(setup.manager, "task_manager_add", {"list": "12", "text": "asked then ticked"})[1]["id"]
    for born in (kept, done, gone):
        call(setup.manager, "task_manager_reply", {"item": born, "text": "look", "notify": True})
    call(setup.manager, "task_manager_ask", {"item": asked, "text": "which?"})
    assert unread_count(client) == 4
    revision = row(client, done)["revision"]
    assert client.patch(f"{ITEMS}/{done}", json={"approved": True, "expected_revision": revision}).status_code == 200
    call(setup.manager, "task_manager_reply", {"item": done, "text": "late note", "notify": True})
    assert client.delete(f"{ITEMS}/{gone}").status_code == 200
    assert client.patch(f"{ITEMS}/{asked}", json={"approved": True, "expected_revision": row(client, asked)["revision"]}).status_code == 200
    mine = next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == "12")
    assert mine["unread"] == 1 and mine["questions"] == 0
    assert unread_count(client) == 1 and row(client, kept)["unread"] is True


def test_the_badge_is_the_incomplete_count(client, setup):
    ids = [call(setup.manager, "task_manager_add", {"list": "12", "text": f"item {n}"})[1]["id"] for n in range(16)]
    call(setup.manager, "task_manager_ask", {"item": ids[0], "text": "which?"})
    call(setup.manager, "task_manager_update", {"item": ids[1], "state": "review"})
    for item in ids[12:15]:
        assert client.patch(f"{ITEMS}/{item}", json={"approved": True, "expected_revision": row(client, item)["revision"]}).status_code == 200
    assert client.delete(f"{ITEMS}/{ids[15]}").status_code == 200
    mine = next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == "12")
    assert mine["incomplete"] == 12


def test_plain_agent_changes_never_make_an_item_unread_only_what_needs_his_eyes_does(client, setup):
    ok, added = call(setup.manager, "task_manager_add", {"list": "12", "text": "ship the drawer"})
    item = added["id"]
    client.post(f"{ITEMS}/{item}/seen")
    assert row(client, item)["unread"] is False
    for name, args in (("task_manager_update", {"text": "ship the drawer, v2"}), ("task_manager_update", {"state": "working"}),
                       ("task_manager_update", {"state": "open"}),
                       ("task_manager_reply", {"text": "fyi, found it", "kind": "info"})):
        assert call(setup.manager, name, {"item": item, **args})[0], (name, args)
        assert row(client, item)["unread"] is False, (name, args)
    ok, other = call(setup.manager, "task_manager_add", {"list": "12", "text": "a second task"})
    client.post(f"{ITEMS}/{other['id']}/seen")
    assert call(setup.manager, "task_manager_fork", {"item": other["id"], "text": "the follow up"})[0]
    assert row(client, other["id"])["unread"] is False
    for name, args in (("task_manager_update", {"state": "review"}), ("task_manager_reply", {"text": "look", "notify": True}),
                       ("task_manager_ask", {"text": "ok to merge?"})):
        client.post(f"{ITEMS}/{item}/seen")
        assert row(client, item)["unread"] is False
        assert call(setup.manager, name, {"item": item, **args})[0], (name, args)
        assert row(client, item)["unread"] is True, (name, args)
