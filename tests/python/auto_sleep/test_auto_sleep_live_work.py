
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.auto_sleep.live_work import (
    REASON_BACKGROUND, REASON_PARKED, REASON_SUBAGENTS, REASON_TIMERS, REASON_UNMEASURED, hold_for,
)
from src.core.background_work.measured import STATE_RUNNING, STATE_UNKNOWN, BackgroundMeasure
from src.core.subagents.tally import SubagentTally
from src.core.timers.tally import TimerTally
from tests.test_auto_sleep_sleeper import (  # noqa: F401
    _add, _config, _run, clean_evidence, world,
)

FIRE = datetime(2026, 10, 1, 22, 52, tzinfo=timezone.utc)


def test_a_clean_fresh_read_still_sleeps(world):
    _, uuid = _add(world)
    assert _run(world) == [uuid]
    assert world.manager.fresh_reads == 1 and world.sleeper.holds == {}


def test_a_live_timer_blocks_sleep_without_the_coffee_cup(world):
    sid, _ = _add(world)
    _config(world, auto_sleep={"keep_awake": []})
    world.manager._attention_watcher.stale[sid] = False
    world.manager._attention_watcher.evidence = clean_evidence(
        timers=TimerTally("ok", live=2, next_fire_at=FIRE))
    world.manager.fresh = world.manager._attention_watcher.evidence
    assert _run(world) == [] and world.calls == []
    assert world.sleeper.holds[sid][1].reasons == (REASON_TIMERS,)


def test_an_open_background_shell_blocks_sleep(world):
    sid, _ = _add(world)
    world.manager.fresh = clean_evidence(background_process=BackgroundMeasure(STATE_RUNNING, 1))
    assert _run(world) == []
    assert world.sleeper.holds[sid][1].text == "kept awake: background shell running"


def test_a_running_subagent_blocks_sleep(world):
    sid, _ = _add(world)
    world.manager.fresh = clean_evidence(subagents=SubagentTally("ok", running=1, total=3, unknown=0))
    assert _run(world) == []
    assert world.sleeper.holds[sid][1].reasons == (REASON_SUBAGENTS,)


def test_the_fresh_reread_aborts_when_the_cached_observation_said_clean(world):
    sid, _ = _add(world)
    world.manager._attention_watcher.evidence = clean_evidence()
    world.manager.fresh = clean_evidence(timers=TimerTally("ok", live=1, next_fire_at=None))
    assert _run(world) == [] and world.calls == []
    assert world.manager.fresh_reads == 1


def test_the_cached_observation_alone_blocks_before_any_fresh_read(world):
    _add(world)
    world.manager._attention_watcher.evidence = clean_evidence(timers=TimerTally("ok", live=1))
    assert _run(world) == [] and world.manager.fresh_reads == 0


@pytest.mark.parametrize("fresh", [
    RuntimeError("read blew up"),
    None,
    clean_evidence(timers=TimerTally("unchecked")),
    clean_evidence(timers=None),
    clean_evidence(subagents=SubagentTally("unchecked")),
    clean_evidence(background_process=BackgroundMeasure(STATE_UNKNOWN, None)),
    clean_evidence(background_process=None),
])
def test_an_unknown_or_failed_fresh_read_blocks_sleep(world, fresh):
    sid, _ = _add(world)
    world.manager.fresh = fresh
    assert _run(world) == [] and world.calls == []
    assert REASON_UNMEASURED in world.sleeper.holds[sid][1].reasons


def test_no_fresh_reader_wired_blocks_sleep(world):
    sid, _ = _add(world)
    world.manager._fresh_evidence = None
    assert _run(world) == []
    assert world.sleeper.holds[sid][1].reasons == (REASON_UNMEASURED,)


def test_a_codex_session_is_not_held_by_claude_only_reads(world):
    _, uuid = _add(world, family="codex")
    world.manager.fresh = clean_evidence(agent_family="codex", timers=None, subagents=None,
                                         background_process=None)
    assert _run(world) == [uuid]


def test_the_reason_text_names_the_count_and_the_next_fire():
    hold = hold_for(clean_evidence(timers=TimerTally("ok", live=2, next_fire_at=FIRE)),
                    require_measured=True)
    assert hold.text.startswith("kept awake: 2 live timers, next ")
    assert hold.text.endswith(FIRE.astimezone().strftime("%H:%M"))
    assert hold_for(clean_evidence(timers=TimerTally("ok", live=1)),
                    require_measured=True).text == "kept awake: 1 live timer"
    both = hold_for(clean_evidence(
        timers=TimerTally("ok", live=1),
        background_process=BackgroundMeasure(STATE_RUNNING, 2)), require_measured=True)
    assert both.text == "kept awake: 1 live timer; 2 background shells running"
    assert both.reasons == (REASON_TIMERS, REASON_BACKGROUND)


def test_a_parked_subagents_work_holds_and_unmeasured_parked_work_holds():
    live = SimpleNamespace(is_live=True, is_unmeasured=False)
    unmeasured = SimpleNamespace(is_live=False, is_unmeasured=True)
    assert hold_for(clean_evidence(parked_work=live), require_measured=True).reasons == (REASON_PARKED,)
    assert hold_for(clean_evidence(parked_work=unmeasured),
                    require_measured=True).reasons == (REASON_UNMEASURED,)


def test_the_cached_judgment_treats_a_missing_field_as_no_reason():
    bare = SimpleNamespace(agent_family="claude")
    assert hold_for(bare, require_measured=False) is None
    assert hold_for(bare, require_measured=True) is not None
    assert hold_for(None, require_measured=True) is None


def test_the_listing_stamps_the_hold_from_the_observation_and_nulls_the_rest():
    from src.api.sleep_hold_listing import sleep_hold_for

    now = datetime.now(timezone.utc)
    info = SimpleNamespace(agent_family="claude", session=SimpleNamespace(id="ses_1"))
    watcher = SimpleNamespace(observation_for=lambda sid, now=None: SimpleNamespace(
        stale=False, evidence=clean_evidence(timers=TimerTally("ok", live=3))))
    hold = sleep_hold_for(watcher, info, now)
    assert hold.reasons == [REASON_TIMERS] and hold.text == "kept awake: 3 live timers"
    stale = SimpleNamespace(observation_for=lambda sid, now=None: SimpleNamespace(stale=True, evidence=None))
    assert sleep_hold_for(stale, info, now) is None and sleep_hold_for(None, info, now) is None
    assert sleep_hold_for(watcher, SimpleNamespace(agent_family="terminal",
                                                   session=info.session), now) is None


def test_get_auto_sleep_reports_the_sessions_held_with_their_reason():
    from src.api.auto_sleep_routes import _holding
    from src.core.auto_sleep.live_work import SleepHold

    sleeper = SimpleNamespace(holds={"ses_1": ("carnivore_a", SleepHold(
        reasons=(REASON_TIMERS,), text="kept awake: 2 live timers, next 18:52"))})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auto_sleeper=sleeper)))
    entry = _holding(request)[0]
    assert (entry.session, entry.reasons, entry.text) == (
        "carnivore_a", ["timers"], "kept awake: 2 live timers, next 18:52")
    assert _holding(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))) == []


def test_the_fresh_read_drops_the_shared_process_snapshot_before_reading():
    from src.core.attention.watcher import WatchTarget
    from src.core.attention_reader import AttentionEvidenceReader

    manager = SimpleNamespace(_registry=SimpleNamespace(backends={}))
    reader = AttentionEvidenceReader(manager, lambda session_id: (None, None))
    reader._snapshot_taken_at = 9e9
    assert reader.read_fresh(WatchTarget("ses_1", "k"), datetime.now(timezone.utc)) is None
    assert reader._snapshot_taken_at == 0.0
