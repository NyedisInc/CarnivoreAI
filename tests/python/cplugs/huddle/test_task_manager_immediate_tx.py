
from __future__ import annotations

import ast
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import rules, status_lines, waits
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerError, TaskManagerForbidden, TaskManagerInvalid, TaskManagerStale
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.sdk import work
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import iso

HUDDLE = Path(__file__).resolve().parents[4] / "src" / "cplugs" / "huddle"
PAUSE_SECONDS = 10


@pytest.fixture
def store(app) -> TaskManagerStore:  # noqa: F811
    return TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)


def race(monkeypatch, first: Callable[[], Any], second: Callable[[], Any], *, pause_at: Tuple[Any, str] = (work, "next_seq"),
         after: bool = False) -> Dict[str, Any]:
    paused, resume = threading.Event(), threading.Event()
    owner, attribute = pause_at
    real = getattr(owner, attribute)

    def wait_here() -> None:
        if threading.current_thread().name == "first" and not paused.is_set():
            paused.set()
            resume.wait(PAUSE_SECONDS)

    def pausing(*args: Any, **kwargs: Any) -> Any:
        if not after:
            wait_here()
        result = real(*args, **kwargs)
        if after:
            wait_here()
        return result

    monkeypatch.setattr(owner, attribute, pausing)
    out: Dict[str, Any] = {}

    def run(name: str, fn: Callable[[], Any]) -> None:
        try:
            out[name] = fn()
        except (TaskManagerError, sqlite3.Error) as exc:
            out[name] = exc

    one = threading.Thread(target=run, args=("first", first), name="first")
    one.start()
    assert paused.wait(PAUSE_SECONDS), "the first writer never reached its pause point"
    two = threading.Thread(target=run, args=("second", second), name="second")
    two.start()
    two.join(0.5)
    resume.set()
    one.join(PAUSE_SECONDS)
    two.join(PAUSE_SECONDS)
    assert not one.is_alive() and not two.is_alive()
    return out


def rows(store: TaskManagerStore, sql: str, *args: Any) -> List[tuple]:
    with closing(store._connect(False)) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def test_two_updates_from_one_revision_queue_and_the_second_is_stale(store, monkeypatch):
    item = store.add("all", "plain", actor=JOE)["id"]
    revision = store.item(item)["revision"]
    out = race(monkeypatch, lambda: store.update(item, actor=JOE, text="one", expected_revision=revision),
               lambda: store.update(item, actor=JOE, text="two", expected_revision=revision))
    assert isinstance(out["first"], dict) and isinstance(out["second"], TaskManagerStale), out
    assert store.item(item)["text"] == "one"


def test_two_moves_into_one_list_take_two_places(store, monkeypatch):
    one, two = (store.add("all", text, actor=JOE)["id"] for text in ("a", "b"))
    race(monkeypatch, lambda: store.move(one, "12", actor=JOE), lambda: store.move(two, "12", actor=JOE))
    places = sorted(r[0] for r in rows(store, "SELECT position FROM work_items WHERE id IN (?, ?)", one, two))
    assert places == [0, 1], places


def test_a_post_racing_a_delete_leaves_no_message_on_the_deleted_item(store, monkeypatch):
    item = store.add("all", "going away", actor=JOE)["id"]
    out = race(monkeypatch, lambda: store.post(item, "late word", actor=CLAUDE), lambda: store.delete(item, actor=JOE))
    assert not isinstance(out["second"], sqlite3.Error), out
    assert rows(store, "SELECT COUNT(*) FROM work_messages WHERE item_id = ?", item) == [(0,)]


def test_two_mark_answered_calls_write_one_status_line(store, monkeypatch):
    item = store.add("all", "which one?", actor=JOE)["id"]
    store.post(item, "A or B?", actor=CLAUDE, kind=rules.QUESTION)
    race(monkeypatch, lambda: store.mark_answered(item, actor=JOE), lambda: store.mark_answered(item, actor=JOE))
    lines = rows(store, "SELECT COUNT(*) FROM work_messages WHERE item_id = ? AND category = ?", item, status_lines.CATEGORY)
    assert lines == [(1,)], lines


def test_run_now_racing_a_tick_is_refused_once_the_tick_lands(store, monkeypatch):
    item = store.add("all", "ship it", actor=JOE)["id"]
    out = race(monkeypatch, lambda: store.update(item, actor=JOE, state=rules.DONE), lambda: store.claim_now(item))
    assert store.item(item)["state"] == rules.DONE
    assert isinstance(out["second"], TaskManagerInvalid) and "not sent" in str(out["second"]), out


def test_two_concurrent_claim_passes_fire_a_trigger_once(store, monkeypatch):
    item = store.add("12", "remind me", actor=JOE, fire_at=iso(3600))["id"]
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_item_triggers SET fire_at = fire_at - 7200 WHERE item_id = ?", (item,))
    out = race(monkeypatch, store.claim_due_triggers, store.claim_due_triggers)
    fired = [claimed["id"] for result in out.values() for claimed in result]
    assert fired == [item], out


def test_a_working_claim_racing_a_tick_never_claims_the_ticked_item(store, monkeypatch):
    item = store.add("all", "ship it", actor=JOE)["id"]
    out = race(monkeypatch, lambda: store.mark_working(item, "session-key"), lambda: store.update(item, actor=JOE, state=rules.DONE),
               pause_at=(TaskManagerStore, "item"), after=True)
    assert store.item(item)["state"] == rules.DONE
    assert rows(store, "SELECT claude_working FROM work_items WHERE id = ?", item) == [(0,)], out
    assert isinstance(out["first"], TaskManagerForbidden) and "ticked" in str(out["first"]), out
    assert rows(store, "SELECT COUNT(*) FROM work_messages WHERE item_id = ? AND category = ? AND text LIKE '%working%'", item, status_lines.CATEGORY) == [(0,)]


def due_check(store: TaskManagerStore, item: int) -> int:
    with closing(store._connect(True)) as conn, conn:
        return conn.execute("INSERT INTO work_item_waits (item_id, set_at, expect_by, deadline, check_kind, check_json, check_next_at) "
                            "VALUES (?, 1, 2, 9999999999, 'file_exists', '{}', 1)", (item,)).lastrowid


def test_two_passes_claiming_one_due_check_run_it_once(store, monkeypatch):
    item = store.add("all", "waiting on a file", actor=JOE)["id"]
    wait = due_check(store, item)
    claim = lambda: waits.WaitStore(store).claim_due_checks(100.0, 10)  # noqa: E731
    out = race(monkeypatch, claim, claim, pause_at=(waits, "backoff_s"))
    claimed = [row["id"] for result in out.values() for row in result]
    assert claimed == [wait], out
    assert rows(store, "SELECT check_runs FROM work_item_waits WHERE id = ?", wait) == [(1,)]


def holds_write_lock(store: TaskManagerStore):
    conn = store._connect(True)
    conn.execute("BEGIN IMMEDIATE")
    return conn


@pytest.mark.parametrize("name", ["claim_due_checks", "record_claude_read"])
def test_a_pass_that_finds_nothing_to_do_takes_no_write_lock(store, name):
    item = store.add("all", "quiet", actor=JOE)["id"]
    work_item = store.item(item)
    store.record_claude_read([(item, work_item["seq"])])
    calls = {"claim_due_checks": lambda: waits.WaitStore(store).claim_due_checks(100.0, 10),
             "record_claude_read": lambda: store.record_claude_read([(item, work_item["seq"])])}
    done = threading.Event()
    blocker = holds_write_lock(store)
    try:
        worker = threading.Thread(target=lambda: (calls[name](), done.set()), daemon=True)
        worker.start()
        finished = done.wait(3)
    finally:
        blocker.rollback()
        blocker.close()
    assert finished, f"{name} waited for the write lock with nothing to write"


READ_CHECK_WRITE = {
    "store.py": ["mark_seen", "add", "fork", "update", "tick_review_check", "retire_swarm_ref", "delete", "move", "remove_completed", "reorder",
                 "note_system", "stamp_from_project", "mark_answered", "post", "accept_schedule"],
    "store_triggers.py": ["claim_now", "record_trigger_error", "record_wake_target"],
    "store_claims.py": ["record_claude_read", "sweep_read_claims", "sweep_stale_dots", "sweep_read_owners", "release_conversation_claims",
                        "mark_sent_by_swarm_ref"],
    "groups.py": ["create", "update", "fold_many", "remove", "set_group"],
    "closure_undo.py": ["undo_completion", "cancel_task"],
    "answer_writer.py": ["submit"],
    "blockers.py": ["clear_hold"],
    "inbox_store.py": ["mark_stuck", "claim", "link_item"],
    "nudge_store.py": ["record_nudges"],
    "roles/store.py": ["set_dnd", "take_if_vacant"],
    "roles/tags.py": ["set_tag", "take_over"],
}
LOCKING = ("._immediate()", "work.write_tx(", "BEGIN IMMEDIATE")


def functions_named(path: Path, name: str) -> List[str]:
    text = path.read_text()
    return [ast.get_source_segment(text, node) or "" for node in ast.walk(ast.parse(text))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]


@pytest.mark.parametrize("file,name", [(f, n) for f, names in READ_CHECK_WRITE.items() for n in names])
def test_every_read_check_write_method_takes_the_write_lock_first(file, name):
    found = functions_named(HUDDLE / file, name)
    assert len(found) == 1, f"{file}::{name} found {len(found)} times: name it uniquely or fix the list"
    assert any(marker in found[0] for marker in LOCKING), f"{file}::{name} reads before it holds the write lock"
    assert "_connect(True)) as conn, conn" not in found[0], f"{file}::{name} still opens a deferred write transaction"


GUARDED_UPDATE = [
    ("store_claims.py", "mark_working", "state NOT IN"),
    ("waits.py", "claim_due_checks", "AND check_next_at = ?"),
]


@pytest.mark.parametrize("file,name,guard", GUARDED_UPDATE)
def test_a_guarded_update_writer_keeps_its_guard(file, name, guard):
    found = functions_named(HUDDLE / file, name)
    assert len(found) == 1, f"{file}::{name} found {len(found)} times: name it uniquely or fix the list"
    assert guard in found[0], f"{file}::{name} lost its guard {guard!r}"
