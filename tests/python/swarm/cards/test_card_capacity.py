
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional

import pytest

# ruff: noqa: E402, F811
from src.core.db import connect, db_path_for
from src.core.swarm import spawn, store
from src.core.swarm.cards import capacity, cpu, dealer, deliver, ops, port as card_port, sweep
from src.cplugs.huddle.cards import policy, tx
from src.core.mcp import card_capacity_tools
from tests.python.swarm.cards.test_card_enforcement import _spawn, _spawn_world, caller, call, owner, owner_approves, refused, world  # noqa: F401

REAL_SAMPLE = capacity.sample
REAL_ACCOUNT_FOR = capacity.account_for


@pytest.fixture(autouse=True)
def approved(monkeypatch):
    monkeypatch.setattr(card_capacity_tools.write_tools, "park", owner_approves)


@pytest.fixture(autouse=True)
def governor(monkeypatch):
    capacity.reset()
    _FAKE.update(ticks=(0, 0, 100, 0), clock=1000.0, anchored=False)
    monkeypatch.setattr(capacity, "sample", lambda *a, **k: None)
    monkeypatch.setattr(capacity, "account_for", lambda profile: None)
    yield
    capacity.reset()


def db(w):
    return closing(connect(db_path_for(w.tmp / "state"), create=False))


def go(w, work):
    with db(w) as conn:
        return work(conn)


def live(w, slug: str, project: int = 16) -> None:
    def work(conn):
        agent = w.agents[slug]
        store.update_agent(conn, agent["id"], project_id=project)
        conn.execute("INSERT INTO swarm_wakes (agent_id, started_at, reason, mode, authority) VALUES (?, '2026-10-07T00:00:00Z', 'spawn', 'fresh', 'data')", (agent["id"],))
        conn.commit()
    go(w, work)


def end_wake(w, slug: str) -> None:
    def work(conn):
        conn.execute("UPDATE swarm_wakes SET ended_at = '2026-10-07T01:00:00Z', end_reason = 'sleep' WHERE agent_id = ? AND ended_at IS NULL", (w.agents[slug]["id"],))
        conn.commit()
    go(w, work)


def asleep(w, slug: str) -> None:
    go(w, lambda conn: store.cas_state(conn, w.agents[slug]["id"], "awake", "asleep"))


def grant(w, scope: str, slots: Optional[int], by: str = "owner") -> dict:
    return asyncio.run(card_port.get().policy("set_grant", {"scope": scope, "slots": slots, "reason": "test"}, by))["data"]["grant"]


def dealing_step(w) -> None:
    store_ = w.huddle
    with tx.write(store_, set()) as conn:
        policy.ensure_dealing_step(conn, [], time.time())


def card(w, title: str = "work") -> dict:
    made = call(w, "boss", "swarm_card_create", summary="a plain line", title=title, project_id=16)["card"]
    return asyncio.run(ops.set_column(w.state, made["id"], {"column": "in_progress"}, by="owner"))


def view(w, card_id: int) -> dict:
    return asyncio.run(card_port.get().card(card_id))


def sweep_once(w) -> dict:
    return asyncio.run(sweep.run(w.state))


_FAKE = {"ticks": (0, 0, 100, 0), "clock": 1000.0, "anchored": False}


def feed(busy: List[float]) -> None:
    if not _FAKE["anchored"]:
        REAL_SAMPLE(_FAKE["clock"], lambda: _FAKE["ticks"])
        _FAKE["anchored"] = True
    for pct in busy:
        user, system, idle, nice = _FAKE["ticks"]
        _FAKE["ticks"] = (user + int(pct), system, idle + 100 - int(pct), nice)
        _FAKE["clock"] += 30.0
        REAL_SAMPLE(_FAKE["clock"], lambda: _FAKE["ticks"])


def test_a_full_grant_makes_a_deal_wait_for_a_slot_and_the_sweep_deals_it_when_one_frees(world):
    w = world
    live(w, "fixer"), live(w, "builder")
    asleep(w, "kid")
    grant(w, "project:16", 2)
    cid = card(w)["id"]
    out = call(w, "boss", "swarm_card_deal", card_id=cid, agent_id=w.agents["kid"]["id"])["card"]
    assert out["holder"] is None and out["dealt_to"] == w.agents["kid"]["id"] and out["mark"]["name"] == "waiting_for_slot" and out["column"] == "in_progress"
    assert not [t for t in w.told if "were dealt card" in t["text"]]
    assert sweep_once(w)["slotted"] == 0 and view(w, cid)["holder"] is None
    grant(w, "project:16", 3)
    assert sweep_once(w)["slotted"] == 1
    held = view(w, cid)
    assert held["holder"]["agent_id"] == w.agents["kid"]["id"] and held["column"] == "in_progress" and held["mark"] is None
    assert any(t["agent"] == w.agents["kid"]["id"] and "were dealt card" in t["text"] for t in w.told)
    assert sweep_once(w)["slotted"] == 0


def test_a_slot_that_frees_by_a_body_closing_deals_the_oldest_waiting_card_first(world):
    w = world
    live(w, "fixer"), live(w, "builder")
    asleep(w, "kid")
    grant(w, "project:16", 2)
    first, second = card(w, "first")["id"], card(w, "second")["id"]
    for cid in (first, second):
        call(w, "boss", "swarm_card_deal", card_id=cid, agent_id=w.agents["kid"]["id"])
    end_wake(w, "fixer")
    assert sweep_once(w)["slotted"] == 1
    assert view(w, first)["holder"] is not None and view(w, second)["holder"] is None
    assert view(w, second)["mark"]["name"] == "waiting_for_slot"


def test_a_cpu_floor_never_holds_back_a_dealt_existing_agent_or_touches_a_held_card_or_a_running_body(world):
    w = world
    dealing_step(w)
    asleep(w, "kid")
    held = card(w, "held")["id"]
    call(w, "boss", "swarm_card_deal", card_id=held, agent_id=w.agents["fixer"]["id"])
    call(w, "fixer", "swarm_card_start", card_id=held)
    base = view(w, held)["holder"]
    feed([90.0, 95.0, 99.0, 90.0])
    pct, floor = capacity.cpu_state()
    assert floor and pct == 90.0
    w.woke.clear(), w.keys.clear()
    counts = sweep_once(w)
    assert counts == {"lapsed": 0, "stalled": 0, "refreshed": 0, "rearmed": 0, "resent": 0, "slotted": 0, "nudged": 0}
    after = view(w, held)["holder"]
    assert after["agent_id"] == base["agent_id"] and after["since"] == base["since"] and not w.woke and not w.keys
    waiting = card(w, "needs a body")["id"]
    out = call(w, "boss", "swarm_card_deal", card_id=waiting, agent_id=w.agents["kid"]["id"])["card"]
    assert (out["mark"] or {}).get("name") != "waiting_for_slot" and out["holder"]["agent_id"] == w.agents["kid"]["id"]
    assert sweep_once(w)["slotted"] == 0


def test_the_floors_do_not_apply_while_dealing_is_off_for_the_project(world):
    w = world
    asleep(w, "kid")
    feed([95.0, 95.0, 95.0, 95.0])
    assert capacity.cpu_state()[1]
    cid = card(w)["id"]
    out = call(w, "boss", "swarm_card_deal", card_id=cid, agent_id=w.agents["kid"]["id"])["card"]
    assert out["holder"] is not None and out["mark"] is None
    assert go(w, lambda c: capacity.refusal(c, 16, {}, floors=True)) == "floor_cpu"
    assert asyncio.run(capacity.gate_inputs(None))[1] is False


def test_with_no_grant_set_nothing_fixed_holds_a_project_back(world):
    w = world
    for slug, parent in (("w1", "fixer"), ("w2", "fixer"), ("w3", "builder")):
        def mint(conn, slug=slug, parent=parent):
            row = store.create_agent(conn, slug=slug, rank="task", job=f"job of {slug}", display_name=slug, repo_dir="/tmp", effort="high",
                                     parent_id=w.agents[parent]["id"], goal="g", task_type="refactor", project_id=16)
            w.agents[slug] = row
        go(w, mint)
        live(w, slug)
    live(w, "fixer"), live(w, "builder")
    asleep(w, "kid")
    with db(w) as conn:
        assert capacity.slots(conn, 16, {}) == (None, None)
    cid = card(w)["id"]
    out = call(w, "boss", "swarm_card_deal", card_id=cid, agent_id=w.agents["kid"]["id"])["card"]
    assert out["holder"] is not None and out["mark"] is None


def test_the_load_average_is_never_read(world, monkeypatch):
    w = world

    def boom(*a, **k):
        raise AssertionError("os.getloadavg was called")

    monkeypatch.setattr(os, "getloadavg", boom)
    REAL_SAMPLE(time.monotonic() - 60.0)
    REAL_SAMPLE(time.monotonic())
    assert capacity.cpu_state()[1] is False
    reading = go(w, capacity.reading)
    assert reading.cpu_floor is False and reading.usage_floor is False
    assert go(w, lambda c: capacity.refusal(c, 16, {})) is None
    sweep_once(w)


def test_busy_percent_and_an_unreadable_source(tmp_path, monkeypatch):
    assert cpu.busy_pct((10, 10, 80, 0), (60, 10, 130, 0)) == 50.0
    assert cpu.busy_pct((10, 10, 80, 0), (10, 10, 80, 0)) is None
    assert cpu.busy_pct((10, 10, 80, 0), (5, 10, 90, 0)) is None
    assert cpu.busy_pct(None, (1, 1, 1, 1)) is None
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 20 50 800 40 0 0 0 0 0\ncpu0 1 1 1 1\n")
    monkeypatch.setattr(cpu, "_PROC_STAT", str(stat))
    monkeypatch.setattr(cpu.sys, "platform", "linux")
    assert cpu.ticks() == (100, 50, 840, 20)
    stat.write_text("garbage\n")
    assert cpu.ticks() is None
    monkeypatch.setattr(cpu.sys, "platform", "win32")
    assert cpu.ticks() is None
    feed([90.0, 90.0, 90.0])
    assert capacity.cpu_state() == (90.0, False)
    REAL_SAMPLE(1000.0, lambda: None)
    assert capacity.cpu_state() == (None, False)


def test_the_real_mach_or_proc_source_reads_ticks_that_grow():
    first = cpu.ticks()
    if first is None:
        assert sys.platform != "darwin", "the Mach binding must work on darwin"
        pytest.skip("no CPU tick source on this platform")
    time.sleep(0.05)
    second = cpu.ticks()
    busy = cpu.busy_pct(first, second)
    assert len(first) == 4 and sum(second) >= sum(first) and (busy is None or 0.0 <= busy <= 100.0)


@pytest.mark.skipif(sys.platform != "darwin", reason="the Mach host port exists on darwin only")
def test_mach_host_port_is_minted_once_not_per_sample():
    cpu.ticks()
    host = cpu._mach
    assert host is not None
    for _ in range(200):
        assert cpu.ticks() is not None
    assert cpu._mach is host


def test_the_sweep_takes_the_cpu_sample(world, monkeypatch):
    w = world
    monkeypatch.setattr(capacity, "sample", REAL_SAMPLE)
    reads = []
    monkeypatch.setattr(cpu, "ticks", lambda: reads.append(1) or (1, 1, 1, 1))
    sweep_once(w)
    assert reads and capacity._last is not None


def _acct(account_id, *used, name=None, label="7d", provider="claude", state="ok", age=10):
    return SimpleNamespace(id=account_id, name=name or account_id, provider=provider, credential_state=state,
                           fetched_at=datetime.fromtimestamp(time.time() - age, timezone.utc), windows=[SimpleNamespace(used_pct=u, label=label) for u in used])


def test_usage_floor_reads_only_fresh_healthy_claude_windows(monkeypatch):
    now = time.time()
    accounts = [_acct("a", 99.0, provider="codex"), _acct("b", 99.0, state="expired"), _acct("c", 99.0, age=2000),
                SimpleNamespace(id="d", name="d", provider="claude", credential_state="ok", fetched_at=None, windows=[SimpleNamespace(used_pct=99.0, label="5h")])]
    monkeypatch.setattr(capacity.ledger_poller, "snapshot", lambda: SimpleNamespace(accounts=accounts))
    assert capacity.usage_state(None, now) == capacity.Usage(None, False, None, None)
    accounts.append(_acct("e", 40.0, 91.0, name="work", age=60))
    assert capacity.usage_state(None, now) == capacity.Usage(91.0, True, "work", "7d")
    accounts[-1] = _acct("e", 40.0, 90.0, age=60)
    assert capacity.usage_state(None, now).floor is False


def test_the_usage_floor_counts_the_account_the_new_body_runs_on(world, monkeypatch):
    w = world
    dealing_step(w)
    asleep(w, "kid")
    accounts = [_acct("parked", 100.0, name="parked", label="7d"), _acct("work", 40.0, name="work", label="5h")]
    monkeypatch.setattr(capacity.ledger_poller, "snapshot", lambda: SimpleNamespace(accounts=accounts))
    monkeypatch.setattr(capacity, "account_for", lambda profile: "work")
    kid = {**w.agents["kid"], "state": "asleep"}

    def refusal():
        return go(w, lambda c: deliver.slot_refusal(c, kid, 16, {}))

    assert refusal() is None and capacity.floor_refusal() is None
    reading = go(w, capacity.reading)
    assert (reading.usage_max_pct, reading.usage_floor, reading.usage_account, reading.usage_window) == (40.0, False, "work", "5h")
    accounts[1] = _acct("work", 95.0, name="work", label="5h")
    assert capacity.floor_refusal() == "floor_usage"
    assert refusal() is None
    assert go(w, capacity.reading).usage_account == "work"
    sent, _, made = _spawn_world(w, monkeypatch)
    card(w, "queued")
    w.told.clear()
    assert asyncio.run(dealer.fire(w.state, "16")) == "delivered"
    text = next(t["text"] for t in w.told if t["text"].startswith("Deal request"))
    assert "Floor: the work account's 5h usage window is at 95%" in text and "Slots: 0 free" in text
    with pytest.raises(spawn.SpawnRefused, match="the work account's 5h usage window is at 95%"):
        asyncio.run(spawn.run(w.view, caller("boss"), _spawn(w)))
    assert not made and not sent
    monkeypatch.setattr(capacity, "account_for", lambda profile: None)
    assert capacity.refusal_text(capacity.floor_refusal()) == "the parked account's 7d usage window is at 100%, over 90%, so no new agent starts"
    accounts[0] = _acct("parked", 50.0, name="parked")
    accounts[1] = _acct("work", 40.0, name="work")
    assert refusal() is None


def test_account_for_ladder(tmp_path, monkeypatch):
    import json

    config = tmp_path / "config.json"
    profiles = [{"id": "claude-default", "harness": "claude", "label": "claude", "default": True},
                {"id": "pinned", "harness": "claude", "label": "p", "account": {"mode": "pinned", "account_id": "acct_x"}},
                {"id": "ghost", "harness": "claude", "label": "g", "account": {"mode": "pinned", "account_id": "acct_gone"}},
                {"id": "dir", "harness": "claude", "label": "d", "env": [{"name": "CLAUDE_CONFIG_DIR", "value": "/elsewhere"}]}]
    config.write_text(json.dumps({"launch_profiles": {"revision": 1, "profiles": profiles}}), encoding="utf-8")
    monkeypatch.setattr(capacity.app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(capacity.ledger_poller, "snapshot", lambda: SimpleNamespace(accounts=[_acct("acct_x", 10.0), _acct("acct_default", 10.0)]))
    seen = []
    monkeypatch.setattr(capacity, "resolve_session_account", lambda path, *, agent_family, profile_dir=None: seen.append(profile_dir) or (
        _acct("acct_dir", 10.0) if profile_dir else _acct("acct_default", 10.0)))
    monkeypatch.setattr(capacity, "account_for", REAL_ACCOUNT_FOR)
    assert capacity.account_for("pinned") == "acct_x"
    assert capacity.account_for("ghost") is None and capacity.account_for("nope") is None
    assert capacity.account_for(None) == "acct_default" and capacity.account_for("claude-default") == "acct_default"
    assert capacity.account_for("dir") == "acct_dir" and seen[-1] == "/elsewhere"
    config.write_text("{not json", encoding="utf-8")
    assert capacity.account_for(None) is None


def test_slots_follow_the_project_grant_the_company_room_and_the_swarm_cap(world):
    w = world
    live(w, "fixer"), live(w, "builder")
    with db(w) as conn:
        assert capacity.slots(conn, 16, {}) == (None, None)
        assert capacity.slots(conn, 16, {"project:16": 5}) == (3, 5)
        assert capacity.slots(conn, 16, {"project:16": 2}) == (0, 2)
        assert capacity.slots(conn, 16, {"project:16": 0}) == (0, 0)
    def company(conn):
        conn.execute("INSERT INTO companies (id, name, created_at, updated_at) VALUES (1, 'Acme', 'x', 'x')")
        conn.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at) VALUES (17, '/tmp/c4-17', '/tmp/c4-17', 'Eta', 'test',"
                     " '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z')")
        conn.execute("UPDATE projects SET company_id = 1 WHERE id IN (16, 17)")
        conn.commit()

    go(w, company)
    live(w, "kid", project=17)
    with db(w) as conn:
        assert capacity.slots(conn, 16, {"company:1": 4}) == (1, 3)
        assert capacity.slots(conn, 16, {"company:1": 4, "project:16": 2}) == (0, 2)
        assert capacity.slots(conn, 16, {"company:1": 1}) == (0, 0)
        assert capacity.slots(conn, 17, {}) == (None, None)
    assert go(w, lambda c: capacity.refusal(c, 16, {"project:16": 2}, floors=False)) == "no_slot"
    assert go(w, lambda c: capacity.refusal(c, 16, {"project:16": 3}, floors=False)) is None
    assert go(w, lambda c: capacity.refusal(c, 16, {}, floors=False)) is None


def test_grant_and_pace_are_for_the_ranks_that_hand_out_capacity(world):
    w = world
    assert "not_allowed" in refused(w, "boss", "swarm_card_grant", scope="project:16", slots=1, reason="x")
    assert "not_allowed" in refused(w, "fixer", "swarm_card_pace", project_id=16, pace="asap")
    assert call(w, "boss", "swarm_card_pace", project_id=16, pace="asap")["rules"]["pace"] == "asap"
    assert "not_allowed" in refused(w, "boss", "swarm_card_pace", project_id=17, pace="asap")
    assert "pace must be" in refused(w, "boss", "swarm_card_pace", project_id=16, pace="fast")
    assert "slots is required" in refused(w, "boss", "swarm_card_grant", scope="project:16", reason="x")
    cap = call(w, "boss", "swarm_card_capacity")
    assert set(cap["capacity"]) == {"cpu_busy_pct", "cpu_floor", "usage_max_pct", "usage_floor", "usage_account", "usage_window", "live_bodies", "cap_total", "cap_per_parent", "at"}
    assert capacity.grant_refusal(None, "project:16", None) is None
    assert capacity.grant_refusal({"rank": "alpha"}, "company:3", 3) is None
    assert capacity.grant_refusal({"rank": "company", "company_id": 3}, "project:9", 3) is None
    assert capacity.grant_refusal({"rank": "company", "company_id": 3}, "project:9", 4)
    assert capacity.grant_refusal({"rank": "company", "company_id": 3}, "company:3", 3)
    assert capacity.pace_refusal({"rank": "company", "company_id": 3}, 9, 3) is None and capacity.pace_refusal({"rank": "company", "company_id": 3}, 9, 4)
    assert capacity.pace_refusal({"rank": "alpha"}, 9, None) is None and capacity.pace_refusal({"rank": "task", "project_id": 9}, 9, None)


def test_the_owner_sets_lists_and_removes_grants_and_the_board_route_carries_the_reading(world):
    from src.api import swarm_card_routes as routes
    from src.models.swarm_cards import CardGrantPut

    assert world is not None
    made = asyncio.run(routes.put_grant(CardGrantPut(slots=4, reason="busy night"), scope="project:16"))
    assert made["slots"] == 4 and made["set_by"] == "owner" and made["reason"] == "busy night"
    assert [g["scope"] for g in asyncio.run(routes.get_grants())] == ["project:16"]
    with pytest.raises(Exception):
        CardGrantPut(slots=21, reason="")
    with pytest.raises(Exception) as exc:
        asyncio.run(routes.put_grant(CardGrantPut(slots=None, reason=""), scope="project:0"))
    assert getattr(exc.value, "status_code", None) == 422
    with pytest.raises(Exception) as leak:
        asyncio.run(routes.put_grant(CardGrantPut(slots=1, reason="ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"), scope="project:16"))
    assert getattr(leak.value, "status_code", None) == 422
    gone = asyncio.run(routes.put_grant(CardGrantPut(slots=None, reason="reset"), scope="project:16"))
    assert gone["slots"] is None and asyncio.run(routes.get_grants()) == []
    reading = asyncio.run(routes.get_capacity())
    assert reading["cap_total"] is None and reading["cpu_busy_pct"] is None and reading["usage_floor"] is False
    board = asyncio.run(routes.get_board(scope="project:16", filter="all", done_limit=5, archived="hide"))
    assert board["capacity"]["cap_per_parent"] is None


def test_the_deal_request_names_slots_waiting_cards_and_pace(world):
    w = world
    dealing_step(w)
    live(w, "fixer")
    asleep(w, "kid")
    grant(w, "project:16", 1)
    call(w, "boss", "swarm_card_pace", project_id=16, pace="asap")
    waiting = card(w, "waits")["id"]
    call(w, "boss", "swarm_card_deal", card_id=waiting, agent_id=w.agents["kid"]["id"])
    card(w, "queued")
    w.told.clear()
    assert asyncio.run(dealer.fire(w.state, "16")) == "delivered"
    text = next(t["text"] for t in w.told if t["text"].startswith("Deal request"))
    assert "Slots: 0 of 1 free; 1 card waiting for a slot." in text and "Pace: asap (use every free slot" in text
    assert dealer.request_text("Zeta", ["x"], [], []).count("Slots:") == 0


def test_a_tripped_floor_zeroes_the_slots_in_the_deal_request_and_refuses_a_spawn_with_a_card(world, monkeypatch):
    w = world
    dealing_step(w)
    sent, _, made = _spawn_world(w, monkeypatch)
    card(w, "queued")
    feed([90.0, 95.0, 99.0, 90.0])
    assert capacity.cpu_state()[1]
    w.told.clear()
    assert asyncio.run(dealer.fire(w.state, "16")) == "delivered"
    text = next(t["text"] for t in w.told if t["text"].startswith("Deal request"))
    assert "Slots: 0 free" in text and "Floor: the machine's CPU has been over 85% for two minutes" in text and dealer.FLOOR_TAIL in text
    plan = _spawn(w)
    with pytest.raises(spawn.SpawnRefused, match="CPU has been over 85%"):
        asyncio.run(spawn.run(w.view, caller("boss"), plan))
    assert not made and not sent
    feed([40.0])
    assert asyncio.run(spawn.run(w.view, caller("boss"), plan))["agent_id"] == made[-1]["id"]
    assert dealer.FLOOR_TAIL not in dealer.request_text("Zeta", ["x"], [], [], slots=(1, 2))


def test_rank_rules_carry_the_capacity_text_and_a_company_agent_grants_through_the_tool(world, monkeypatch):
    from src.core.swarm import definition

    w = world
    assert definition.rank_rules("company") == definition.capacity_rules("company")
    assert "or a whole company" in definition.rank_rules("alpha")

    def mint(conn):
        conn.execute("INSERT INTO companies (id, name, created_at, updated_at) VALUES (1, 'Acme', 'x', 'x')")
        conn.execute("UPDATE projects SET company_id = 1 WHERE id = 16")
        conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin, lifecycle, created_at, updated_at)"
                     " VALUES ('uuid-comp', 'cloude', 'cloude_comp', 1788821572, ?, 't', 'created', 'running', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (str(w.repo),))
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'uuid-comp'").fetchone()[0]
        row = store.create_agent(conn, slug="comp", rank="company", job="company", display_name="Comp", repo_dir=str(w.repo), effort="high", parent_id=None,
                                 goal="g", task_type="refactor", company_id=1)
        store.set_session_row(conn, row["id"], row_id)
        store.cas_state(conn, row["id"], "asleep", "awake")
        w.agents["comp"] = store.get_agent(conn, row["id"])
        return row_id

    row_id = go(w, mint)
    infos = asyncio.run(w.view.list_session_infos())
    infos.append(SimpleNamespace(session=SimpleNamespace(id="ses_comp"), tmux_session="cloude_comp", session_row_id=row_id))
    out = call(w, "comp", "swarm_card_grant", scope="project:16", slots=2, reason="x")["grant"]
    assert out["slots"] == 2 and out["set_by"] == f"agent:{w.agents['comp']['id']}"
    secret = "token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    assert "secret" in refused(w, "comp", "swarm_card_grant", scope="project:16", slots=3, reason=secret)
    assert [g["slots"] for g in asyncio.run(card_port.get().policy_read("grants", {}))["grants"]] == [2]
