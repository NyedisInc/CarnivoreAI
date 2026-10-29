
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.cplugs.huddle import fork as forks, lifecycle, rules
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerForbidden
from src.core.work.ladder import MIGRATIONS
from src.core.work.storage import WorkStorage
from src.cplugs.sdk import CplugStorage, StorageSpec
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

KEY = "key-a"


def working(store, text: str = "do it", list_key: str = "12") -> int:
    item = store.add(list_key, text, actor=JOE)
    store.mark_working(item["id"], KEY)
    return item["id"]


def claim_of(store, item_id: int):
    with closing(store._connect(False)) as conn:
        return tuple(conn.execute("SELECT claude_working, claude_working_by, owner_session_key FROM work_items WHERE id = ?", (item_id,)).fetchone())


@pytest.mark.parametrize("state", [rules.REVIEW, rules.WAITING, rules.TODO])
def test_an_agent_move_out_of_open_ends_the_claim_and_keeps_the_owner(manager, state):
    store = huddle_store(manager)
    item = working(store)
    store.update(item, actor=CLAUDE, state=state)
    assert claim_of(store, item) == (0, "", KEY)


def test_the_owners_tick_ends_the_claim(manager):
    store = huddle_store(manager)
    item = working(store)
    store.update(item, actor=JOE, approve=True)
    assert claim_of(store, item)[:2] == (0, "")


def test_a_fork_that_moves_its_parent_out_of_open_ends_the_parent_claim(manager):
    store = huddle_store(manager)
    item = working(store)
    store.fork(item, actor=CLAUDE, claimed_by=KEY, parent_state=rules.TODO)
    assert claim_of(store, item)[:2] == (0, "")


def test_a_raw_state_write_ends_the_claim_whoever_makes_it(manager):
    store = huddle_store(manager)
    item = working(store)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET state = 'waiting' WHERE id = ?", (item,))
    assert claim_of(store, item)[:2] == (0, "")


def test_a_move_to_open_keeps_the_claim(manager):
    store = huddle_store(manager)
    item = working(store)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET state = 'open' WHERE id = ?", (item,))
    assert claim_of(store, item)[:2] == (1, KEY)


def test_the_claim_check_can_go_red_when_the_trigger_is_gone(manager):
    store = huddle_store(manager)
    item = working(store)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("DROP TRIGGER work_items_claim_leaves_working")
        conn.execute("UPDATE work_items SET state = 'waiting' WHERE id = ?", (item,))
    assert claim_of(store, item)[:2] == (1, KEY)


def v42_file(folder: Path) -> Path:
    path = folder / "huddle.db"
    CplugStorage(folder, StorageSpec(db="huddle.db", migrations=MIGRATIONS[:42])).connect(True).close()
    with closing(sqlite3.connect(path)) as conn, conn:
        for n, (state, deleted) in enumerate([("review", 0), ("open", 0), ("waiting", 0), ("review", 1)]):
            conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq, claude_working, "
                         "claude_working_by, owner_session_key, deleted) VALUES ('12', ?, ?, 'joe', ?, 1, 1, 1, 1, 1, 'key-a', 'key-a', ?)",
                         (f"row {n}", n, state, deleted))
    return path


def test_rung_43_clears_claims_on_other_states_behind_a_verified_backup_and_keeps_ownership(tmp_path: Path):
    path = v42_file(tmp_path)
    WorkStorage(tmp_path).connect(True).close()
    with closing(sqlite3.connect(path)) as conn:
        rows = {r[0]: r[1:] for r in conn.execute("SELECT text, claude_working, claude_working_by, owner_session_key, deleted FROM items")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert rows["row 0"] == (0, "", "key-a", 0) and rows["row 2"] == (0, "", "key-a", 0)
    assert rows["row 1"] == (1, "key-a", "key-a", 0)
    assert rows["row 3"] == (1, "key-a", "key-a", 1)
    assert list(tmp_path.glob("huddle.db.pre-claim-rule-*")), "rung 43 takes a verified backup first"


def swarm_lane(store, item_id: int) -> None:
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET lane = 'swarm' WHERE id = ?", (item_id,))


def test_a_plain_session_cannot_claim_a_swarm_lane_task_through_the_tool(manager):
    store = huddle_store(manager)
    item = store.add("12", "swarm work", actor=JOE)["id"]
    swarm_lane(store, item)
    ok, text = call(manager, "task_manager_update", {"item": item, "state": "working"})
    assert not ok and "swarm_card_start" in text
    assert claim_of(store, item)[:2] == (0, "")


def test_a_swarm_agent_may_claim_its_own_lane_and_a_plain_session_still_claims_a_task_manager_task(manager):
    store = huddle_store(manager)
    item = store.add("12", "swarm work", actor=JOE)["id"]
    swarm_lane(store, item)
    with pytest.raises(TaskManagerForbidden):
        store.mark_working(item, KEY)
    store.mark_working(item, KEY, swarm_caller=True)
    assert claim_of(store, item)[:2] == (1, KEY)
    plain = store.add("12", "mine", actor=JOE)["id"]
    store.mark_working(plain, KEY)
    assert claim_of(store, plain)[:2] == (1, KEY)


def test_the_provisional_claim_and_a_fork_state_write_never_claim_a_swarm_lane_task(manager):
    store = huddle_store(manager)
    item = store.add("12", "swarm work", actor=JOE)["id"]
    swarm_lane(store, item)
    with closing(store._connect(True)) as conn, conn:
        assert lifecycle.claim(conn, item, KEY) is False
        forks.write_state(conn, item, forks.StateChange(rules.OPEN, False, True), seq=99, now=1.0, claimant=KEY)
    assert claim_of(store, item)[:2] == (0, "")
    plain = store.add("12", "mine", actor=JOE)["id"]
    with closing(store._connect(True)) as conn, conn:
        forks.write_state(conn, plain, forks.StateChange(rules.OPEN, False, True), seq=99, now=1.0, claimant=KEY)
    assert claim_of(store, plain)[:2] == (1, KEY)
