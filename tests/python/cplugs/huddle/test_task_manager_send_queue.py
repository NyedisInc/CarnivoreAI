
from __future__ import annotations

import asyncio
import time

import pytest

from src.cplugs.huddle import held, inbox_delivery, service, send_queue
from tests.python.cplugs.huddle.test_task_manager_inbox import queue as add_box_entry
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import Env

REAL_ARM = send_queue._arm
BASE = "/api/v1/cplugs/huddle"
SEND = f"{BASE}/send"
QUEUE = f"{BASE}/send-queue"


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def env(app, monkeypatch):
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "carnivore", "99": "other"})
    rig = Env(app, monkeypatch)
    rig.clock = Clock()
    send_queue.use_clock(rig.clock)
    monkeypatch.setattr(send_queue, "_arm", lambda ctx: None)
    rig.set_rows([row("ses_old", 12, minutes_ago=30), row("ses_new", 12, minutes_ago=1), row("ses_other", 99)])
    yield rig
    send_queue.reset()
    held.reset()


def change(client, key: str = "12", text: str = "x") -> dict:
    client.post(f"{BASE}/lists/{key}/items", json={"text": text})
    return client.post(SEND, json={"lists": [key], "queue": True}).json()


def flush_due(env) -> list:
    return asyncio.run(send_queue.flush_due(env.ctx))


def test_five_changes_in_three_seconds_send_one_tell_after_ten_quiet_seconds(client, app, env):
    note(app, "ses_old", "12", 100.0)
    for step in range(5):
        env.clock.now = 1000.0 + step * 0.75
        assert change(client)["results"] == [{"list": "12", "status": "queued"}]
    snap = client.get(QUEUE).json()
    assert (snap["count"], snap["first_at"], snap["reset_at"], snap["due_at"], snap["quiet_s"], snap["cap_s"]) == (5, 1000.0, 1003.0, 1013.0, 10.0, 45.0)
    assert env.pasted == []
    env.clock.now = 1012.9
    assert flush_due(env) == [] and env.pasted == []
    env.clock.now = 1013.0
    outcome = flush_due(env)
    assert [(o["list"], o["status"]) for o in outcome] == [("12", "sent")]
    assert len(env.pasted) == 1 and env.pasted[0][0] == "ses_old"
    assert "(list 12, since 0)" in env.pasted[0][1]
    assert client.get(QUEUE).json()["count"] == 0
    assert flush_due(env) == [] and len(env.pasted) == 1


def test_continuous_changes_still_send_at_the_cap(client, app, env):
    note(app, "ses_old", "12", 100.0)
    for step in range(5):
        env.clock.now = 1000.0 + step * 9
        change(client)
    env.clock.now = 1044.9
    assert flush_due(env) == []
    env.clock.now = 1045.0
    assert [o["status"] for o in flush_due(env)] == ["sent"] and len(env.pasted) == 1


def test_an_explicit_tell_sends_what_is_queued_for_the_same_session_first_and_not_other_sessions(client, app, env):
    note(app, "ses_old", "12", 100.0)
    note(app, "ses_old", "all", 100.0)
    change(client, "all", "shared")
    change(client, "99", "other")
    client.post(f"{BASE}/lists/12/items", json={"text": "mine"})
    told = client.post(SEND, json={"lists": ["12"]}).json()["results"]
    assert told[0]["status"] == "sent"
    assert [(s, "the shared swarm list" in t) for s, t in env.pasted] == [("ses_old", True), ("ses_old", False)]
    snap = client.get(QUEUE).json()
    assert list(snap["lists"]) == ["99"]


def test_a_list_queued_itself_is_superseded_by_its_own_immediate_tell(client, app, env):
    note(app, "ses_old", "12", 100.0)
    change(client)
    change(client)
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "sent"
    assert len(env.pasted) == 1 and client.get(QUEUE).json()["count"] == 0
    env.clock.now += 100
    assert flush_due(env) == [] and len(env.pasted) == 1


def test_an_add_box_entry_waits_in_the_send_queue_and_goes_out_when_it_releases(client, app, env):
    note(app, "ses_new", "all", 100.0)
    client.put(f"{BASE}/lists/12/inbox-prefs", json={"file_through_session": True})
    entry = add_box_entry(client, waits=True)["entry"]
    assert client.get(QUEUE).json()["lists"]["12"]["count"] == 1
    sent = next(s for s in client.get(f"{BASE}/sent").json()["sends"] if s["key"] == f"e:{entry['id']}")
    assert sent["tell"]["state"] == "queued" and sent["tell"]["due_at"] is not None
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx)) == 0 and env.pasted == []
    env.clock.now += 11
    assert [o["list"] for o in flush_due(env)] == ["12"]
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx)) == 1
    assert "task_manager_entry_import" in env.pasted[0][1]


def test_releasing_the_queue_wakes_the_scheduler_so_the_entry_is_not_left_to_the_next_poll(client, env, monkeypatch):
    woken = []
    monkeypatch.setattr(send_queue.triggers, "nudge", lambda: woken.append(True))
    add_box_entry(client, waits=True)
    woken.clear()
    env.clock.now += 11
    flush_due(env)
    assert woken == [True]


def test_an_add_box_entry_tell_sends_the_queue_for_its_session_first(client, app, env):
    note(app, "ses_new", "all", 100.0)
    client.put(f"{BASE}/lists/12/inbox-prefs", json={"file_through_session": True})
    change(client, "all", "shared")
    add_box_entry(client, waits=True)
    asyncio.run(send_queue.flush_now(env.ctx, ["12"]))
    assert asyncio.run(inbox_delivery.deliver_pass(env.ctx)) == 1
    assert [s for s, _t in env.pasted] == ["ses_new", "ses_new"]
    assert "the shared swarm list" in env.pasted[0][1] and "task_manager_entry_import" in env.pasted[1][1]
    assert client.get(QUEUE).json()["count"] == 0


def test_the_flush_route_sends_now_and_clears(client, app, env):
    note(app, "ses_old", "12", 100.0)
    change(client)
    body = client.post(f"{QUEUE}/flush", json={}).json()
    assert [(r["list"], r["status"]) for r in body["results"]] == [("12", "sent")]
    assert body["queue"]["count"] == 0 and len(env.pasted) == 1
    assert client.post(f"{QUEUE}/flush", json={}).json()["results"] == []
    change(client)
    change(client, "99")
    only = client.post(f"{QUEUE}/flush", json={"lists": ["99"]}).json()
    assert [r["list"] for r in only["results"]] == ["99"] and list(only["queue"]["lists"]) == ["12"]


def test_a_flushed_list_with_no_session_answers_its_candidates_and_keeps_the_items_untold(client, env):
    change(client)
    body = client.post(f"{QUEUE}/flush", json={}).json()["results"]
    assert body[0]["status"] == "no_session" and env.pasted == []
    assert next(r for r in client.get(f"{BASE}/lists").json()["lists"] if r["key"] == "12")["untold"] is True


def test_a_list_told_by_another_path_meanwhile_has_nothing_left_to_flush(client, app, env):
    note(app, "ses_old", "12", 100.0)
    change(client)
    client.post(f"{BASE}/lists/12/send", json={"target": "ses_old"})
    assert client.get(QUEUE).json()["count"] == 0 and len(env.pasted) == 1


def test_the_routes_need_auth(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as anonymous:
        assert anonymous.get(QUEUE).status_code in (401, 403)
        assert anonymous.post(f"{QUEUE}/flush", json={}).status_code in (401, 403)


def test_the_window_settings_are_clamped_and_the_cap_never_below_the_quiet():
    assert send_queue.window({}) == (10.0, 45.0)
    assert send_queue.window({"sendQuietSeconds": 0, "sendCapSeconds": 9999}) == (1.0, 600.0)
    assert send_queue.window({"sendQuietSeconds": 100, "sendCapSeconds": 5}) == (100.0, 100.0)
    assert send_queue.window({"sendQuietSeconds": "x", "sendCapSeconds": True}) == (10.0, 45.0)


def test_the_defaults_are_ten_quiet_and_forty_five_cap_and_the_manifest_says_the_same():
    import json
    from pathlib import Path

    assert (send_queue.DEFAULT_QUIET_S, send_queue.DEFAULT_CAP_S) == (10.0, 45.0)
    settings = json.loads((Path(send_queue.__file__).parent / "cplug.json").read_text())["settings_schema"]["fields"]
    assert (settings[send_queue.QUIET_SETTING]["default"], settings[send_queue.CAP_SETTING]["default"]) == (10, 45)


def test_a_stored_window_beats_the_defaults(env):
    env.ctx.settings_now = lambda: {"sendQuietSeconds": 3, "sendCapSeconds": 20}
    snap = send_queue.state(env.ctx)
    assert (snap["quiet_s"], snap["cap_s"]) == (3.0, 20.0)


def test_the_real_timer_sends_once_the_window_closes(client, app, env, monkeypatch):
    monkeypatch.setattr(send_queue, "_arm", REAL_ARM)
    send_queue.use_clock(time.time)
    note(app, "ses_old", "12", 100.0)
    env.ctx.settings_now = lambda: {"sendQuietSeconds": 1, "sendCapSeconds": 5}
    client.post(f"{BASE}/lists/12/items", json={"text": "x"})

    async def run() -> int:
        send_queue.queue_change(env.ctx, "12")
        await asyncio.sleep(0.4)
        before = len(env.pasted)
        await asyncio.sleep(1.4)
        return before

    before = asyncio.run(run())
    assert before == 0 and len(env.pasted) == 1


def test_a_restart_rearms_every_untold_list_on_the_normal_window(client, app, env):
    client.post(f"{BASE}/lists/12/items", json={"text": "x"})
    assert client.get(QUEUE).json()["count"] == 0
    assert asyncio.run(send_queue.rearm_untold(env.ctx)) == ["12"]
    snap = client.get(QUEUE).json()
    assert list(snap["lists"]) == ["12"] and snap["due_at"] == 1010.0
    assert asyncio.run(send_queue.rearm_untold(env.ctx)) == []
    assert client.get(QUEUE).json()["lists"]["12"]["count"] == 1
    env.clock.now = 1010.0
    note(app, "ses_old", "12", 100.0)
    assert [(o["list"], o["status"]) for o in flush_due(env)] == [("12", "sent")]


def test_a_rearm_that_cannot_read_the_store_logs_and_never_raises(env, monkeypatch):
    def broken(ctx):
        raise OSError("disk gone")

    monkeypatch.setattr(service, "store", broken)
    assert asyncio.run(send_queue.rearm_untold(env.ctx)) == []


def test_a_flush_never_asks_about_a_list_with_nothing_untold(client, env):
    send_queue.queue_change(env.ctx, "99")
    body = client.post(f"{QUEUE}/flush", json={}).json()["results"]
    assert body == [{"list": "99", "status": "nothing"}] and env.pasted == []


def test_a_queued_change_with_a_picked_session_stays_queued_and_goes_to_that_session(client, app, env):
    note(app, "ses_old", "12", 100.0)
    client.post(f"{BASE}/lists/12/items", json={"text": "x"})
    answer = client.post(SEND, json={"lists": ["12"], "queue": True, "targets": {"12": "ses_new"}}).json()
    assert answer["results"][0]["status"] == "queued" and env.pasted == []
    env.clock.now += 60
    assert [o["status"] for o in flush_due(env)] == ["sent"]
    assert [s for s, _t in env.pasted] == ["ses_new"]
