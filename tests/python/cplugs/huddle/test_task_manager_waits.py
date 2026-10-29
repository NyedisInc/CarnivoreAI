
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
import structlog

from src.cplugs.huddle import schedule, wait_runner, waits
from src.cplugs.huddle.answer_writer import AnswerWriter
from src.cplugs.huddle.roles import unstick
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.huddle.waits import WaitStore
from tests.python.cplugs.huddle.test_task_manager_lane import synthetic_v37
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, env  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_state_rungs import walk

ROUTE = "/api/v1/cplugs/huddle/items/{}/wait/resolve"
INSTALL = {"waiting_on": "the staging restart", "wait_kind": "install"}


def iso(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).astimezone().isoformat()


def park(store, item: int, *, by: str = "u-1", **extra) -> dict:
    return store.update(item, actor="claude", state="waiting", wait={**INSTALL, **extra}, wait_by=by)


def wait_row(store, item: int, status: str = "") -> dict:
    with closing(store._connect(False)) as conn:
        sql = "SELECT * FROM work_item_waits WHERE item_id = ?" + (" AND status = ?" if status else "") + " ORDER BY id DESC LIMIT 1"
        row = conn.execute(sql, (item, status) if status else (item,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else {}


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    from src.api.auth import limiter

    limiter.reset()


@pytest.fixture
def told(monkeypatch):
    seen: list = []

    async def tell(ctx, run, key, list_key):
        seen.append((key, list_key))
        return {"list": list_key, "status": "sent"}

    monkeypatch.setattr(unstick, "send_session", tell)
    return seen


def runner_at(env, hours: float) -> wait_runner.WaitRunner:
    return wait_runner.WaitRunner(env.ctx, clock=lambda: time.time() + hours * 3600)


def question_of(item: dict) -> dict:
    return [m for m in item["thread"] if m["kind"] == "question" and not m["answered"]][-1]



def test_deadline_is_the_expected_time_plus_half_again_and_never_less_than_fifteen_minutes():
    assert waits.deadline_for(0, 3600) == 5400
    assert waits.deadline_for(0, 86400) == 86400 + 43200
    assert waits.deadline_for(0, 600) == 600 + 900
    assert waits.deadline_for(1000, 1000 + 1800) == 2800 + 900


def test_an_agent_cannot_park_without_saying_what_and_the_owner_always_can(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "wait for it", actor="joe")["id"]
    ok, text = call(manager, "task_manager_update", {"item": item, "state": "waiting"})
    assert not ok and "waiting_on" in text and store.item(item)["state"] == "open"
    ok, text = call(manager, "task_manager_update", {"item": item, "state": "waiting", "waiting_on": "a restart"})
    assert not ok and "wait_kind" in text
    ok, text = call(manager, "task_manager_update", {"item": item, "state": "waiting", "waiting_on": "something", "wait_kind": "other"})
    assert not ok and "expect_by" in text
    ok, text = call(manager, "task_manager_update", {"item": item, "waiting_on": "a restart", "wait_kind": "install"})
    assert not ok and "only with state waiting" in text
    moved = store.update(item, actor="joe", state="waiting")
    assert moved["state"] == "waiting" and "wait" not in moved and wait_row(store, item) == {}


def test_waiting_on_the_owner_is_a_question_not_a_wait(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "needs a call", actor="joe")["id"]
    for who in ("Joe to answer", "the owner's ok"):
        ok, text = call(manager, "task_manager_update", {"item": item, "state": "waiting", "waiting_on": who, "wait_kind": "person"})
        assert not ok and "task_manager_ask" in text
    assert store.item(item)["state"] == "open"
    ok, answer = call(manager, "task_manager_update", {"item": item, "state": "waiting", "waiting_on": "joe runs the handoff script", "wait_kind": "install"})
    assert ok and answer["state"] == "waiting"


@pytest.mark.parametrize("kind,seconds", [("install", 3600), ("session", 3 * 3600), ("person", 86400), ("vendor", 86400)])
def test_a_wait_without_a_time_gets_the_default_of_its_kind(manager, kind, seconds):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    before = time.time()
    ok, answer = call(manager, "task_manager_update", {"item": item, "state": "waiting", "waiting_on": "alex's build", "wait_kind": kind})
    assert ok
    row = wait_row(store, item)
    assert abs(row["expect_by"] - (before + seconds)) < 5 and row["deadline"] == waits.deadline_for(row["set_at"], row["expect_by"])
    assert row["token_hash"] and answer["wait"]["expect_by"] == row["expect_by"]


def test_expect_by_must_be_iso_with_an_offset_in_the_future_and_within_30_days():
    now = time.time()
    for bad in ("tomorrow", "2099-01-01T00:00:00", iso(-60), iso(31 * 86400), "", None):
        with pytest.raises(TaskManagerInvalid):
            waits.parse_expect_by(bad, now)
    assert abs(waits.parse_expect_by(iso(7200), now) - (now + 7200)) < 2


def test_a_park_answer_carries_the_token_once_and_the_store_keeps_only_its_hash(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    ok, answer = call(manager, "task_manager_update", {"item": item, "state": "waiting", **INSTALL}, raw=True)
    token = answer["wait_callback"]["token"]
    assert len(token) >= 40 and "/wait/resolve" in answer["wait_callback"]["resolve"]
    with closing(store._connect(False)) as conn:
        dump = [tuple(r) for r in conn.execute("SELECT * FROM work_item_waits")]
        assert dump and token not in repr(dump) and any(hashlib.sha256(token.encode()).hexdigest() in row for row in dump)
        assert token not in repr([tuple(r) for r in conn.execute("SELECT * FROM work_messages")])
    assert "wait_callback" not in call(manager, "task_manager_tasks_list", {"item": item})[1]["item"]
    assert "token" not in repr(store.item(item))



def test_rung_46_is_additive_and_backfills_only_agent_parked_task_manager_waits_with_a_silent_day_and_a_half(tmp_path):
    path = synthetic_v37(tmp_path)
    walk(path, 45)
    with closing(sqlite3.connect(path)) as conn, conn:
        for item in range(1, 8):
            conn.execute("UPDATE items SET state = 'waiting' WHERE id = ?", (item,))
        conn.execute("UPDATE items SET lane = 'task_manager', swarm_ref = ''")
        conn.execute("INSERT INTO item_lineage (item_id, list_key, at, from_state, to_state, by) VALUES (1, 'all', 0, 'open', 'waiting', 'owner')")
        for item, by in ((1, "u-1"), (2, "owner"), (3, "carnivore"), (4, "u-1"), (5, "u-1"), (6, "u-1")):
            conn.execute("INSERT INTO item_lineage (item_id, list_key, at, from_state, to_state, by) VALUES (?, 'all', 1, 'open', 'waiting', ?)", (item, by))
        conn.execute("INSERT INTO blockers (item_id, kind, text, created_by, created_at) VALUES (4, 'install', 'x', 'u-1', 1)")
        conn.execute("UPDATE items SET swarm_ref = 'card:1' WHERE id = 5")
        conn.execute("UPDATE items SET lane = 'swarm' WHERE id = 6")
        before = [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")]
    walk(path, 46)
    now = time.time()
    with closing(sqlite3.connect(path)) as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM items ORDER BY id")] == before
        rows = conn.execute("SELECT item_id, legacy, set_at, deadline, status, token_hash FROM item_waits").fetchall()
    assert [(r[0], r[1], r[4], r[5]) for r in rows] == [(1, 1, "active", "")]
    assert abs(rows[0][2] - now) < 30 and abs(rows[0][3] - (now + 36 * 3600)) < 30


def test_a_legacy_wait_is_not_expired_at_once_and_is_silent_on_the_wire(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "old wait", actor="joe")["id"]
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET state = 'waiting' WHERE id = ?", (item,))
        conn.execute("INSERT INTO work_item_waits (item_id, set_at, expect_by, deadline, legacy) VALUES (?, ?, ?, ?, 1)",
                     (item, time.time(), time.time() + 86400, time.time() + 129600))
    assert WaitStore(store).due_expiries(time.time() + 3600) == [] and WaitStore(store).due_expiries(time.time() + 37 * 3600)[0]["item_id"] == item
    assert "wait" not in store.item(item)
    again = park(store, item)
    assert again["wait_token"] and again["wait"]["waiting_on"] == "the staging restart" and again["wait"]["extended"] == 0


def test_the_rungs_triggers_end_a_wait_with_its_token(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    park(store, item)
    store.update(item, actor="joe", state="review")
    row = wait_row(store, item)
    assert row["status"] == "settled" and row["token_hash"] == ""
    park(store, item)
    store.update(item, actor="joe", state="open")
    assert wait_row(store, item)["status"] == "ended" and wait_row(store, item)["token_hash"] == ""



def test_expiry_hands_the_task_back_open_with_the_challenge_and_tells_the_parker(client, env, told):  # noqa: F811
    item = env.add(client)["id"]
    first = park(env.store, item)
    assert first["state"] == "waiting" and first["wait"]["kind"] == "install"
    assert asyncio.run(runner_at(env, 0.5).expire_due()) == 0
    assert asyncio.run(runner_at(env, 2).expire_due()) == 1
    after = env.store.item(item)
    assert after["state"] == "open" and wait_row(env.store, item)["status"] == "expired" and wait_row(env.store, item)["token_hash"] == ""
    challenge = [m for m in after["thread"] if m["kind"] == "info" and m["author_key"] == "carnivore"]
    assert len(challenge) == 1 and "the staging restart" in challenge[0]["text"] and "extend_reason" in challenge[0]["text"] and "task_manager_ask" in challenge[0]["text"]
    assert told == [("u-1", "12")]
    assert asyncio.run(runner_at(env, 3).expire_due()) == 0


def test_one_extension_with_a_reason_then_a_second_is_refused_and_the_second_expiry_asks_the_owner_once(client, env, told):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item)
    asyncio.run(runner_at(env, 2).expire_due())
    with pytest.raises(TaskManagerInvalid, match="extend_reason"):
        park(env.store, item)
    extended = park(env.store, item, extend_reason="the install is queued behind another")
    assert extended["wait"]["extended"] == 1 and extended["wait"]["extend_reason"].startswith("the install") and extended["wait_token"]
    with pytest.raises(TaskManagerInvalid, match="already extended"):
        park(env.store, item, extend_reason="still")
    assert asyncio.run(runner_at(env, 5).expire_due()) == 1 and asyncio.run(runner_at(env, 6).expire_due()) == 0
    asked = env.store.item(item)
    assert asked["state"] == "waiting" and wait_row(env.store, item)["status"] == "escalated"
    questions = [m for m in asked["thread"] if m["kind"] == "question"]
    assert len(questions) == 1 and questions[0]["category"] == "wait_stuck" and "since" in questions[0]["text"]
    form = AnswerWriter(env.store).read(questions[0]["id"])
    assert [o["id"] for o in form["ask"]["questions"][0]["options"]] == ["handle", "drop", "check", "until"]
    with pytest.raises(TaskManagerInvalid, match="owner has been asked"):
        park(env.store, item, extend_reason="try anyway")


def test_extending_before_the_deadline_works_once_in_place_and_keeps_the_token(client, env):  # noqa: F811
    item = env.add(client)["id"]
    first = park(env.store, item)
    with pytest.raises(TaskManagerInvalid, match="extend_reason"):
        park(env.store, item, expect_by=iso(7200))
    again = park(env.store, item, expect_by=iso(7200), extend_reason="needs another hour")
    assert again["wait"]["extended"] == 1 and "wait_token" not in again
    assert waits.check_token(wait_row(env.store, item), first["wait_token"])
    assert env.store.update(item, actor="claude", state="waiting", wait={}, wait_by="u-1")["state"] == "waiting"


@pytest.mark.parametrize("choice,state", [("check", "open"), ("handle", "todo"), ("drop", "todo")])
def test_each_answer_to_the_wait_question_does_what_it_says(client, env, told, choice, state):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item)
    asyncio.run(runner_at(env, 2).expire_due())
    park(env.store, item, extend_reason="queued")
    asyncio.run(runner_at(env, 5).expire_due())
    question = question_of(env.store.item(item))
    posted = AnswerWriter(env.store).submit(question["id"], {"q1": {"choice": choice}})
    after = env.store.item(item)
    assert after["state"] == state and posted["carnivore"] == {"category": "wait_stuck", "choice": choice}
    assert wait_row(env.store, item)["status"] == "settled"
    if choice == "check":
        sent = asyncio.run(unstick.after_answer(env.ctx, wait_runner._run, {**posted, "item": after}))
        assert sent == {"list": "12", "status": "sent"} and ("u-1" in {k for k, _ in told} or told)



def test_a_good_token_clears_the_wait_without_the_owners_credentials_and_only_once(client, env, told, monkeypatch):  # noqa: F811
    item = env.add(client)["id"]
    token = park(env.store, item)["wait_token"]
    client.app.dependency_overrides.clear()
    bare = client.post(ROUTE.format(item), json={"token": token, "result": "cleared", "reason": "the script ran"})
    assert bare.status_code == 200 and bare.json() == {"ok": True, "item_id": item, "result": "cleared", "state": "open"}
    after = env.store.item(item)
    assert after["state"] == "open" and any(m["text"] == "cleared: the script ran" for m in after["thread"])
    assert told and wait_row(env.store, item)["status"] == "cleared"
    again = client.post(ROUTE.format(item), json={"token": token, "result": "cleared"})
    assert again.status_code == 403 and again.json()["detail"]["code"] == "task_manager_forbidden"


def test_failed_returns_the_task_open_with_the_reason(client, env, told):  # noqa: F811
    item = env.add(client)["id"]
    token = park(env.store, item)["wait_token"]
    done = client.post(ROUTE.format(item), json={"token": token, "result": "failed", "reason": "exit 3 at step 2"})
    assert done.status_code == 200 and env.store.item(item)["state"] == "open"
    assert any(m["text"] == "wait failed: exit 3 at step 2" for m in env.store.item(item)["thread"]) and wait_row(env.store, item)["status"] == "failed"


def test_a_wrong_missing_expired_or_ended_wait_token_is_refused_the_same_way(client, env, told):  # noqa: F811
    item, other = env.add(client)["id"], env.add(client)["id"]
    token = park(env.store, item)["wait_token"]
    other_token = park(env.store, other)["wait_token"]
    for body in ({"token": "nope", "result": "cleared"}, {"result": "cleared"}, {"token": other_token, "result": "cleared"}):
        refused = client.post(ROUTE.format(item), json=body)
        assert refused.status_code == 403, body
    assert client.post(ROUTE.format(item), json={"token": token, "result": "maybe"}).status_code == 400
    assert env.store.item(item)["state"] == "waiting"
    asyncio.run(runner_at(env, 2).expire_due())
    assert client.post(ROUTE.format(item), json={"token": token, "result": "cleared"}).status_code == 403
    env.store.update(other, actor="joe", state="review")
    assert client.post(ROUTE.format(other), json={"token": other_token, "result": "cleared"}).status_code == 403
    assert client.post(ROUTE.format(99999), json={"token": token, "result": "cleared"}).status_code == 403


def test_the_apps_own_auth_works_without_a_token_and_the_mcp_tool_is_the_same_callback(client, env, manager, told, monkeypatch):  # noqa: F811
    from src.cplugs.huddle import routes_wait

    item = env.add(client)["id"]
    park(env.store, item)

    async def owner(request):
        return True

    monkeypatch.setattr(routes_wait, "has_valid_bearer", owner)
    assert client.post(ROUTE.format(item), json={"result": "cleared"}).status_code == 200

    mine = huddle_store(manager)
    parked = mine.add("all", "build", actor="joe")["id"]
    ok, _ = call(manager, "task_manager_update", {"item": parked, "state": "waiting", **INSTALL})
    ok, answer = call(manager, "task_manager_wait_update", {"item": parked, "result": "failed", "reason": "build broke"})
    assert ok and answer["state"] == "open" and mine.item(parked)["state"] == "open"
    ok, text = call(manager, "task_manager_wait_update", {"item": parked, "result": "cleared"})
    assert not ok and "no live wait" in text


def test_the_token_never_reaches_a_log(client, env, manager, told, caplog, capsys, default_structlog):  # noqa: F811
    item = env.add(client)["id"]
    with structlog.testing.capture_logs() as captured:
        caplog.set_level("DEBUG")
        token = park(env.store, item)["wait_token"]
        client.post(ROUTE.format(item), json={"token": "wrong-" + token, "result": "cleared"})
        client.post(ROUTE.format(item), json={"token": token, "result": "cleared"})
        mcp_item = huddle_store(manager).add("all", "m", actor="joe")["id"]
        ok, answer = call(manager, "task_manager_update", {"item": mcp_item, "state": "waiting", **INSTALL}, raw=True)
        mcp_token = answer["wait_callback"]["token"]
    out = capsys.readouterr()
    everything = repr(captured) + caplog.text + out.out + out.err
    assert token not in everything and mcp_token not in everything
    assert any(entry["event"] == "task_manager_wait_callback" for entry in captured) and any(entry["event"] == "task_manager_wait_callback_refused" for entry in captured)


def test_the_item_state_event_runs_on_the_scheduler_and_a_checkless_wait_stays_put(client, env, told, monkeypatch):  # noqa: F811
    from tests.python.cplugs.huddle.test_task_manager_wait_fixes import REAL_HANG_S, watch_wait_passes

    target, parked, plain = env.add(client)["id"], env.add(client)["id"], env.add(client)["id"]
    park(env.store, parked, wait_check={"kind": "item_state", "item": target, "state": "review"})
    park(env.store, plain)
    signals = watch_wait_passes(monkeypatch)

    async def scenario():
        schedule.start(env.ctx)
        try:
            await asyncio.wait_for(signals.first_pass(), REAL_HANG_S)
            assert env.store.item(parked)["state"] == "waiting"
            await asyncio.to_thread(lambda: env.store.update(target, actor="claude", state="review"))
            while env.store.item(parked)["state"] != "open":
                await asyncio.wait_for(signals.next_pass(), REAL_HANG_S)
        finally:
            schedule.stop()

    asyncio.run(scenario())
    cleared = env.store.item(parked)
    assert cleared["state"] == "open" and any(m["text"] == f"cleared: item {target} reached review" for m in cleared["thread"]) and told
    assert env.store.item(plain)["state"] == "waiting"
