
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List, Optional

import pytest

from src.core.attention.turn_counts import KIND_MONITOR
from src.core.subagents import files, stall
from src.core.subagents.parked_launches import OpenLaunch
from src.core.subagents.stall import STALL_AFTER, STALL_NOTIFY_AFTER, read_marked, stalled_seconds
from src.core.subagents.stall_notice import make_stall_notice_raiser
from src.core.subagents.tally import SubagentTallyCache
from src.models import Toast
from tests.helpers.subagent_fixture import A, B, CONV, E, F, I, build_corpus


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 26, hour, minute, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh():
    files.reset_caches_for_tests()
    yield
    files.reset_caches_for_tests()


@pytest.fixture
def parent(tmp_path):
    return build_corpus(tmp_path / "projects")


def _monitor(agent: str, deadline: Optional[datetime]) -> OpenLaunch:
    return OpenLaunch(agent_id=agent, kind=KIND_MONITOR, task_id="bmon00001",
                      launched_at=_at(11, 30), deadline=deadline)


def _marks(parent, now: datetime, launches) -> dict:
    real = stall.conversation_launches
    stall.conversation_launches = lambda _path: launches
    try:
        result = read_marked(parent, conversation_uuid=CONV, now=now)
    finally:
        stall.conversation_launches = real
    return {row.id: row.stalled_seconds for row in result.subagents}


def test_a_running_agent_quiet_for_the_stall_limit_is_stalled_and_a_fresh_one_is_not(parent):
    assert _marks(parent, _at(12, 0), [])[B] is None
    marks = _marks(parent, _at(12, 4), [])
    assert marks[B] == 6 * 60
    assert marks[F] == 9 * 60, "F wrote at 11:55 and is running too"


def test_done_and_unknown_agents_are_never_stalled(parent):
    marks = _marks(parent, _at(12, 4), [])
    assert marks[B] is not None, "the control agent is stalled, so the rows below really were judged"
    assert marks[A] is None and marks[E] is None


def test_an_agent_with_an_armed_monitor_inside_its_deadline_is_never_stalled(parent):
    marks = _marks(parent, _at(12, 4), [(_monitor(B, _at(12, 30)), False)])
    assert marks[B] is None
    assert marks[F] == 9 * 60, "the exemption is B's alone"


@pytest.mark.parametrize("deadline,retired", [
    (_at(12, 3), False),
    (None, False),
    (_at(12, 30), True),
])
def test_a_monitor_that_is_expired_persistent_or_retired_does_not_excuse_the_silence(parent, deadline, retired):
    assert _marks(parent, _at(12, 4), [(_monitor(B, deadline), retired)])[B] == 6 * 60


def test_an_unreadable_launch_ledger_marks_nothing(parent):
    assert _marks(parent, _at(12, 4), [])[B] is not None
    assert set(_marks(parent, _at(12, 4), None).values()) == {None}


def test_the_decision_is_pure_and_its_limits_are_the_named_constants():
    now = _at(12, 0)
    quiet = now - STALL_AFTER
    assert stalled_seconds(status="running", last_activity_at=quiet, waiting_on_monitor=False, now=now) == 300
    assert stalled_seconds(status="running", last_activity_at=quiet + timedelta(seconds=1),
                           waiting_on_monitor=False, now=now) is None
    assert stalled_seconds(status="unknown", last_activity_at=quiet, waiting_on_monitor=False, now=now) is None
    assert (STALL_AFTER, STALL_NOTIFY_AFTER) == (timedelta(minutes=5), timedelta(minutes=15))


def test_the_tally_counts_stalls_and_lists_only_those_past_the_notify_limit(parent):
    root = parent.parents[1]
    soon = SubagentTallyCache(projects_dir=root).tally("claude", CONV, None, None, _at(12, 4))
    assert soon.stalled == 3 and soon.long_stalled == ()
    late = SubagentTallyCache(projects_dir=root).tally("claude", CONV, None, None, _at(12, 14))
    assert {a.agent_id for a in late.long_stalled} == {B, F, I}
    assert late.stalled == 3 and late.running == 3, "a stalled agent is still counted running"
    mid = SubagentTallyCache(projects_dir=root).tally("claude", CONV, None, None, _at(12, 9))
    assert {a.agent_id for a in mid.long_stalled} == {I}, "only the agent quiet 17 minutes crosses at 12:09"




class _Policy:

    def __init__(self, suppresses: bool) -> None:
        self.suppresses = suppresses


class _Manager:

    def __init__(self, muted: bool = False) -> None:
        self._notification_policy_store = object()
        self.muted = muted
        self.toasts: List[dict] = []

    def notification_policy_stamp(self, session_id: str) -> _Policy:
        return _Policy(self.muted)

    def record_toast(self, **kw) -> Toast:
        self.toasts.append(kw)
        return Toast(id=f"t{len(self.toasts)}", session_id=kw["session_id"], kind=kw["kind"],
                     title=kw["title"], body=kw["body"], created_at=datetime.now(timezone.utc))


def _agent(agent_id: str, last: datetime, idle_minutes: int = 16) -> stall.StalledAgent:
    return stall.StalledAgent(agent_id, "build the index", last, idle_minutes * 60)


def test_one_notification_per_stall_filed_under_the_parent_and_replayed_for_a_new_stall():
    manager, sent = _Manager(), []
    raiser = make_stall_notice_raiser(manager, None, lambda sid, payload: sent.append(sid))
    target = SimpleNamespace(session_id="ses_parent")
    stalled = _agent("a1", _at(11, 0))
    raiser(target, [stalled])
    raiser(target, [stalled])
    assert len(manager.toasts) == 1 and sent == ["ses_parent"]
    toast = manager.toasts[0]
    assert (toast["kind"], toast["notify_type"], toast["session_id"]) == ("Notification", "session.agent_stalled", "ses_parent")
    assert "build the index" in toast["body"] and "nothing was stopped" in toast["body"]
    raiser(target, [])
    raiser(target, [_agent("a1", _at(11, 40))])
    assert len(manager.toasts) == 2


def test_a_muted_session_is_not_told_and_unmuting_does_not_replay_the_old_stall():
    manager = _Manager(muted=True)
    raiser = make_stall_notice_raiser(manager, None, lambda *_a: None)
    target = SimpleNamespace(session_id="ses_parent")
    stalled = _agent("a1", _at(11, 0))
    raiser(target, [stalled])
    assert manager.toasts == []
    manager.muted = False
    raiser(target, [stalled])
    assert manager.toasts == [], "the stall was already seen while muted"
    raiser(target, [stalled, _agent("a2", _at(11, 5))])
    assert len(manager.toasts) == 1, "a different stall after unmuting is told"
