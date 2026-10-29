
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
from structlog.testing import capture_logs

from src.api import one_shot_routes
from src.cplugs.host import runtime
from src.cplugs.huddle import item_owner, owner_read, structured
from src.cplugs.huddle.roles import mcp_tags
from src.cplugs.huddle.rules import CLAUDE, JOE
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

URL = "/api/v1/cplugs/huddle/send"


def store_of(app) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)


def untold(client, key: str) -> bool:
    return next(r for r in client.get("/api/v1/cplugs/huddle/lists").json()["lists"] if r["key"] == key)["untold"]


def joe_reply(client, item_id: int, text: str = "see my note") -> None:
    assert client.post(f"/api/v1/cplugs/huddle/items/{item_id}/messages", json={"text": text}).status_code == 200


def add(client, text: str) -> int:
    return client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": text}).json()["id"]


def told_once(client) -> None:
    assert client.post(URL, json={"lists": ["12"]}).json()["results"][0]["status"] == "sent"


def test_a_reply_on_a_claimed_item_is_told_to_the_claimant_not_the_last_caller(client, app, pasted):
    item = add(client, "build it")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store_of(app).mark_working(item, "ses_new")
    joe_reply(client, item)
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert (result["status"], result["target"], result["reason"]) == ("sent", "ses_new", "owner")
    assert pasted[-1][0] == "ses_new" and f"(item ids {item})" in pasted[-1][1]
    assert [p[0] for p in pasted[1:]] == ["ses_new"]
    assert untold(client, "12") is False


def test_claimed_and_unclaimed_changes_split_into_two_tells_each_with_its_own_cursor(client, app, pasted):
    mine, theirs = add(client, "owned"), add(client, "plain")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store = store_of(app)
    store.mark_working(mine, "ses_new")
    store.note_read("ses_new", "12", 4)
    store.note_read("ses_old", "12", 2)
    joe_reply(client, mine)
    joe_reply(client, theirs)
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "sent" and result["target"] == "ses_old"
    assert [(p["target"], p["reason"], p["items"], p["status"]) for p in result["parts"]] == [
        ("ses_new", "owner", [mine], "sent"), ("ses_old", "last_task_manager_caller", [theirs], "sent")]
    owner_line, default_line = pasted[-2], pasted[-1]
    assert owner_line[0] == "ses_new" and f"(item ids {mine})" in owner_line[1] and "(list 12, since 4)" in owner_line[1]
    assert default_line[0] == "ses_old" and f"(item ids {theirs})" in default_line[1] and "(list 12, since 2)" in default_line[1]
    assert untold(client, "12") is False


def test_a_claimant_that_is_not_live_falls_back_to_the_default_and_logs_why(client, app, pasted):
    item = add(client, "orphan")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store_of(app).mark_working(item, "ses_gone")
    joe_reply(client, item)
    with capture_logs() as logs:
        result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert (result["status"], result["target"], result["reason"]) == ("sent", "ses_old", "last_task_manager_caller")
    assert "parts" not in result and "item ids" not in pasted[-1][1]
    assert any(e["event"] == "task_manager_owner_not_live" and e["item"] == item and e["fallback"] == "ses_old" for e in logs)


def test_the_claim_outlives_review_and_waiting_install_and_a_tick_ends_it(client, app, pasted):
    item = add(client, "ship it")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store = store_of(app)
    store.mark_working(item, "ses_new")
    store.update(item, actor=CLAUDE, state="review")
    after_review = store.item(item)
    assert after_review[item_owner.COLUMN] == "ses_new"
    joe_reply(client, item, "not quite")
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert (result["target"], result["reason"]) == ("ses_new", "owner")
    store.update(item, actor=CLAUDE, state="waiting")
    assert store.item(item)[item_owner.COLUMN] == "ses_new"
    client.patch(f"/api/v1/cplugs/huddle/items/{item}", json={"approved": True})
    assert store.item(item)[item_owner.COLUMN] == "ses_new"
    client.post(URL, json={"lists": ["12"]})
    assert store.item(item)[item_owner.COLUMN] == ""


def test_a_tick_on_an_untagged_item_is_told_to_its_owner_not_the_default(client, app, pasted):
    item = add(client, "fix the defects")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store_of(app).mark_working(item, "ses_new")
    assert client.patch(f"/api/v1/cplugs/huddle/items/{item}", json={"approved": True}).status_code == 200
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert (result["status"], result["target"], result["reason"]) == ("sent", "ses_new", "owner")
    assert pasted[-1][0] == "ses_new" and f"(item ids {item})" in pasted[-1][1]
    assert store_of(app).item(item)[item_owner.COLUMN] == ""


def test_an_agent_add_is_tagged_to_its_session_and_never_for_an_external_token(manager):
    ok, out = call(manager, "task_manager_add", {"list": "12", "text": "mine"})
    assert ok and out["tagged_session_key"] == "ses_1"
    ok, batched = call(manager, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "add", "text": "batched"}]})
    assert ok, batched
    assert huddle_store(manager).item(next(r["item_id"] for r in batched["results"] if r.get("item_id")))["tagged_session_key"] == "ses_1"
    plain = {"id": 99, "tagged_session_key": ""}
    for key, external in (("mcp-token:t1", True), (None, False), ("swarm", False)):
        assert asyncio.run(mcp_tags.tag_filer(None, plain, key, external=external)) is plain


def test_a_new_claim_moves_ownership_and_a_read_never_does(client, app, pasted):
    item = add(client, "contested")
    store = store_of(app)
    store.mark_working(item, "ses_new")
    store.update(item, actor=CLAUDE, state="review")
    joe_reply(client, item)
    note(app, "ses_old", "12", 100.0)
    client.post(URL, json={"lists": ["12"]})
    seq = store.item(item)["seq"]
    store.record_claude_read([(item, seq)])
    assert store.item(item)[item_owner.COLUMN] == "ses_new" and store.item(item)["status"] != "working"
    store.mark_working(item, "ses_old")
    assert store.item(item)[item_owner.COLUMN] == "ses_old"


def test_a_refused_owner_part_leaves_the_list_untold_and_the_default_part_still_goes(client, app, monkeypatch):
    sent = []

    async def paste(request, session_id, text):
        if session_id == "ses_new":
            raise HTTPException(status_code=409, detail={"code": "paste_shell", "detail": "a shell is in front"})
        sent.append((session_id, text))
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)
    mine, theirs = add(client, "owned"), add(client, "plain")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store_of(app).mark_working(mine, "ses_new")
    joe_reply(client, mine)
    joe_reply(client, theirs)
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "refused"
    assert [(p["target"], p["status"]) for p in result["parts"]] == [("ses_new", "refused"), ("ses_old", "sent")]
    assert sent[-1][0] == "ses_old" and f"(item ids {theirs})" in sent[-1][1]
    assert untold(client, "12") is True


def test_split_is_pure_and_keeps_an_owner_that_is_the_default_in_one_tell():
    rows = [{"id": "s_a", "key": "u-a"}, {"id": "s_b", "key": "u-b"}]
    whole = item_owner.split([(1, "u-b"), (2, "")], rows, "s_b", "picked")
    assert not whole.divided and [(p.target, p.items) for p in whole.parts] == [("s_b", [1, 2])]
    owned_only = item_owner.split([(1, "u-a")], rows, None, "pick")
    assert owned_only.divided and [(p.target, p.reason, p.items) for p in owned_only.parts] == [("s_a", "owner", [1])]
    gone = item_owner.split([(3, "u-z")], rows, "s_b", "only_session")
    assert gone.gone == {3: "u-z"} and [(p.target, p.items) for p in gone.parts] == [("s_b", [3])]


def test_huddle_list_rows_name_the_owner_while_it_is_live(manager):
    store = huddle_store(manager)
    item = store.add("12", "work", actor=JOE)["id"]
    other = store.add("12", "theirs", actor=JOE)["id"]
    assert call(manager, "task_manager_update", {"item": item, "state": "working"})[0]
    store.mark_working(other, "ses_elsewhere")
    assert call(manager, "task_manager_update", {"item": item, "state": "review"})[0]
    ok, out = call(manager, "task_manager_tasks_list", {"list": "12"})
    assert ok, out
    rows = {r["id"]: r for r in out["items"]}
    assert rows[item][item_owner.FIELD] == "ses_1" and item_owner.FIELD not in rows[other]
    assert owner_read.held_by([{"id": item, item_owner.COLUMN: "ses_1"}], CALLER, None) == {item}


def test_the_session_that_asked_a_typed_question_on_an_unclaimed_item_is_told_the_form_answer(client, app, pasted):
    item = add(client, "plan it")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store = store_of(app)
    assert store.item(item)[item_owner.COLUMN] == ""
    text, parts = structured.build(None, "which way", [{"id": "go", "type": "yes_no", "prompt": "Go?", "labels": ["go", "stop"]}])
    asked = store.post(item, text, actor=CLAUDE, kind="question", author_key="ses_new", parts=parts)
    assert store.item(item)[item_owner.COLUMN] == "ses_new"
    done = client.post(f"/api/v1/cplugs/huddle/questions/{asked['message']['id']}/answer", json={"answers": {"go": {"value": True}}})
    assert done.status_code == 200, done.text
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert (result["status"], result["target"], result["reason"]) == ("sent", "ses_new", "owner")
    assert pasted[-1][0] == "ses_new" and f"(item ids {item})" in pasted[-1][1]


def test_asking_never_takes_an_item_another_session_owns_and_the_swarm_key_owns_nothing(client, app):
    item = add(client, "held")
    store = store_of(app)
    store.mark_working(item, "ses_new")
    store.post(item, "q", actor=CLAUDE, kind="question", author_key="ses_other")
    assert store.item(item)[item_owner.COLUMN] == "ses_new"
    plain = add(client, "chat")
    store.post(plain, "q", actor=CLAUDE, kind="question", author_key="swarm")
    assert store.item(plain)[item_owner.COLUMN] == ""


def test_each_owners_tell_names_only_the_replies_on_its_own_items(client, app, pasted):
    a, b, plain = add(client, "a's"), add(client, "b's"), add(client, "nobody's")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store = store_of(app)
    store.mark_working(a, "ses_new")
    store.mark_working(b, "ses_codex")
    for item in (a, b, plain):
        joe_reply(client, item)
    result = client.post(URL, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "sent"
    lines = {target: text for target, text in pasted[-3:]}
    assert set(lines) == {"ses_new", "ses_codex", "ses_old"}
    for target, mine in (("ses_new", a), ("ses_codex", b), ("ses_old", plain)):
        named = {i for i in (a, b, plain) if f"task {i} (message" in lines[target]}
        assert named == {mine}, (target, lines[target])


def test_a_reply_already_told_to_its_owner_is_not_named_again_to_the_default(client, app, pasted):
    owned, plain = add(client, "owned"), add(client, "plain")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store_of(app).mark_working(owned, "ses_new")
    joe_reply(client, owned)
    client.post(URL, json={"lists": ["12"]})
    assert pasted[-1][0] == "ses_new"
    joe_reply(client, plain)
    client.post(URL, json={"lists": ["12"]})
    line = pasted[-1]
    assert line[0] == "ses_old" and f"task {plain} (message" in line[1] and f"task {owned} (message" not in line[1]


def test_an_unowned_items_reply_goes_to_the_default_and_an_owner_gone_falls_back_to_it(client, app, pasted):
    plain, orphan = add(client, "plain"), add(client, "orphan")
    note(app, "ses_old", "12", 100.0)
    told_once(client)
    store_of(app).mark_working(orphan, "ses_gone")
    joe_reply(client, plain)
    joe_reply(client, orphan)
    client.post(URL, json={"lists": ["12"]})
    target, text = pasted[-1]
    assert target == "ses_old" and f"task {plain} (message" in text and f"task {orphan} (message" in text
