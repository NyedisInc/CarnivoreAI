
from __future__ import annotations

from contextlib import closing

from src.cplugs.huddle import item_owner, lineage
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.roles import ask, lost, route, tag_send
from tests.python.cplugs.huddle.roles_rig import BASE, give_stored_rows
from tests.python.cplugs.huddle.test_task_manager_nudge_sweep import ITEMS, LISTS, Rig, rig  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import SEND, World, add, joe_reply, store_of, told_once, world  # noqa: F401
from src.cplugs.sdk.session_rows import StoredRow


def questions(store, item: int) -> list:
    return [(m["author_key"], m["category"]) for m in store.item(item)["thread"] if m["kind"] == "question"]


def test_a_list_past_500_items_accepts_an_add_and_a_move(client, world):
    store = store_of(world.app)
    with closing(store._connect(True)) as conn, conn:
        conn.executemany("INSERT INTO work_items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                         "VALUES ('12', 'bulk', ?, 'joe', 'open', 1, 1, 1, 1)", [(n,) for n in range(500)])
    made = client.post(f"{BASE}/lists/12/items", json={"text": "number 501"})
    assert made.status_code == 200 and made.json()["position"] == 500
    other = client.post(f"{BASE}/lists/all/items", json={"text": "elsewhere"}).json()["id"]
    moved = client.post(f"{ITEMS}/{other}/move", json={"list": "12"})
    assert moved.status_code == 200 and store.item(other)["list"] == "12"


def test_an_owner_session_gone_at_a_send_hands_its_task_to_the_lead(client, world, pasted):
    item = add(client)
    told_once(client)
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).status_code == 200
    store_of(world.app).mark_working(item, "ses_ghost")
    joe_reply(client, item)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    moved = store_of(world.app).item(item)
    assert moved[item_owner.COLUMN] == "ses_new" and result["status"] == "sent" and pasted[-1][0] == "ses_new"
    with closing(store_of(world.app)._connect(False)) as conn:
        last = lineage.for_item(conn, item)[-1]
    assert (last["by"], last["detail"]) == ("carnivore", "session_gone")


def test_an_owner_session_gone_with_no_lead_is_one_question_to_joe(client, world, pasted):
    item = add(client)
    told_once(client)
    store_of(world.app).mark_working(item, "ses_ghost")
    joe_reply(client, item)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "sent" and pasted[-1][0] == "ses_old"
    assert questions(store_of(world.app), item) == [("carnivore", ask.OWNER_GONE)]
    assert tag_send._ask_for_gone(store_of(world.app), [item], ask.OWNER_GONE) == []
    assert questions(store_of(world.app), item) == [("carnivore", ask.OWNER_GONE)]


def test_an_owner_whose_row_still_stands_is_not_gone(client, world, monkeypatch):
    give_stored_rows(monkeypatch, {"ses_ghost": StoredRow(12, False)})
    item = add(client)
    told_once(client)
    client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"})
    store_of(world.app).mark_working(item, "ses_ghost")
    joe_reply(client, item)
    client.post(SEND, json={"lists": ["12"]})
    assert store_of(world.app).item(item)[item_owner.COLUMN] == "ses_ghost" and questions(store_of(world.app), item) == []


def test_an_archived_row_is_gone_and_an_unreadable_table_decides_nothing(world, monkeypatch):
    import asyncio
    from src.cplugs.sdk.session_rows import SessionRowsUnreadable
    ctx = world.app.state
    from src.cplugs.host import runtime
    hctx = runtime.host_for(world.app).context("huddle", background=True)
    give_stored_rows(monkeypatch, {"ses_ghost": StoredRow(12, True)})
    assert asyncio.run(lost.lost_outcome(hctx, "ses_ghost", wake=False)) == route.GONE
    give_stored_rows(monkeypatch, SessionRowsUnreadable("locked"))
    assert asyncio.run(lost.lost_outcome(hctx, "ses_ghost", wake=False)) is None


def test_a_dead_sessions_open_task_goes_to_the_lead_on_a_nudge_pass_and_is_then_nudged(client, rig):
    item = rig.add(client)
    rig.own(item["id"], "ses_ghost")
    assert client.put(f"{LISTS}/12/lead", json={"session": "ses_new"}).status_code == 200
    rig.switch(client)
    rig.sweep(0.5)
    assert rig.item(item["id"])[item_owner.COLUMN] == "ses_ghost" and rig.pasted == []
    rig.sweep(1.5)
    assert rig.item(item["id"])[item_owner.COLUMN] == "ses_new" and rig.pasted == []
    rig.sweep(3.0)
    assert [t for t, _ in rig.pasted] == ["ses_new"]


def test_a_dead_sessions_open_task_with_no_lead_becomes_a_question_with_no_nudge(client, rig):
    item = rig.add(client)
    rig.own(item["id"], "ses_ghost")
    rig.switch(client)
    rig.sweep(1.5)
    assert rig.pasted == [] and questions(rig.store, item["id"]) == [("carnivore", ask.OWNER_GONE)]
    rig.sweep(3.0)
    assert rig.pasted == [] and len(questions(rig.store, item["id"])) == 1


def test_a_dead_session_is_picked_up_even_with_no_session_live(client, rig):
    item = rig.add(client)
    rig.own(item["id"], "ses_ghost")
    rig.set_rows([])
    rig.switch(client)
    rig.sweep(1.5)
    assert questions(rig.store, item["id"]) == [("carnivore", ask.OWNER_GONE)]


def test_a_waiting_task_of_a_dead_session_is_never_touched(client, rig):
    item = rig.add(client)
    rig.own(item["id"], "ses_ghost")
    client.patch(f"{ITEMS}/{item['id']}", json={"state": "waiting"})
    rig.switch(client)
    rig.sweep(5.0)
    assert rig.pasted == [] and questions(rig.store, item["id"]) == [] and rig.item(item["id"])[item_owner.COLUMN] == "ses_ghost"


def test_an_answered_owner_question_clears_the_dead_owner(client, rig):
    item = rig.add(client)
    rig.own(item["id"], "ses_ghost")
    rig.switch(client)
    rig.sweep(1.5)
    asked = [m for m in rig.item(item["id"])["thread"] if m["kind"] == "question" and not m["answered"]][-1]
    AnswerWriter(rig.store).submit(asked["id"], {ask.QUESTION_ID: {"choice": ask.CANCEL}})
    assert rig.item(item["id"])[item_owner.COLUMN] == ""
