
from __future__ import annotations

from contextlib import closing

from src.cplugs.huddle import inbox, rules
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import JOE
from tests.python.cplugs.huddle.test_task_manager_inbox import BASE, call, env, manager, tool_store  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_inbox_stuck import app, client, stick  # noqa: F401


def promote(store, item_id: int, state: str = "open") -> None:
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET state = ? WHERE id = ?", (state, item_id))


def test_deleting_one_item_of_an_entry_leaves_the_others_text_and_thread(client, env):
    stuck = stick(client, env)
    carrier = stuck["carrier"]
    promote(env.store, carrier)
    made = env.store.add("12", "filed by a session", actor=rules.CLAUDE)
    env.inbox.link_item(stuck["entry"]["id"], made["id"])
    env.store.delete(made["id"], actor=JOE)
    survivor = env.store.item(carrier)
    assert survivor["text"] and not survivor.get("deleted") and survivor["thread"]


def test_a_carrier_nobody_touched_is_still_retired_by_a_late_filing(client, env):
    stuck = stick(client, env)
    made = env.store.add("12", "filed late", actor=rules.CLAUDE)
    env.inbox.link_item(stuck["entry"]["id"], made["id"])
    assert env.inbox.carriers(stuck["entry"]["id"]) == []


def test_the_list_files_a_stuck_entry_with_its_promoted_carrier(client, env):
    stuck = stick(client, env)
    promote(env.store, stuck["carrier"])
    assert env.inbox.open_entries() == []
    entry = env.inbox.get(stuck["entry"]["id"])
    assert entry["status"] == inbox.FILED and entry["item_ids"] == [stuck["carrier"]]
    assert env.store.item(stuck["carrier"])["text"]


def test_entry_import_attaches_instead_of_duplicating(manager):
    store = tool_store(manager)
    inboxes = InboxStore(store)
    entry = inboxes.add("12", "backlog dark mode")
    inboxes.mark_stuck(entry["id"])
    carrier = store.add("12", entry["text"], actor=rules.CLAUDE, created_key=rules.CARNIVORE_KEY, state=rules.TODO, title="backlog")
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET inbox_id = ?, state = 'open' WHERE id = ?", (entry["id"], carrier["id"]))
    ok, text = call(manager, "task_manager_entry_import", {"inbox_id": entry["id"], "items": [{"title": "t", "text": "x"}]})
    assert not ok and str(carrier["id"]) in text
    final = inboxes.get(entry["id"])
    assert final["status"] == inbox.FILED and final["item_ids"] == [carrier["id"]]
    assert store.item(carrier["id"])["text"] == entry["text"]
