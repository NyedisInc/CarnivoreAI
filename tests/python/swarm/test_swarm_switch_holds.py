
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.swarm import switch


@pytest.fixture
def flip(monkeypatch):
    state = [True]
    monkeypatch.setattr(switch, "is_on", lambda: state[0])
    return state


def test_card_effects_skip_the_fact_and_the_teardown_while_off(flip, monkeypatch):
    from src.core.swarm.cards import effects

    ran: list = []

    class Port:
        async def card(self, card_id):
            return {"id": card_id, "title": "t"}

    async def record(app_state, card, effect):
        ran.append(effect["kind"])

    monkeypatch.setattr(effects.card_port, "get", lambda: Port())
    for kind in ("learn", "retire_validator", "post"):
        monkeypatch.setitem(effects._HANDLERS, kind, record)
    batch = [{"kind": k, "card_id": 4} for k in ("learn", "retire_validator", "post")]
    flip[0] = False
    asyncio.run(effects.run(None, batch))
    assert ran == ["post"], "off: no fact file and no teardown, a chat line still posts"
    flip[0] = True
    asyncio.run(effects.run(None, batch))
    assert ran == ["post", "learn", "retire_validator", "post"]


def test_a_validation_is_refused_before_any_stale_validator_is_retired(flip, monkeypatch):
    from src.core.swarm.cards import validate
    from src.cplugs.sdk.cards import CardRefused

    read: list = []
    torn: list = []

    async def card(card_id):
        read.append(card_id)
        raise CardRefused("not_a_card", "past the gate")

    async def teardown(app_state, agent):
        torn.append(agent["id"])

    async def run_db(work):
        return {"id": 9, "torn_down_at": None}

    monkeypatch.setattr(validate.ops, "_card", card)
    monkeypatch.setattr(validate.teardown, "run", teardown)
    monkeypatch.setattr(validate.body, "run_db", run_db)
    flip[0] = False
    with pytest.raises(CardRefused) as off:
        asyncio.run(validate.start(None, 5, by="auto_validate"))
    assert off.value.code == "swarm_off" and read == []
    asyncio.run(validate.retire_now(None, 9))
    assert torn == [], "off: a validator is never torn down"
    flip[0] = True
    with pytest.raises(CardRefused) as on:
        asyncio.run(validate.start(None, 5, by="auto_validate"))
    assert on.value.code == "not_a_card" and read == [5]
    asyncio.run(validate.retire_now(None, 9))
    assert torn == [9]


@pytest.fixture
def datastore(tmp_path, monkeypatch):
    from src.config import settings
    from src.core import db

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    with closing(sqlite3.connect(str(db.db_path_for(tmp_path)))) as conn:
        conn.executescript(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT);"
            "CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, session_row_id INTEGER, torn_down_at TEXT);"
            "INSERT INTO sessions VALUES (1, 'plain-uuid'), (2, 'body-uuid'), (3, 'gone-uuid');"
            "INSERT INTO swarm_agents VALUES (7, 2, NULL), (8, 3, '2026-10-01');")
        conn.commit()


def test_the_switch_names_only_live_swarm_bodies_and_only_while_off(flip, datastore):
    assert switch.held_row_ids() == set() and switch.guards_body("body-uuid") is False
    flip[0] = False
    assert switch.held_row_ids() == {2}
    assert switch.guards_body("body-uuid") is True
    assert switch.guards_body("plain-uuid") is False and switch.guards_body("gone-uuid") is False


def test_a_recreate_and_a_reboot_reopen_refuse_a_held_body(flip, datastore, monkeypatch):
    from src.api import recreate_action, recreate_routes, restore_offer_routes

    gathered: list = []

    def gather(session_uuid, *args, **kwargs):
        gathered.append(session_uuid)
        raise HTTPException(status_code=404, detail="past the gate")

    monkeypatch.setattr(recreate_routes, "_gather", gather)
    flip[0] = False
    with pytest.raises(HTTPException) as off:
        asyncio.run(recreate_action.recreate_by_uuid("body-uuid", "claude", get_manager=lambda: None))
    assert off.value.status_code == 409 and off.value.detail["code"] == "swarm_off" and gathered == []
    item = {"session_uuid": "body-uuid", "kind": "agent", "title": "x"}
    reopened = asyncio.run(restore_offer_routes._reopen_one(None, item, "claude"))
    assert reopened["outcome"] == "refused" and reopened["detail"] == switch.OFF_MESSAGE and gathered == []
    with pytest.raises(HTTPException) as plain:
        asyncio.run(recreate_action.recreate_by_uuid("plain-uuid", "claude", get_manager=lambda: None))
    assert plain.value.status_code == 404, "a plain session is never held"
    flip[0] = True
    with pytest.raises(HTTPException) as on:
        asyncio.run(recreate_action.recreate_by_uuid("body-uuid", "claude", get_manager=lambda: None))
    assert on.value.status_code == 404 and gathered == ["plain-uuid", "body-uuid"]


def test_the_reboot_offer_leaves_held_bodies_out(flip, datastore):
    from src.core.session_journal_task import _offerable_rows

    rows = [{"id": 1}, {"id": 2}]
    assert _offerable_rows(rows) == rows
    flip[0] = False
    assert _offerable_rows(rows) == [{"id": 1}]


def test_the_restart_ladder_holds_a_swarm_body_but_its_preview_renders(flip, monkeypatch):
    from src.api.session_attach_routes import respawn_or_http
    from src.core.swarm import launch

    monkeypatch.setattr(launch, "swarm_launch_args", lambda row_id, conn=None: ["--agent", "a"] if row_id == 2 else [])
    flip[0] = False
    with pytest.raises(switch.BodyHeld):
        launch.with_swarm_args(2, ["--resume", "u"], hold=True)
    assert launch.with_swarm_args(2, ["--resume", "u"]) == ["--agent", "a", "--resume", "u"], "the preview only renders"
    assert launch.with_swarm_args(1, ["--resume", "u"], hold=True) == ["--resume", "u"], "a plain row is never held"

    class Manager:
        async def respawn_session(self, name, **kwargs):
            launch.with_swarm_args(2, None, hold=True)

    with pytest.raises(HTTPException) as off:
        asyncio.run(respawn_or_http(Manager(), "carnivore_a"))
    assert off.value.status_code == 409 and off.value.detail["code"] == "swarm_off"
    flip[0] = True
    assert launch.with_swarm_args(2, ["--resume", "u"], hold=True) == ["--agent", "a", "--resume", "u"]


def test_a_sleep_while_off_rebuilds_the_search_rows_but_writes_no_index_block(flip, monkeypatch):
    from src.core.swarm import body, fact_index

    seen: list = []

    async def run_db(work):
        return work(None)

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(fact_index, "refresh_agent", lambda conn, agent, write_block=True: seen.append(write_block))
    flip[0] = False
    asyncio.run(body._refresh_index({"id": 3}))
    flip[0] = True
    asyncio.run(body._refresh_index({"id": 3}))
    assert seen == [False, True]


def test_a_death_found_while_off_is_buried_without_a_card(flip, monkeypatch):
    from src.core.swarm import alerts, body, body_death, delivery, watch

    cards: list = []
    answers: list = []

    async def run_db(work):
        return answers.pop(0)

    async def nothing(*args, **kwargs):
        return None

    async def dead_card(agent, wake_id):
        cards.append(wake_id)

    monkeypatch.setattr(body, "run_db", run_db)
    for module, name in ((delivery, "wake_ended"), (body_death, "_close_dialog_cards"), (body, "_refresh_index"), (body, "_commit")):
        monkeypatch.setattr(module, name, nothing)
    monkeypatch.setattr(watch, "forget", lambda name: None)
    monkeypatch.setattr(alerts, "post_dead_card", dead_card)
    agent = {"id": 4, "state": "awake", "session_row_id": 2, "host_key": "peer-1", "thread_key": "agent:4"}

    def bury() -> bool:
        answers[:] = [({"lifecycle": "stopped", "tmux_name": "x"}, {"id": 11, "tmux_name": "x"}), True, True, True]
        return asyncio.run(body_death.detect(SimpleNamespace(), agent))

    flip[0] = False
    assert bury() is True and cards == [], "off: buried, no new card"
    flip[0] = True
    assert bury() is True and cards == [11]


def test_a_remote_body_keeps_its_task_manager_tools_and_loses_only_the_swarm_family(flip, monkeypatch):
    from src.api import federation_pack_span_routes as span
    from src.core.pack.span import proxy_server

    ran: list = []

    async def run(app, peer, call):
        ran.append(call.tool)
        return {"result": "ok"}

    monkeypatch.setattr(proxy_server, "run", run)
    monkeypatch.setattr(span, "_peer", lambda principal: "peer-1")
    request = SimpleNamespace(app=None)

    def call(tool: str):
        return proxy_server.ProxyCall(tool=tool, body_session_uuid="body-uuid", project_uid="project-1", home_agent_id=7)

    flip[0] = False
    for tool in ("huddle_progress", "task_manager_reply"):
        assert asyncio.run(span.swarm_proxy(call(tool), request, None)) == {"result": "ok"}
    with pytest.raises(HTTPException) as off:
        asyncio.run(span.swarm_proxy(call("swarm_report"), request, None))
    assert off.value.status_code == 409 and off.value.detail["code"] == "swarm_off"
    assert ran == ["huddle_progress", "task_manager_reply"]
    flip[0] = True
    asyncio.run(span.swarm_proxy(call("swarm_report"), request, None))
    assert ran[-1] == "swarm_report"


def test_a_remote_bodys_memory_writeback_lands_while_off_so_its_sleep_finishes(flip, monkeypatch):
    from src.api import federation_pack_span_routes as span
    from src.core.pack.span import proxy_server

    applied: list = []

    async def apply(install, agent_id, files, label):
        applied.append((install, agent_id, len(files)))
        return {"applied": ["a.md"], "kept_both": []}

    class Conn:
        def close(self) -> None:
            return None

    monkeypatch.setattr(proxy_server, "apply_writeback", apply)
    monkeypatch.setattr(span, "_peer", lambda principal: "peer-1")
    monkeypatch.setattr(span.peer_auth, "open_db", lambda: Conn())
    monkeypatch.setattr(span.peer_hosts, "get", lambda conn, install: None)
    flip[0] = False
    body = span.WritebackBody(home_agent_id=7, files=[{"path": "a.md"}])
    assert asyncio.run(span.memory_writeback(body, None)) == {"applied": ["a.md"], "kept_both": []}
    assert applied == [("peer-1", 7, 1)]
