
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_autosleep_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_autosleep_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.auto_sleep import sleeper as sleeper_mod
from src.core.auto_sleep.idle_clock import IdleClock
from src.core.auto_sleep.pane_listeners import ListenerSnapshot, MeasureError
from src.core.auto_sleep.sleeper import AutoSleeper
from src.core.db import connect, db_path_for
from src.core.conversation_writers import Proc, ProcessTable
from src.core.db_migration import ensure_db_migrated
from src.models.websocket import WSMessageType

NOW = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
CONV = "11111111-2222-3333-4444-55555555555{n}"


class _Watcher:

    def __init__(self):
        self.stale = {}
        self.evidence = None

    def observation_for(self, session_id, now=None):
        if session_id not in self.stale:
            return None
        return SimpleNamespace(stale=self.stale[session_id], evidence=self.evidence)


def clean_evidence(**over):
    from src.core.background_work.measured import STATE_NONE, BackgroundMeasure
    from src.core.subagents.tally import SubagentTally
    from src.core.timers.tally import TimerTally

    fields = dict(agent_family="claude", timers=TimerTally("ok", live=0),
                  subagents=SubagentTally("ok", running=0, total=0, unknown=0),
                  background_open=0, background_process=BackgroundMeasure(STATE_NONE, 0),
                  parked_work=None)
    fields.update(over)
    return SimpleNamespace(**fields)


class _Manager:

    def __init__(self):
        self._registry = SimpleNamespace(sessions={}, subscribers={}, backends={})
        self._attention_watcher = _Watcher()
        self.infos = {}
        self.fresh = clean_evidence()
        self.fresh_reads = 0

    async def _fresh_evidence(self, session_id):
        self.fresh_reads += 1
        if isinstance(self.fresh, Exception):
            raise self.fresh
        return self.fresh

    async def get_session_info(self, session_id):
        return self.infos.get(session_id)


class _Hub:
    def __init__(self):
        self.frames = []

    def publish(self, frame):
        self.frames.append(frame)
        return 1


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.core import session_change_notice

    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}))
    hub = _Hub()
    monkeypatch.setattr(session_change_notice, "get_hub", lambda _state: hub)
    manager = _Manager()
    app_state = SimpleNamespace(session_manager=manager)
    clock = IdleClock()
    calls = []

    async def sleep(uuid):
        calls.append(uuid)
        return SimpleNamespace(status="asleep", session_name=None, code=None)

    w = SimpleNamespace(
        state=state, config=config, hub=hub, manager=manager, clock=clock,
        calls=calls, app_state=app_state, procs=[Proc(1, 0, "t", "launchd")],
        listening=set(), snapshots=[],
    )

    def snapshot():
        w.snapshots.append(1)
        return ListenerSnapshot(frozenset(w.listening), ProcessTable.from_rows(w.procs))

    w.sleeper = AutoSleeper(
        app_state, clock, sleep=sleep,
        config_path=lambda: config, db_path=lambda: db_path_for(state),
        now=lambda: NOW, listeners=snapshot,
    )
    return w


def _add(w, n=1, *, family="claude", status="idle", hint=None, unread=False,
         listening=False, conv=CONV, idle_minutes=61, stale=False, observed=True):
    sid = f"ses_{n}"
    name = f"carnivore_s{n}"
    uuid = f"row-uuid-{n}"
    with connect(db_path_for(w.state), create=False) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, claude_session_uuid, title, origin, "
            "lifecycle, lifecycle_source, agent_type, created_at, updated_at) "
            "VALUES (?, 'cloude', ?, ?, '/Users/x/p', ?, 't', 'created', "
            "'running', 'tmux_list', 'claude', '2026-09-01T00:00:00Z', "
            "'2026-09-01T00:00:00Z')",
            (uuid, name, 1790090835 + n, conv.format(n=n) if conv else None),
        )
        row_id = int(cur.lastrowid)
        conn.commit()
    pane, shell, server = 1000 + n, 2000 + n, 3000 + n
    w.procs += [Proc(pane, 1, "t", "claude"), Proc(shell, pane, "t", "zsh"),
                Proc(server, shell, "t", "node")]
    if listening:
        w.listening.add(server)
    w.manager._registry.sessions[sid] = object()
    w.manager._registry.backends[sid] = SimpleNamespace(pid=pane)
    w.manager.infos[sid] = SimpleNamespace(
        session=SimpleNamespace(id=sid), tmux_session=name, label=f"label {n}",
        agent_family=family, activity_status=status, activity_hint=hint,
        unread=unread, local_servers=[], session_row_id=row_id,
    )
    if observed:
        w.manager._attention_watcher.stale[sid] = stale
    w.clock.observe(sid, f"{name}@1", "idle", None, NOW - timedelta(minutes=idle_minutes))
    return sid, uuid


def _run(w):
    return asyncio.run(w.sleeper.pass_once())


def _config(w, **block):
    w.config.write_text(json.dumps(block))


def test_baseline_an_idle_agent_session_is_put_to_sleep(world):
    sid, uuid = _add(world)
    assert _run(world) == [uuid]
    assert world.calls == [uuid]
    frame = world.hub.frames[-1]
    assert frame["type"] == WSMessageType.SESSION_AUTO_SLEPT
    assert frame["session_name"] == "label 1" and frame["idle_minutes"] == 60
    assert world.clock.idle_ids() == []


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"idle_minutes": 59}, "not idle long enough"),
        ({"family": "terminal"}, "terminal family"),
        ({"family": None}, "family not determined"),
        ({"status": "question"}, "not at rest"),
        ({"status": "unknown"}, "unknown never counts"),
        ({"hint": "shell"}, "a shell command still running"),
        ({"unread": True}, "unread output"),
        ({"listening": True}, "a TCP listener in the pane's process tree"),
        ({"stale": True}, "stale observation"),
        ({"observed": False}, "no observation at all"),
        ({"conv": None}, "no conversation id to resume"),
    ],
)
def test_each_condition_alone_blocks(world, kwargs, why):
    _add(world, **kwargs)
    assert _run(world) == [], why
    assert world.calls == [] and world.hub.frames == []


def test_the_toggle_off_blocks(world):
    _config(world, auto_sleep={"enabled": False})
    _add(world)
    assert _run(world) == []


def test_the_minutes_are_read_from_the_setting(world):
    _config(world, auto_sleep={"idle_minutes": 90})
    _add(world, idle_minutes=80)
    assert _run(world) == []
    _config(world, auto_sleep={"idle_minutes": 75})
    assert len(_run(world)) == 1


def test_a_browser_attached_blocks(world):
    sid, _ = _add(world)
    world.manager._registry.subscribers[sid] = [object()]
    assert _run(world) == []


def test_a_pinned_idle_session_is_slept_and_a_keep_awake_one_is_not(world):
    _, kept = _add(world, 1)
    _, pinned = _add(world, 2)
    _config(world, auto_sleep={"keep_awake": [kept], "pinned_by_device": {
        "device-mac0001": ["carnivore_s1", "carnivore_s2"]}},
        ui_preferences={"revision": 1, "values": {
            "sidebar_arrangement": {"pinned": ["carnivore_s1", "carnivore_s2"]},
            "drawer_arrangement": {"v": 1, "pinned": [kept, pinned]}}})
    assert _run(world) == [pinned]


def test_keep_awake_blocks(world):
    _, uuid = _add(world)
    _config(world, auto_sleep={"keep_awake": [uuid]})
    assert _run(world) == []


def test_a_refused_sleep_publishes_nothing_and_keeps_the_clock(world):
    sid, _ = _add(world)

    async def refuse(uuid):
        return SimpleNamespace(status="refused", code="presence_unknown", session_name=None)

    world.sleeper._sleep = refuse
    assert _run(world) == []
    assert world.hub.frames == []
    assert world.clock.idle_ids() == [sid]


def test_a_session_gone_from_the_registry_is_pruned(world):
    sid, _ = _add(world)
    del world.manager._registry.sessions[sid]
    assert _run(world) == []
    assert world.clock.idle_ids() == []


def test_the_pass_is_bounded(world):
    for n in range(1, sleeper_mod.MAX_SLEEPS_PER_PASS + 3):
        _add(world, n=n)
    assert len(_run(world)) == sleeper_mod.MAX_SLEEPS_PER_PASS


def test_an_unreadable_config_does_nothing(world):
    _add(world)
    world.config.write_text("{not json")
    assert _run(world) == []


def test_a_listener_outside_the_pane_tree_does_not_keep_it_awake(world):
    _add(world)
    world.procs.append(Proc(4242, 1, "t", "node"))
    world.listening.add(4242)
    assert _run(world) == ["row-uuid-1"]


def test_the_listener_of_one_session_keeps_only_that_session_awake(world):
    _add(world, n=1, listening=True)
    _add(world, n=2)
    assert _run(world) == ["row-uuid-2"]
    assert len(world.snapshots) == 1


def test_no_snapshot_is_taken_when_no_session_reaches_the_check(world):
    sid, _ = _add(world)
    world.manager._registry.subscribers[sid] = [object()]
    assert _run(world) == []
    assert world.snapshots == []


@pytest.mark.parametrize("how", ["no backend", "pane pid unknown", "snapshot fails",
                                 "pane pid not in the table"])
def test_a_listener_check_that_cannot_measure_does_not_sleep(world, how):
    sid, _ = _add(world)
    if how == "no backend":
        del world.manager._registry.backends[sid]
    elif how == "pane pid unknown":
        world.manager._registry.backends[sid] = SimpleNamespace(pid=None)
    elif how == "snapshot fails":
        def broken():
            raise MeasureError("lsof exited 2")

        world.sleeper._take_listeners = broken
    else:
        world.manager._registry.backends[sid] = SimpleNamespace(pid=999999)
    assert _run(world) == []
    assert world.calls == []




def _add_unread(w, *, idle_minutes):
    sid, uuid = _add(w, status="finished_unread", unread=True, idle_minutes=idle_minutes)
    w.clock.forget(sid)
    w.clock.observe(sid, "carnivore_s1@1", "idle", None,
                    NOW - timedelta(minutes=idle_minutes), unread=True)
    return sid, uuid


def test_unread_blocks_sleep_when_the_setting_is_on_however_long_it_idled(world):
    _config(world, auto_sleep={"unread_blocks_sleep": True})
    _add_unread(world, idle_minutes=24 * 60)
    assert _run(world) == []
    assert world.calls == []


def test_unread_may_sleep_after_the_plain_limit_by_default(world):
    _, uuid = _add_unread(world, idle_minutes=61)
    assert _run(world) == [uuid]


def test_unread_below_a_longer_limit_is_not_slept_even_past_the_plain_one(world):
    _config(world, auto_sleep={"unread_blocks_sleep": False, "unread_idle_minutes": 180})
    _add_unread(world, idle_minutes=120)
    assert _run(world) == []


def test_the_unread_limit_is_configurable(world):
    _config(world, auto_sleep={"unread_blocks_sleep": False, "unread_idle_minutes": 90})
    _, uuid = _add_unread(world, idle_minutes=91)
    assert _run(world) == [uuid]


def test_a_session_read_late_gets_its_plain_minutes_from_the_reading(world):
    _config(world, auto_sleep={"unread_blocks_sleep": False})
    sid, _ = _add_unread(world, idle_minutes=600)
    world.clock.observe(sid, "carnivore_s1@1", "idle", None,
                        NOW - timedelta(minutes=5), unread=False)
    world.manager.infos[sid].unread = False
    world.manager.infos[sid].activity_status = "idle"
    assert _run(world) == []
    world.clock.observe(sid, "carnivore_s1@1", "idle", None, NOW, unread=False)
    assert world.clock.sleep_seconds(sid, NOW, unread=False) == 5 * 60


def test_unread_sleep_still_honours_every_other_condition(world):
    _config(world, auto_sleep={"unread_blocks_sleep": False})
    _add(world, status="finished_unread", unread=True, listening=True)
    world.clock.forget("ses_1")
    world.clock.observe("ses_1", "carnivore_s1@1", "idle", None,
                        NOW - timedelta(minutes=300), unread=True)
    assert _run(world) == []


@pytest.mark.parametrize(("rank", "alerts"), [("alpha", 0), ("company", 0), ("project", 0), ("feature", 1), ("task", 1)])
def test_leader_swarm_agents_sleep_without_an_alert_on_any_channel(world, monkeypatch, rank, alerts):
    from src.core.auto_sleep import swarm_rule
    from src.core.notifications import contracts

    sid, uuid = _add(world, idle_minutes=100000)
    emitted = []
    contracts.install_sink(emitted.append)
    slept = []

    async def sleep_agent(_state, agent_id):
        slept.append(agent_id)
        return SimpleNamespace(status="asleep", session_name=None, code=None)

    monkeypatch.setattr(swarm_rule, "sleep_agent", sleep_agent)
    with connect(db_path_for(world.state), create=False) as conn:
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO swarm_agents (slug, rank, display_name, job, repo_dir, memory_scope, session_row_id, effort,"
            " character_seed, color_slot, thread_key, state, created_at, updated_at) VALUES"
            " ('a', ?, 'A', 'j', '/x', 'local', ?, 'high', 1, 1, 'tk', 'awake', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
            (rank, row_id))
        conn.commit()
    assert _run(world) == [uuid]
    assert len(slept) == 1
    contracts.uninstall_sink()
    assert len(world.hub.frames) == alerts and len(emitted) == alerts


def test_an_early_return_clears_last_passes_holds(world):
    world.sleeper.holds = {"ses_old": ("carnivore_old", object())}
    _config(world, auto_sleep={"enabled": False})
    assert _run(world) == []
    assert world.sleeper.holds == {}
