
from __future__ import annotations

from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_mcp import huddle_store

LIST = "/api/v1/cplugs/huddle/lists/12"
ITEMS = "/api/v1/cplugs/huddle/items"


def row(client, item_id: int) -> dict:
    return next(i for i in client.get(LIST).json()["items"] if i["id"] == item_id)


def summary(client) -> dict:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == "12")


def seed_look(setup, item: int, text: str) -> dict:
    return huddle_store(setup.manager).post(item, text, actor="claude", kind="attention")["message"]


def working_item(client, setup) -> int:
    item = add(client, "12", "fix the drawer padding")
    assert call(setup.manager, "task_manager_tasks_list", {"list": "12"})[0]
    assert call(setup.manager, "task_manager_update", {"item": item, "state": "working"})[0]
    assert row(client, item)["status"] == "working"
    return item


def test_info_while_working_is_not_unread_keeps_the_status_and_is_read_one_by_one(client, setup):
    item = working_item(client, setup)
    before = summary(client)
    ok, posted = call(setup.manager, "task_manager_reply", {"item": item, "text": "found it in drawer.css", "kind": "info"})
    assert ok and posted["kind"] == "info"
    assert call(setup.manager, "task_manager_reply", {"item": item, "text": "and in sidebar.css", "kind": "info"})[0]
    now = row(client, item)
    assert now["status"] == "working" and now["section"] == "working" and now["unread"] is False
    assert now["info_unseen"] is True and now["info_unread"] == 2 and now["attention_unseen"] is False
    first, second = [m for m in now["thread"] if m["kind"] == "info" and not m.get("category")]
    assert first["unread"] is True and second["unread"] is True
    after = summary(client)
    assert after["unread"] == 0 and after["claude_seq"] == before["claude_seq"]
    assert after["waiting_to_send"] == before["waiting_to_send"]
    assert client.post(f"{ITEMS}/{item}/seen", json={"message": first["id"]}).status_code == 200
    now = row(client, item)
    assert now["info_unread"] == 1 and [m["unread"] for m in now["thread"] if m["kind"] == "info" and not m.get("category")] == [False, True]
    assert now["status"] == "working"
    assert client.post(f"{ITEMS}/{item}/seen", json={"message": second["id"]}).status_code == 200
    assert row(client, item)["info_unseen"] is False
    client.post(f"{ITEMS}/{item}/messages", json={"text": "thanks"})
    joe_msg = next(m for m in row(client, item)["thread"] if m["author"] == "joe")
    assert client.post(f"{ITEMS}/{item}/seen", json={"message": joe_msg["id"]}).status_code == 400
    assert client.post(f"{ITEMS}/{item}/seen", json={"message": 999999}).status_code == 400


def test_a_look_is_just_like_an_info_but_still_marks_the_item_unread_and_surfaces_the_tab(client, setup):
    item = working_item(client, setup)
    before = summary(client)["claude_seq"]
    assert seed_look(setup, item, "look: the fix changes the tab order")["kind"] == "attention"
    seed_look(setup, item, "and the focus ring")
    assert call(setup.manager, "task_manager_reply", {"item": item, "text": "an fyi", "kind": "info"})[0]
    now = row(client, item)
    assert now["unread"] is True and now["attention_unseen"] is True and now["attention_unread"] == 2
    assert now["info_unread"] == 1
    assert now["status"] == "open" and now["section"] == "open"
    assert summary(client)["unread"] == 1 and summary(client)["claude_seq"] > before
    first, second = [m for m in now["thread"] if m["kind"] == "attention"]
    assert first["unread"] is True and second["unread"] is True
    assert row(client, item)["unread"] is True and row(client, item)["attention_unread"] == 2
    assert client.post(f"{ITEMS}/{item}/seen", json={"message": first["id"]}).status_code == 200
    now = row(client, item)
    assert now["attention_unread"] == 1 and now["info_unread"] == 1 and now["status"] == "open"
    assert [m["unread"] for m in now["thread"] if m["kind"] == "attention"] == [False, True]
    assert client.post(f"{ITEMS}/{item}/seen", json={"message": second["id"]}).status_code == 200
    now = row(client, item)
    assert now["attention_unseen"] is False and now["info_unread"] == 1 and now["status"] == "open"


def test_question_stays_a_question_and_kinds_are_checked(client, setup):
    item = working_item(client, setup)
    assert call(setup.manager, "task_manager_ask", {"item": item, "text": "keep the old order?"})[0]
    now = row(client, item)
    assert now["status"] == "question" and now["unread"] is True and now["thread"][-1]["kind"] == "question"
    ok, _ = call(setup.manager, "task_manager_reply", {"item": item, "text": "x", "kind": "question"})
    assert not ok


def test_default_kind_is_info_on_every_status(client, setup):
    item = working_item(client, setup)
    ok, posted = call(setup.manager, "task_manager_reply", {"item": item, "text": "on it"})
    assert ok and posted["kind"] == "info" and row(client, item)["unread"] is False
    ok, added = call(setup.manager, "task_manager_add", {"list": "12", "text": "a finding"})
    client.post(f"{ITEMS}/{added['id']}/seen")
    ok, posted = call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "see this"})
    assert ok and posted["kind"] == "info" and row(client, added["id"])["unread"] is False


def test_info_on_an_open_item_leaves_it_open(client, setup):
    ok, added = call(setup.manager, "task_manager_add", {"list": "12", "text": "profiling the listing"})
    client.post(f"{ITEMS}/{added['id']}/seen")
    assert row(client, added["id"])["status"] == "open"
    assert call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "halfway", "kind": "info"})[0]
    now = row(client, added["id"])
    assert now["status"] == "open" and now["unread"] is False and now["info_unseen"] is True


def test_mark_answered_clears_the_question_and_a_later_reply_never_does(client, setup):
    item = working_item(client, setup)
    assert call(setup.manager, "task_manager_ask", {"item": item, "text": "keep the old order?"})[0]
    assert call(setup.manager, "task_manager_reply", {"item": item, "text": "meanwhile, a finding", "kind": "info"})[0]
    assert row(client, item)["status"] == "question"
    ok, marked = call(setup.manager, "task_manager_answered_set", {"item": item})
    assert ok and marked["status"] != "question"
    now = row(client, item)
    assert now["status"] != "question" and all(m["answered"] for m in now["thread"] if m["kind"] == "question")
    assert [m["author"] for m in now["thread"]].count("joe") == 0
    assert call(setup.manager, "task_manager_answered_set", {"item": item})[0]
    ok, _ = call(setup.manager, "task_manager_answered_set", {"item": item, "list": "12"})
    assert not ok
    assert call(setup.manager, "task_manager_ask", {"item": item, "text": "and the colour?"})[0]
    assert client.post(f"{ITEMS}/{item}/answered").status_code == 200
    assert row(client, item)["status"] != "question"
    assert client.post(f"{ITEMS}/999999/answered").status_code == 404


def test_a_bare_attention_or_a_read_action_is_an_info_that_notifies(client, setup):
    for args in ({"kind": "attention"}, {"action": "read"}, {"kind": "attention", "action": "none"}, {"kind": "info", "notify": True}):
        ok, added = call(setup.manager, "task_manager_add", {"list": "12", "text": "a finding"})
        client.post(f"{ITEMS}/{added['id']}/seen")
        ok, posted = call(setup.manager, "task_manager_reply", {"item": added["id"], "text": "see this", **args})
        assert ok and posted["kind"] == "info", args
        now = row(client, added["id"])
        assert now["unread"] is True and now["attention_unread"] == 0 and now["info_unread"] == 1, args
        assert client.post(f"{ITEMS}/{added['id']}/seen").status_code == 200
        assert row(client, added["id"])["unread"] is False


def test_an_info_without_notify_stays_read_and_notify_goes_only_on_an_info(client, setup):
    item = working_item(client, setup)
    assert call(setup.manager, "task_manager_reply", {"item": item, "text": "fyi", "notify": False})[0] and row(client, item)["unread"] is False
    ok, out = call(setup.manager, "task_manager_reply", {"item": item, "text": "x", "kind": "answer", "quote_text": "his words", "notify": True})
    assert not ok and "notify goes only on an info" in out


def test_a_look_that_asks_is_refused_and_points_to_its_replacement(client, setup):
    item = working_item(client, setup)
    for action, pointer in (("answer", "task_manager_ask"), ("tick", "task_manager_update"), ("push", "task_manager_update")):
        for args in ({"kind": "attention", "action": action}, {"action": action}):
            ok, out = call(setup.manager, "task_manager_reply", {"item": item, "text": "x", **args})
            assert not ok and pointer in out, (args, out)
    assert [m for m in row(client, item)["thread"] if not m.get("category")] == []
    ok, out = call(setup.manager, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "reply", "item_id": item, "text": "x", "kind": "attention", "action": "tick"},
                                                                          {"op": "reply", "item_id": item, "text": "y", "kind": "attention"}]})
    assert ok and [r["ok"] for r in out["results"]] == [False, True] and "task_manager_update" in out["results"][0]["error"]
