
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import fire, schedule_port, scheduled, wait_runner
from src.cplugs.huddle.roles import ask, tags
from tests.python.cplugs.huddle.roles_rig import BASE
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import SLEEPER, World, add, store_of  # noqa: F401


@pytest.fixture
def world(app, monkeypatch, pasted):
    note(app, "ses_old", "12", 100.0)
    app.state.session_manager._boot_readopt_task = None
    return World(app, monkeypatch)


def ctx_of(app):
    return runtime.host_for(app).context("huddle", background=True)


def fire_item(world, item: int) -> str:
    return asyncio.run(fire.deliver(ctx_of(world.app), {"id": item, "list": "12", "title": "t", "text": "t"}))


def test_an_untagged_fire_still_goes_to_the_lists_pick(client, world, pasted):
    item = add(client)
    fire_item(world, item)
    assert pasted[-1][0] == "ses_old"


def test_a_tagged_fire_goes_to_its_agent_not_the_projects_session(client, world, pasted):
    item = add(client)
    tags.set_tag(store_of(world.app), item, "ses_other")
    fire_item(world, item)
    assert [t for t, _ in pasted] == ["ses_other"] and f"item {item}" in pasted[0][1]


def test_a_tagged_fire_wakes_an_asleep_agent_first(client, world, pasted):
    item = add(client)
    world.sleeper()
    tags.set_tag(store_of(world.app), item, SLEEPER)
    fire_item(world, item)
    assert world.woken == [SLEEPER] and pasted[-1][0] == SLEEPER


def test_a_gone_tag_sends_the_fire_to_the_lead_and_the_task_moves_to_it(client, world, pasted):
    item = add(client)
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).status_code == 200
    tags.set_tag(store_of(world.app), item, "ses_ghost")
    fire_item(world, item)
    assert pasted[-1][0] == "ses_new" and store_of(world.app).item(item)["tagged_session_key"] == ""


def test_a_gone_tag_with_no_lead_asks_joe_once_and_the_list_carries_the_fire(client, world, pasted):
    item = add(client)
    tags.set_tag(store_of(world.app), item, "ses_ghost")
    fire_item(world, item)
    fire_item(world, item)
    assert [t for t, _ in pasted] == ["ses_old", "ses_old"]
    with closing(store_of(world.app)._connect(False)) as conn:
        assert ask.has_open(conn, item, ask.SESSION_GONE)
        assert conn.execute("SELECT COUNT(*) FROM work_messages WHERE item_id = ? AND kind = 'question'", (item,)).fetchone()[0] == 1


def pings_of(client, item: int) -> dict:
    from tests.python.cplugs.huddle.test_task_manager_schedule import iso
    client.patch(f"/api/v1/cplugs/huddle/items/{item}", json={"fire_at": iso(3600)})
    body = client.get("/api/v1/cplugs/huddle/scheduled").json()
    return next(s for s in body["schedules"] if s["item"] == item)["pings"]


def test_pings_follow_the_tag_then_the_lead_then_the_list(client, world):
    plain, live, asleep, ghost = add(client, "a"), add(client, "b"), add(client, "c"), add(client, "d")
    world.sleeper()
    tags.set_tag(store_of(world.app), live, "ses_other")
    tags.set_tag(store_of(world.app), asleep, SLEEPER)
    tags.set_tag(store_of(world.app), ghost, "ses_ghost")
    assert pings_of(client, plain)["session"] == "ses_old"
    assert pings_of(client, live)["session"] == "ses_other"
    woken = pings_of(client, asleep)
    assert woken["session"] is None and woken["session_key"] == SLEEPER and world.woken == []
    assert pings_of(client, ghost)["session"] == "ses_old"
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).status_code == 200
    assert pings_of(client, ghost)["session"] == "ses_new"
    assert store_of(world.app).item(ghost)["tagged_session_key"] == "ses_ghost"


def test_the_row_icon_port_counts_a_tagged_fire_on_its_tag(client, world):
    plain, tagged = add(client, "a"), add(client, "b")
    tags.set_tag(store_of(world.app), tagged, "ses_other")
    for item in (plain, tagged):
        pings_of(client, item)
    infos = asyncio.run(world.app.state.session_manager.list_session_infos())
    got = asyncio.run(schedule_port.SchedulePort(ctx_of(world.app)).by_session(infos))
    assert {k: len(v) for k, v in got.items()} == {"ses_old": 1, "ses_other": 1}


def test_a_stale_wait_handback_is_told_to_the_tag_not_the_parker(client, world, pasted):
    item = add(client)
    told = client.post(f"{BASE}/send", json={"lists": ["12"]}).json()["results"][0]
    assert told["status"] == "sent"
    tags.set_tag(store_of(world.app), item, "ses_other")
    store = store_of(world.app)
    store.update(item, actor="claude", state="review")
    wait_runner.hand_back(store, item, "still waiting?", "wait_expired")
    asyncio.run(wait_runner.send_parker(ctx_of(world.app), {"set_by": "ses_old"}, "12", item))
    assert pasted[-1][0] == "ses_other"
