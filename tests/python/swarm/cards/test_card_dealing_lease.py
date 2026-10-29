
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_c3_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_c3_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import body, delivery, store, thread_port, watch
from src.core.swarm.cards import dealer, lease, ops, port as card_port, sweep
from src.core.swarm.facade import SwarmFacade
from src.cplugs import huddle as huddle_plugin
from src.cplugs.huddle import service
from src.cplugs.huddle.cards import policy
from src.cplugs.huddle.cards.port import TaskManagerCardPort
from src.core.work.storage import WorkStorage

LEASE_S = sweep.LEASE_S


class Chat:

    def __init__(self) -> None:
        self.traffic: List[Any] = []

    async def ensure_thread(self, key, title): ...
    async def post_card(self, key, kind, title, text, ref): return 1
    async def post_traffic(self, key, text, ref):
        self.traffic.append((key, text, ref))
        return f"huddle:msg:t{len(self.traffic)}"

    async def post_owner_message(self, key, text): return "huddle:msg:o1"
    async def close_card(self, item_id, state): ...
    async def archive_thread(self, key): ...


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    repo = tmp_path / "repo"
    repo.mkdir()
    policy.drain_kicks()
    lease.reset()
    monkeypatch.setattr(dealer, "DEAL_DEBOUNCE_S", 0.05)
    monkeypatch.setattr(lease, "BOOT_AT", 0.0)
    gate: Dict[str, Optional[asyncio.Event]] = {"event": None}
    told: List[Dict[str, Any]] = []
    woke: List[int] = []
    outcome = ["delivered"]

    async def deliver_text(app_state, agent_id, text, **kw):
        told.append({"agent": agent_id, "text": text, "ref": kw.get("source_ref")})
        if gate["event"] is not None:
            await gate["event"].wait()
        return outcome[0]

    async def wake(app_state, agent_id, *a, **kw):
        woke.append(agent_id)

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    monkeypatch.setattr(delivery, "record_for_session_row", lambda *a, **k: None)
    monkeypatch.setattr(body, "wake", wake)
    rows: Dict[str, int] = {}
    agents: Dict[str, Dict[str, Any]] = {}
    with closing(connect(db_path_for(tmp_path / "state"), create=False)) as conn:
        for pid, name in ((16, "Zeta"), (17, "Empty")):
            conn.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, ?, ?, 'test',"
                         " '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z')", (pid, str(repo / name), str(repo / name), name))

        def agent(slug, rank, parent=None, **extra):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created', 'running',"
                         " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{slug}", f"cloude_{slug}", str(repo)))
            rows[slug] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{slug}",)).fetchone()[0]
            row = store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(), repo_dir=str(repo), effort="high",
                                     parent_id=parent, goal=f"goal of {slug}", task_type="refactor", **extra)
            store.set_session_row(conn, row["id"], rows[slug])
            store.cas_state(conn, row["id"], "asleep", "awake")
            agents[slug] = store.get_agent(conn, row["id"])

        agent("boss", "project", project_id=16)
        agent("fixer", "task", agents["boss"]["id"])
        agent("builder", "feature", agents["boss"]["id"])

    async def list_infos():
        return []

    state = SimpleNamespace(session_manager=SimpleNamespace(list_session_infos=list_infos))
    facade = SwarmFacade(tmp_path / "state", list_infos, state)
    projects = [{"id": 16, "name": "Zeta"}, {"id": 17, "name": "Empty"}]
    ctx = SimpleNamespace(storage=WorkStorage(tmp_path / "huddle"), settings={"view": "area"}, swarm=facade, notify=lambda *a, **k: None,
                          has=lambda p: True, projects=SimpleNamespace(list=lambda **kw: list(projects)))
    chat = Chat()
    thread_port.register(chat)
    w = SimpleNamespace(huddle=service.store(ctx), ctx=ctx, facade=facade, port=TaskManagerCardPort(ctx), state=state, chat=chat, told=told, woke=woke,
                        outcome=outcome, agents=agents, tmp=tmp_path, projects=projects, gate=gate)
    yield w
    facade.register_card_port(None)
    thread_port.register(None)
    lease.reset()
    watch.reset()
    policy.drain_kicks()


def bring_up(w) -> None:
    w.facade.register_card_port(w.port)


async def step(w, projects: Optional[List[Dict[str, Any]]] = None) -> bool:
    saved = list(w.projects)
    w.projects[:] = projects or []
    try:
        return await huddle_plugin._dealing_step(w.ctx)
    finally:
        w.projects[:] = saved


async def make(w, title: str = "work", project: int = 16) -> Dict[str, Any]:
    return await ops.create(w.state, None, {"title": title, "project_id": project, "queued": True}, by="owner")


async def held(w, slug: str = "fixer", title: str = "work") -> Dict[str, Any]:
    card = await make(w, title)
    await ops.deal(w.state, card["id"], {"agent_id": w.agents[slug]["id"]}, by="owner")
    return await ops.start(w.state, card["id"], {}, by=f"agent:{w.agents[slug]['id']}")


async def view(card_id: int) -> Dict[str, Any]:
    return await card_port.get().card(card_id)


def requests(w) -> List[Dict[str, Any]]:
    return [t for t in w.told if t["text"].startswith("Deal request")]


async def settle(seconds: float = 0.4) -> None:
    await asyncio.sleep(seconds)


async def row(w, key: str = "16") -> Optional[Dict[str, Any]]:
    return (await card_port.get().policy_read("deal", {"project_key": key}))["deal"]


def reading(state: str = "busy", reason: str = "tool", at: float = 0.0, dialog: Any = None, stale: bool = False) -> Any:
    return SimpleNamespace(verdict=SimpleNamespace(state=state, reason=reason), evidence=SimpleNamespace(dialog=dialog), stale=stale, cycle=1,
                           observed_at=datetime.fromtimestamp(at))


def last_beat(card: Dict[str, Any]) -> float:
    return max(card["holder"]["beat_at"] or 0.0, card["holder"]["since"] or 0.0)


@pytest.mark.asyncio
async def test_a_burst_of_cards_delivers_one_deal_request_listing_all_of_them_and_the_agent_answers_it(world):
    w, boss = world, world.agents["boss"]
    await step(w)
    bring_up(w)
    cards = await asyncio.gather(*(make(w, f"burst {i}") for i in range(5)))
    await settle()
    assert len(requests(w)) == 1 and requests(w)[0]["agent"] == boss["id"] and requests(w)[0]["ref"] == "deal:16"
    assert all(f"card #{c['id']}: burst" in requests(w)[0]["text"] for c in cards)
    assert "Free agents: Fixer (agent" in requests(w)[0]["text"] and "Deal request for Zeta: card created" in requests(w)[0]["text"]
    first = await row(w)
    assert first["state"] == "delivered" and first["attempts"] == 1 and len(first["offered_ids"]) == 5
    await make(w, "sixth")
    await settle()
    assert len(requests(w)) == 1
    await ops.deal(w.state, None, {"hold": True}, by=f"agent:{boss['id']}")
    assert (await row(w))["state"] == "answered"
    await make(w, "after the answer")
    await settle()
    assert len(requests(w)) == 2 and (await row(w))["state"] == "delivered"


@pytest.mark.asyncio
async def test_a_project_with_no_agents_still_gets_its_kick_and_reads_no_dealer(world):
    w = world
    await step(w)
    bring_up(w)
    await make(w, "orphan", project=17)
    await asyncio.sleep(0.01)
    assert dealer.armed("17")
    await settle()
    assert (await row(w, "17"))["state"] == "no_dealer" and not requests(w)


@pytest.mark.asyncio
async def test_dealing_is_fail_closed_until_the_one_time_step_then_the_step_stores_off_for_every_existing_project(world):
    w = world
    bring_up(w)
    await make(w, "before the step")
    await settle()
    assert (await row(w))["state"] == "dealing_off" and not requests(w)
    await ops.set_rules(w.state, None, {"list_key": "18", "changes": {"dealing": True}}, by="owner")
    assert await step(w, [{"id": 16, "name": "Zeta"}, {"id": 17, "name": "Empty"}, {"id": 18, "name": "Late"}]) is True
    stored = {k: (await card_port.get().policy_read("rules", {"list_keys": [k]}))["rules"][k]["dealing"] for k in ("16", "17", "18", "19")}
    assert stored == {"16": False, "17": False, "18": True, "19": None}
    assert (await card_port.get().policy_read("dealing", {"project_key": "19"}))["dealing"] is True
    assert (await card_port.get().policy_read("dealing", {"project_key": "16"}))["dealing"] is False
    assert await step(w, [{"id": 20, "name": "Never"}]) is False
    assert (await card_port.get().policy_read("rules", {"list_keys": ["20"]}))["rules"]["20"]["dealing"] is None
    await make(w, "while off")
    await settle()
    assert not requests(w) and (await row(w))["state"] == "dealing_off"
    await ops.set_rules(w.state, None, {"list_key": "16", "changes": {"dealing": True}}, by="owner")
    await settle()
    assert len(requests(w)) == 1 and (await row(w))["state"] == "delivered"


@pytest.mark.asyncio
async def test_a_card_with_no_beat_for_600_s_lapses_and_fires_one_request(world):
    w, fixer, boss = world, world.agents["fixer"], world.agents["boss"]
    await step(w)
    bring_up(w)
    card = await held(w)
    await settle()
    w.told.clear()
    base = last_beat(card)
    assert (await sweep.run(w.state, base + LEASE_S - 1)) == {"lapsed": 0, "stalled": 0, "refreshed": 0, "rearmed": 0, "resent": 0, "slotted": 0, "nudged": 0}
    assert (await view(card["id"]))["holder"]["agent_id"] == fixer["id"]
    counts = await sweep.run(w.state, base + LEASE_S + 1)
    assert counts["lapsed"] == 1
    after = await view(card["id"])
    assert after["column"] == "in_progress" and after["queued"] and after["holder"] is None and after["last_holder"] == fixer["id"] and after["mark"]["name"] == "handing_off"
    assert [t["agent"] for t in w.told if "went quiet" in t["text"]] == [fixer["id"]] and not w.woke
    await settle()
    assert len(requests(w)) == 1 and requests(w)[0]["agent"] == boss["id"] and "lease lapsed" in requests(w)[0]["text"]
    assert (await sweep.run(w.state, base + LEASE_S + 31))["lapsed"] == 0
    await settle()
    assert len(requests(w)) == 1
    await ops.deal(w.state, card["id"], {"agent_id": w.agents["builder"]["id"]}, by=f"agent:{boss['id']}")
    handed = [t for t in w.chat.traffic if "stopped responding; handed" in t[1]]
    assert len(handed) == 1 and "to Builder, which starts from the handoff note" in handed[0][1] and handed[0][2].startswith("card:handed_off:")


@pytest.mark.asyncio
async def test_a_review_card_whose_agent_was_torn_down_never_lapses_but_a_held_card_of_a_dead_body_lapses_at_once(world):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w, "fixer", "finished work")
    await ops.finish(w.state, card["id"], {"result": "done", "how_to_validate": "look"}, by=f"agent:{fixer['id']}")
    assert (await view(card["id"]))["column"] == "review"
    mine = await held(w, "builder", "builder work")
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        for slug in ("fixer", "builder"):
            conn.execute("UPDATE swarm_agents SET state = 'torn_down', torn_down_at = '2026-10-07T00:00:00Z' WHERE id = ?", (w.agents[slug]["id"],))
    w.told.clear()
    assert (await sweep.run(w.state, last_beat(mine) + 5))["lapsed"] == 1
    assert (await view(card["id"]))["column"] == "review" and (await view(mine["id"]))["column"] == "in_progress"
    assert (await sweep.run(w.state, time.time() + 10 ** 6))["lapsed"] == 0
    assert (await view(card["id"]))["column"] == "review"
    assert not [t for t in w.told if "went quiet" in t["text"]]


@pytest.mark.asyncio
async def test_an_open_question_a_stop_reading_and_a_busy_reading_all_hold_the_clock(world):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w)
    base = last_beat(card)
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        conn.execute("INSERT INTO swarm_questions (id, text, state, created_at) VALUES (1, 'which flag?', 'routing', '2026-10-07T00:00:00Z')")
        conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (1, ?, ?)",
                     (fixer["id"], datetime.fromtimestamp(base + 1).astimezone().isoformat()))
    far = base + 10 ** 4
    assert (await sweep.run(w.state, far))["lapsed"] == 0
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        conn.execute("UPDATE swarm_questions SET state = 'answered' WHERE id = 1")
    assert (await sweep.run(w.state, far + 30))["lapsed"] == 0
    assert (await sweep.run(w.state, far + LEASE_S + 1))["lapsed"] == 1
    again = await held(w, "builder", "second")
    b2 = last_beat(again)
    lease.observe(w.agents["builder"]["id"], reading("needs_user", "permission", at=b2 + 8995))
    assert (await sweep.run(w.state, b2 + 9000))["lapsed"] == 0
    lease.observe(w.agents["builder"]["id"], reading("done_idle", "turn_ended", at=b2 + 9000))
    assert (await sweep.run(w.state, b2 + 8995 + LEASE_S - 1))["lapsed"] == 0
    assert (await sweep.run(w.state, b2 + 8995 + LEASE_S + 1))["lapsed"] == 1
    silent = await held(w, "builder", "silent watcher")
    b4 = last_beat(silent)
    lease.observe(w.agents["builder"]["id"], reading("needs_user", "question", at=b4 + 10))
    assert (await sweep.run(w.state, b4 + 10 + sweep.STOP_FRESH_S + LEASE_S + 5))["lapsed"] == 1
    third = await held(w, "builder", "third")
    b3 = last_beat(third)
    lease.observe(w.agents["builder"]["id"], reading("busy", "subagents", at=b3 + 3000))
    assert (await sweep.run(w.state, b3 + 3000 + LEASE_S - 1))["lapsed"] == 0
    assert (await sweep.run(w.state, b3 + 3000 + LEASE_S + 1))["lapsed"] == 1


@pytest.mark.asyncio
async def test_an_asleep_holder_quiet_past_600_s_loses_the_card_despite_an_older_question_and_a_stale_screen(world):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w)
    base = last_beat(card)
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        conn.execute("INSERT INTO swarm_questions (id, text, state, created_at) VALUES (1, 'older?', 'open', '2026-10-07T00:00:00Z')")
        conn.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (1, ?, ?)",
                     (fixer["id"], datetime.fromtimestamp(base - 3600).astimezone().isoformat()))
        store.cas_state(conn, fixer["id"], "awake", "asleep")
    lease.observe(fixer["id"], reading("needs_user", "input", at=base + LEASE_S + 5))
    w.told.clear()
    assert (await sweep.run(w.state, base + LEASE_S - 1))["lapsed"] == 0
    assert (await sweep.run(w.state, base + LEASE_S + 10))["lapsed"] == 1
    after = await view(card["id"])
    assert after["holder"] is None and after["queued"] and after["column"] == "in_progress" and after["last_holder"] == fixer["id"]
    db = WorkStorage(w.tmp / "huddle").db_path
    with closing(sqlite3.connect(db)) as conn:
        rows = conn.execute("SELECT kind, by, detail FROM work_card_events WHERE item_id = ? AND kind = 'lapsed'", (card["id"],)).fetchall()
    assert rows == [("lapsed", "server", f"no sign of life for {int(LEASE_S + 10)} s")]
    owner = [t for t in w.chat.traffic if "went quiet on" in t[1]]
    assert len(owner) == 1 and "it is queued for the next deal" in owner[0][1] and owner[0][2].startswith("card:important:")


@pytest.mark.asyncio
async def test_a_legacy_claim_and_a_paused_card_never_lapse(world):
    w = world
    await step(w)
    bring_up(w)
    claimed = await make(w, "plain session claim")
    await asyncio.to_thread(w.huddle.mark_working, claimed["id"], "plain-session")
    assert (await view(claimed["id"]))["column"] == "in_progress" and (await view(claimed["id"]))["holder"] is None
    paused = await held(w, "fixer", "paused work")
    await ops.pause(w.state, paused["id"], {"mode": "after_step"}, by="owner")
    counts = await sweep.run(w.state, time.time() + 10 ** 6)
    assert {k: counts[k] for k in ("lapsed", "stalled", "refreshed")} == {"lapsed": 0, "stalled": 0, "refreshed": 0}
    assert (await view(claimed["id"]))["column"] == "in_progress" and (await view(paused["id"]))["holder"]["agent_id"] == w.agents["fixer"]["id"]
    await ops.resume(w.state, paused["id"], {}, by="owner")
    resumed = await view(paused["id"])
    assert (await sweep.run(w.state, last_beat(resumed) + LEASE_S - 1))["lapsed"] == 0


@pytest.mark.asyncio
async def test_with_dealing_off_a_lapse_posts_one_stalled_item_and_deals_nothing(world):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    await ops.set_rules(w.state, None, {"list_key": "16", "changes": {"dealing": False}}, by="owner")
    card = await held(w)
    await settle()
    w.told.clear()
    base = last_beat(card)
    assert (await sweep.run(w.state, base + LEASE_S + 1))["stalled"] == 1
    stalled = await view(card["id"])
    assert stalled["holder"]["agent_id"] == fixer["id"] and stalled["mark"]["name"] == "stalled" and stalled["column"] == "in_progress"
    lines = [t for t in w.chat.traffic if "stopped responding on" in t[1]]
    assert len(lines) == 1 and "dealing is off in Zeta" in lines[0][1] and lines[0][2].startswith("card:important:")
    assert (await sweep.run(w.state, base + LEASE_S + 400))["stalled"] == 0
    await settle()
    assert len([t for t in w.chat.traffic if "stopped responding on" in t[1]]) == 1 and not requests(w) and (await row(w))["state"] == "dealing_off"
    await ops.handoff(w.state, card["id"], {"handoff": "back", "progress": 10}, by=f"agent:{fixer['id']}")
    assert (await view(card["id"]))["mark"] is None
    await ops.set_rules(w.state, None, {"list_key": "16", "changes": {"dealing": True}}, by="owner")
    again = await view(card["id"])
    assert (await sweep.run(w.state, last_beat(again) + LEASE_S + 1))["lapsed"] == 1


@pytest.mark.asyncio
async def test_a_working_holder_with_a_stale_handoff_is_asked_to_refresh_once_per_window(world):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w)
    base = last_beat(card)
    at = base + sweep.REFRESH_S + 100
    lease.observe(fixer["id"], reading("busy", "tool", at=at))
    w.told.clear()
    assert (await sweep.run(w.state, at + 5))["refreshed"] == 1
    asks = [t for t in w.told if t["text"].startswith("Write your handoff into card")]
    assert len(asks) == 1 and asks[0]["agent"] == fixer["id"]
    asked = (await card_port.get().policy_read("leases", {}))["leases"][0]["refresh_asked_at"]
    lease.observe(fixer["id"], reading("busy", "tool", at=asked + 60))
    assert (await sweep.run(w.state, asked + 65))["refreshed"] == 0 and len([t for t in w.told if "Write your handoff" in t["text"]]) == 1
    lease.observe(fixer["id"], reading("busy", "tool", at=asked + sweep.REFRESH_S + 10))
    assert (await sweep.run(w.state, asked + sweep.REFRESH_S + 20))["refreshed"] == 1


@pytest.mark.asyncio
async def test_the_sweep_rearms_a_lost_timer_resends_an_unanswered_request_and_gives_up_after_three(world):
    w, boss = world, world.agents["boss"]
    await step(w)
    bring_up(w)
    await make(w, "lost timer")
    dealer._cancel_timers()
    assert (await row(w))["state"] == "waiting" and not requests(w)
    assert (await sweep.run(w.state, time.time() + 10))["rearmed"] == 1
    await settle()
    assert len(requests(w)) == 1 and (await row(w))["state"] == "delivered"
    delivered_at = (await row(w))["delivered_at"]
    assert (await sweep.run(w.state, delivered_at + dealer.RETRY_S - 1))["resent"] == 0
    assert (await sweep.run(w.state, delivered_at + dealer.RETRY_S + 1))["resent"] == 1
    await settle()
    assert len(requests(w)) == 2 and (await row(w))["attempts"] == 2 and w.told[-1]["agent"] == boss["id"]
    assert (await sweep.run(w.state, delivered_at + 2 * dealer.RETRY_S + 2))["resent"] == 1
    await settle()
    assert len(requests(w)) == 3 and (await row(w))["attempts"] == 3
    assert (await sweep.run(w.state, delivered_at + 3 * dealer.RETRY_S + 3))["resent"] == 1
    await settle()
    assert len(requests(w)) == 3 and (await row(w))["state"] == "gave_up"
    gave = [t for t in w.chat.traffic if "went unanswered" in t[1]]
    assert len(gave) == 1 and gave[0][2] == "card:important:deal-16"


@pytest.mark.asyncio
async def test_refused_sends_count_attempts_retry_at_the_full_spacing_and_give_up_with_one_important_item(world):
    w = world
    await step(w)
    bring_up(w)
    w.outcome[0] = "refused:pane_gone"
    await make(w, "never lands")
    await settle()
    assert len(requests(w)) == 1
    for tries in range(1, 4):
        current = await row(w)
        assert current["state"] == "waiting" and current["attempts"] == tries
        assert (await sweep.run(w.state, current["delivered_at"] + dealer.RETRY_S - 1))["rearmed"] == 0
        await settle()
        assert len(requests(w)) == tries
        await sweep.run(w.state, current["delivered_at"] + dealer.RETRY_S + 1)
        await settle()
    assert (await row(w))["state"] == "gave_up" and len(requests(w)) == 3
    assert len([t for t in w.chat.traffic if "went unanswered" in t[1]]) == 1


@pytest.mark.asyncio
async def test_a_new_card_after_a_refused_send_waits_for_the_retry_spacing_and_the_sweep_sends_it(world):
    w = world
    await step(w)
    bring_up(w)
    w.outcome[0] = "refused:pane_gone"
    await make(w, "first")
    await settle()
    assert len(requests(w)) == 1 and (await row(w))["attempts"] == 1
    for title in ("second", "third", "fourth"):
        await make(w, title)
        await settle()
    assert len(requests(w)) == 1 and (await row(w))["attempts"] == 1 and (await row(w))["state"] == "waiting"
    stamp = (await row(w))["delivered_at"]
    assert (await sweep.run(w.state, stamp + dealer.RETRY_S + 1))["rearmed"] == 1
    await settle()
    assert len(requests(w)) == 2 and (await row(w))["attempts"] == 2


@pytest.mark.asyncio
async def test_a_failed_bookkeeping_write_after_a_send_never_lets_the_request_go_out_again(world, monkeypatch):
    w = world
    await step(w)
    bring_up(w)
    real = w.port.policy

    async def policy_write(op, args, by):
        if op == "deal_state" and args["state"] == "delivered":
            raise sqlite3.OperationalError("database is locked")
        return await real(op, args, by)

    monkeypatch.setattr(w.port, "policy", policy_write)
    await make(w, "lands")
    await settle()
    assert len(requests(w)) == 1 and (await row(w))["state"] == "waiting" and (await row(w))["attempts"] == 1
    assert (await sweep.run(w.state, time.time() + 60))["rearmed"] == 0
    await settle()
    assert len(requests(w)) == 1


@pytest.mark.asyncio
async def test_a_deal_write_that_fails_before_the_send_sends_nothing(world, monkeypatch):
    w = world
    await step(w)
    bring_up(w)
    real = w.port.policy

    async def policy_write(op, args, by):
        if op == "deal_state" and args.get("attempt"):
            raise sqlite3.OperationalError("database is locked")
        return await real(op, args, by)

    monkeypatch.setattr(w.port, "policy", policy_write)
    await make(w, "never typed")
    await settle()
    assert not requests(w) and (await row(w))["attempts"] == 0


@pytest.mark.asyncio
async def test_a_send_still_in_flight_is_never_sent_twice_by_a_sweep_or_a_new_card(world):
    w = world
    await step(w)
    bring_up(w)
    w.gate["event"] = asyncio.Event()
    await make(w, "first")
    await settle(0.2)
    assert len(requests(w)) == 1 and (await row(w))["state"] == "waiting"
    assert dealer.armed("16")
    assert (await sweep.run(w.state, time.time() + 60))["rearmed"] == 0
    await make(w, "second")
    await settle(0.2)
    assert len(requests(w)) == 1
    w.gate["event"].set()
    await settle()
    assert len(requests(w)) == 1 and (await row(w))["state"] == "delivered" and not dealer.armed("16")


@pytest.mark.asyncio
async def test_the_watcher_reading_of_a_swarm_body_feeds_the_lease(world, monkeypatch):
    w, fixer = world, world.agents["fixer"]
    monkeypatch.setitem(watch._bodies, "cloude_fixer", fixer["id"])
    assert lease.beat(fixer["id"]) is None
    now = time.time()
    watch.on_observation(SimpleNamespace(key="cloude_fixer@17"), reading("busy", "tool", at=now))
    assert lease.beat(fixer["id"]).busy_at == pytest.approx(now, abs=1.0)
    watch.on_observation(SimpleNamespace(key="cloude_stranger@17"), reading("busy", "tool", at=now))
    assert len(lease._beats) == 1


@pytest.mark.asyncio
async def test_a_reused_tmux_name_at_another_epoch_never_feeds_the_lease_or_settles_a_stale_body(world, monkeypatch):
    fixer, builder = world.agents["fixer"], world.agents["builder"]
    calls: List[Any] = []
    real_observe = lease.observe
    monkeypatch.setattr(lease, "observe", lambda agent_id, obs: (calls.append(("observe", agent_id)), real_observe(agent_id, obs))[1])
    monkeypatch.setattr(watch, "_spawn", lambda agent_id, work: calls.append((work.__name__, agent_id)))
    watch.register(world.state, "cloude_fixer", fixer["id"], 1_760_000_000)
    now = time.time()
    plain = reading("busy", "tool", at=now)
    for key in ("cloude_fixer@1760000500", "cloude_fixer"):
        watch.on_observation(SimpleNamespace(key=key), plain)
    assert calls == [] and lease.beat(fixer["id"]) is None
    watch.on_observation(SimpleNamespace(key="cloude_fixer@1760000000"), plain)
    assert calls == [("observe", fixer["id"]), ("_settle", fixer["id"])]
    assert lease.beat(fixer["id"]).busy_at == pytest.approx(now, abs=1.0)
    calls.clear()
    watch.register(world.state, "cloude_builder", builder["id"], None)
    for key in ("cloude_builder@1760000500", "cloude_builder"):
        watch.on_observation(SimpleNamespace(key=key), plain)
    assert calls == [("observe", builder["id"]), ("_settle", builder["id"])] * 2
    assert watch.split_instance_key("user@host") == ("user@host", None)
    assert watch.split_instance_key("cloude_a@17") == ("cloude_a", 17)


@pytest.mark.asyncio
async def test_inside_the_boot_grace_nothing_lapses_asks_or_posts_for_a_card_that_exists_today(world, monkeypatch):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    await ops.set_rules(w.state, None, {"list_key": "16", "changes": {"dealing": False}}, by="owner")
    card = await held(w)
    base = last_beat(card)
    boot = base + 5
    monkeypatch.setattr(lease, "BOOT_AT", boot)
    lease.observe(fixer["id"], reading("busy", "tool", at=boot + sweep.REFRESH_S + 100))
    w.told.clear()
    assert (await sweep.run(w.state, boot + LEASE_S - 1)) == {"lapsed": 0, "stalled": 0, "refreshed": 0, "rearmed": 0, "resent": 0, "slotted": 0, "nudged": 0}
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        conn.execute("UPDATE swarm_agents SET state = 'torn_down', torn_down_at = '2026-10-07T00:00:00Z' WHERE id = ?", (fixer["id"],))
    assert (await sweep.run(w.state, boot + LEASE_S - 1))["stalled"] == 0
    assert not [t for t in w.chat.traffic if "stopped responding on" in t[1]] and not w.told
    assert (await sweep.run(w.state, boot + LEASE_S + 1))["stalled"] == 1


@pytest.mark.asyncio
async def test_with_dealing_on_a_dead_holder_inside_the_boot_grace_lapses_nothing_requests_nothing_and_wakes_nothing(world, monkeypatch):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w)
    boot = last_beat(card) + 5
    monkeypatch.setattr(lease, "BOOT_AT", boot)
    with closing(connect(db_path_for(w.tmp / "state"), create=False)) as conn:
        conn.execute("UPDATE swarm_agents SET state = 'torn_down', torn_down_at = '2026-10-07T00:00:00Z' WHERE id = ?", (fixer["id"],))
    w.told.clear()
    w.woke.clear()
    assert (await sweep.run(w.state, boot + LEASE_S - 1)) == {"lapsed": 0, "stalled": 0, "refreshed": 0, "rearmed": 0, "resent": 0, "slotted": 0, "nudged": 0}
    await settle()
    assert not w.told and not w.woke and not requests(w)
    assert (await sweep.run(w.state, boot + LEASE_S + 1))["lapsed"] == 1


@pytest.mark.asyncio
async def test_a_working_holder_is_not_asked_to_refresh_inside_the_boot_grace(world, monkeypatch):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w)
    at = last_beat(card) + sweep.REFRESH_S + 100
    monkeypatch.setattr(lease, "BOOT_AT", at - 10)
    lease.observe(fixer["id"], reading("busy", "tool", at=at))
    assert (await sweep.run(w.state, at + 5))["refreshed"] == 0
    monkeypatch.setattr(lease, "BOOT_AT", at - LEASE_S - 10)
    assert (await sweep.run(w.state, at + 5))["refreshed"] == 1


@pytest.mark.asyncio
async def test_a_lapse_decides_on_the_switch_and_beat_at_write_time_and_a_non_project_list_never_deals(world):
    w, fixer = world, world.agents["fixer"]
    await step(w)
    bring_up(w)
    card = await held(w)
    base = last_beat(card)
    seen = [card["holder"]["beat_at"], card["holder"]["since"]]
    await ops.set_rules(w.state, None, {"list_key": "16", "changes": {"dealing": False}}, by="owner")
    await card_port.get().act("lapse", card["id"], {"reason": "quiet", "seen": seen}, "server")
    after = await view(card["id"])
    assert after["mark"]["name"] == "stalled" and after["holder"]["agent_id"] == fixer["id"]
    with pytest.raises(Exception) as refused:
        await card_port.get().act("lapse", card["id"], {"reason": "quiet", "seen": [seen[0] or 0.0, (seen[1] or 0.0) - 1]}, "server")
    assert getattr(refused.value, "code", "") == "stale"
    assert base > 0
    assert (await card_port.get().policy_read("dealing", {"project_key": "not-a-project"}))["dealing"] is False


@pytest.mark.asyncio
async def test_an_unreadable_project_list_leaves_the_step_unrun_and_the_dealer_closed(world, monkeypatch):
    from src.api import projects_service
    from src.core.project_authority import MODE_DB_UNREADABLE, ProjectsView
    from src.cplugs.host import capabilities

    w = world
    bring_up(w)

    def unreadable(**kw):
        raise OSError("the project list could not be read")

    w.ctx.projects = SimpleNamespace(list=unreadable)
    assert await huddle_plugin._dealing_step(w.ctx) is False
    assert (await card_port.get().policy_read("dealing", {"project_key": "16"}))["step"] is False
    assert (await card_port.get().policy_read("dealing", {"project_key": "16"}))["dealing"] is False
    monkeypatch.setattr(projects_service, "current_view", lambda settings, include_archived=False: ProjectsView(mode=MODE_DB_UNREADABLE, message="down"))
    assert capabilities.Projects().list() == []
    with pytest.raises(OSError):
        capabilities.Projects().list(include_archived=True, strict=True)
