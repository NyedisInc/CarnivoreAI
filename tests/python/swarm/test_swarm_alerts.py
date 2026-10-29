
from __future__ import annotations

import json
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pa_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pa_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.config import settings
from src.core import resource_push
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.notifications import contracts
from src.core.swarm import activity, alerts, body, delivery, facade, push, spawn, store, thread_port, views


class FakeInner:

    def __init__(self):
        self.cards = []

    async def post_card(self, thread_key, kind, title, text, swarm_ref):
        self.cards.append({"id": len(self.cards) + 1, "thread_key": thread_key, "kind": kind, "swarm_ref": swarm_ref,
                           "title": title, "text": text, "closed": False})
        return len(self.cards)

    async def open_cards(self):
        return [{k: c[k] for k in ("id", "thread_key", "kind", "swarm_ref", "title", "text")} for c in self.cards if not c["closed"]]

    async def settle_cards(self, swarm_ref, *, prefix=False, resolve=False, **kw):
        for c in self.cards:
            if c["swarm_ref"] == swarm_ref or (prefix and c["swarm_ref"].startswith(swarm_ref)):
                c["closed"] = c["closed"] or resolve

    async def close_open_cards(self, thread_key, prefix): ...


@pytest.fixture()
def world(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"config_version": 5, "projects": []}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        a = store.create_agent(conn, slug="loki", rank="feature", job="j", display_name="Loki", repo_dir=str(tmp_path), effort="high")
        b = store.create_agent(conn, slug="hosta", rank="feature", job="j", display_name="Hosta", repo_dir=str(tmp_path), effort="high")
    inner = FakeInner()
    thread_port.register(alerts.AlertingPort(inner))
    sent, pushed = [], []
    monkeypatch.setattr(contracts, "emit", sent.append)
    monkeypatch.setattr(resource_push, "notify", pushed.append)
    monkeypatch.setattr(spawn, "parent_agent", lambda view, caller: _agent(a))
    alerts.LIMITS.reset()
    activity.clear()

    class Manager:
        async def list_session_infos(self):
            return []

    app = FastAPI()
    app.include_router(swarm_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = Manager()
    yield SimpleNamespace(app=app, manager=app.state.session_manager, inner=inner, sent=sent, pushed=pushed, a=a, b=b, state=tmp_path)
    thread_port.register(None)
    settings._auth_config_cache = None


async def _agent(row):
    return row


async def roster(w):
    return {a["id"]: a for a in (await views.roster(w.manager))["agents"]}


@pytest.mark.asyncio
async def test_roster_fields_and_null_fallbacks(world):
    got = await roster(world)
    loki = got[world.a["id"]]
    assert loki["character_seed"] == world.a["character_seed"] and 1 <= loki["color_slot"] <= 8
    assert loki["alert"] is None and loki["activity"] is None and loki["question_waiting"] is False
    assert {"project_id", "company_id", "persona", "alert_reason", "activity_at", "talking_with"} <= set(loki)
    old = views.summarize({**world.a, "character_seed": None, "color_slot": None, "session_row_id": None}, {})
    assert old["character_seed"] > 0 and 1 <= old["color_slot"] <= 8 and old == views.summarize(
        {**world.a, "character_seed": None, "color_slot": None, "session_row_id": None}, {})
    assert (await views.roster(world.manager))["threads_ready"] is True


@pytest.mark.asyncio
async def test_roster_carries_the_latest_recorded_placement_reason_and_never_invents_one(world):
    from src.core.pack.placement import ddl as placement_ddl

    def seed(conn):
        placement_ddl.apply_pack_placement(conn)
        for reason in ("first pick", "most headroom after its reserve"):
            conn.execute("INSERT INTO pack_placements (agent_id, workload_json, chosen_install_id, mode, reason, candidates_json, created_at) "
                         "VALUES (?, '{}', 'peer-1', 'stats', ?, '[]', 1.0)", (world.a["id"], reason))
        conn.commit()

    await body.run_db(seed)
    got = await roster(world)
    assert got[world.a["id"]]["placement_reason"] == "most headroom after its reserve"
    assert all(a["placement_reason"] is None for i, a in got.items() if i != world.a["id"])


@pytest.mark.asyncio
async def test_threads_ready_false_without_a_port(world):
    thread_port.register(None)
    assert (await views.roster(world.manager))["threads_ready"] is False


def test_the_immediate_prefixes_are_the_ones_the_cards_carry():
    assert body.WAKE_REFUSED_PREFIX in alerts.IMMEDIATE_PREFIXES and body.WAKE_FAILED_PREFIX in alerts.IMMEDIATE_PREFIXES
    assert delivery.STUCK_PREFIX in alerts.IMMEDIATE_PREFIXES


@pytest.mark.asyncio
async def test_rungs_from_open_cards_and_one_push_across_two_reads(world):
    port, key = thread_port.get(), world.a["thread_key"]
    await port.post_card(key, "done", "report", "finished", "report:1")
    assert (await roster(world))[world.a["id"]]["alert"] == "routine"
    await port.post_card(key, "waiting", "naming family", "family: x", "naming:1")
    assert (await roster(world))[world.a["id"]]["alert"] == "priority"
    assert world.sent == []
    await port.post_card(key, "info", "wake failed", "boom", f"{body.WAKE_FAILED_PREFIX}{world.a['id']}:4")
    for _ in range(2):
        got = (await roster(world))[world.a["id"]]
    assert got["alert"] == "immediate" and got["alert_reason"] == "wake failed"
    assert [e.type_id for e in world.sent] == ["swarm.alert"] and world.sent[0].session_ref == "Loki"
    assert (await roster(world))[world.b["id"]]["alert"] is None


async def _post(world, ref):
    return await thread_port.get().post_card(world.a["thread_key"], "info", "needs you now", "disk full, see https://evil.example/pay?token=abc", ref)


@pytest.mark.asyncio
async def test_a_flash_card_is_one_text_and_the_reason_never_reaches_the_outside_copy(world):
    await _post(world, f"{alerts.FLASH_REF}{world.a['id']}:aa")
    assert (await roster(world))[world.a["id"]]["alert"] == "flash"
    assert [e.type_id for e in world.sent] == ["swarm.flash"]
    for event in world.sent:
        assert event.details is None and "evil.example" not in f"{event.title} {event.session_ref} {event.instance_key}"


@pytest.mark.asyncio
async def test_immediate_alert_pushes_are_limited(world):
    for n in range(3):
        await _post(world, f"{alerts.IMMEDIATE_REF}{world.a['id']}:{n}")
    assert [e.type_id for e in world.sent] == ["swarm.alert"]


@pytest.mark.asyncio
async def test_deciding_the_alert_card_clears_the_rung_and_names_the_roster(world):
    await _post(world, f"{alerts.FLASH_REF}{world.a['id']}:bb")
    plugin = facade.SwarmFacade(world.state, lambda: [], app_state=SimpleNamespace())
    await plugin.card_decided(world.inner.cards[0]["swarm_ref"], "approve", "", "huddle:msg:1")
    assert (await roster(world))[world.a["id"]]["alert"] is None
    world.pushed.clear()
    plugin.thread_changed(world.a["thread_key"])
    plugin.thread_changed("not-a-swarm-thread")
    assert world.pushed == ["swarm_roster"]


@pytest.mark.asyncio
async def test_activity_marks(world, monkeypatch):
    from src.core.crosstalk import store as crosstalk_store

    monkeypatch.setattr(push, "agent_ids_for_keys", lambda keys: [world.a["id"], world.b["id"]])
    world.pushed.clear()
    crosstalk_store._notify_swarm("k1", "k2")
    got = await roster(world)
    assert got[world.a["id"]]["activity"] == "talking" and got[world.a["id"]]["talking_with"] == world.b["id"]
    assert got[world.b["id"]]["talking_with"] == world.a["id"] and "swarm_roster" in world.pushed
    activity.mark(world.a["id"], "done")
    assert (await roster(world))[world.a["id"]]["activity"] == "done"
    assert activity.current(world.a["id"], now=activity.current(world.a["id"])["activity_at"] + 9)["activity"] is None


@pytest.mark.asyncio
async def test_color_patch_accepts_1_and_8_and_refuses_0_and_9(world):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=world.app), base_url="http://t/api/v1") as c:
        assert (await roster(world))[world.a["id"]]["color_chosen"] is False
        for slot in (1, 8):
            done = await c.patch(f"/swarm/agents/{world.a['id']}", json={"color_slot": slot})
            assert done.status_code == 200 and done.json()["color_slot"] == slot and done.json()["color_chosen"] is True
        for slot in (0, 9):
            assert (await c.patch(f"/swarm/agents/{world.a['id']}", json={"color_slot": slot})).status_code == 422
        assert (await c.patch("/swarm/agents/99", json={"color_slot": 2})).status_code == 404
        assert "swarm_roster" in world.pushed


@pytest.mark.asyncio
async def test_look_patch_sets_and_clears_color_shape_and_background(world):
    url = f"/swarm/agents/{world.a['id']}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=world.app), base_url="http://t/api/v1") as c:
        got = (await c.patch(url, json={"shape": "hexagon", "tile_bg": 3, "color_slot": 5})).json()
        assert (got["shape"], got["tile_bg"], got["color_slot"], got["color_chosen"]) == ("hexagon", 3, 5, True)
        got = (await c.patch(url, json={"color_slot": None})).json()
        assert (got["shape"], got["tile_bg"], got["color_chosen"]) == ("hexagon", 3, False)
        got = (await c.patch(url, json={"shape": None, "tile_bg": None})).json()
        assert (got["shape"], got["tile_bg"]) == (None, None)
        assert (await roster(world))[world.a["id"]]["shape"] is None
        for bad in ({"shape": "blob"}, {"tile_bg": 9}, {}):
            assert (await c.patch(url, json=bad)).status_code == 422


@pytest.mark.asyncio
async def test_a_blocked_agent_is_pushed_once_however_many_passes_repost_its_card(world):
    port, key, ref = thread_port.get(), world.a["thread_key"], f"{body.WAKE_REFUSED_PREFIX}{world.a['id']}"
    ids = {await port.post_card(key, "info", "cannot wake yet", "Loki stays asleep: pegged.", ref) for _ in range(6)}
    assert len(ids) == 1 and len(world.inner.cards) == 1
    assert [e.type_id for e in world.sent] == ["swarm.alert"]
    for n in range(5):
        await port.post_card(key, "info", "wake failed", "boom", f"{body.WAKE_FAILED_PREFIX}{world.a['id']}:{n}")
    assert [e.type_id for e in world.sent] == ["swarm.alert", "swarm.alert"]
    await port.post_card(world.b["thread_key"], "info", "cannot wake yet", "x", f"{body.WAKE_REFUSED_PREFIX}{world.b['id']}")
    assert len(world.sent) == 3
    await port.settle_cards(ref, resolve=True)
    await port.post_card(key, "info", "cannot wake yet", "again", ref)
    assert len(world.sent) == 4
