
from __future__ import annotations

import pytest

from src.cplugs.huddle import lifecycle
from src.cplugs.huddle.nudge import lines, planning, settings

TEXTS = settings.read({}).texts


def make_row(**over) -> dict:
    base = {"id": 1, "state": "open", "kind": "", "created_by": "joe", "joe_seq": 0, "claude_read_seq": 0, "claude_working": 0,
            "told_seq": 0, "swarm_ref": "", "card_holder": None, "card_queued": 0, "review_action": None, "look_parts": None,
            "nudge_count": None, "nudge_last_at": None, "nudge_stalled_at": None, "title": "", "text": "ship it", "position": 0,
            "list_key": "12", "deleted": 0}
    return {**base, **over}


def where(row: dict, asking: bool = False, **kw) -> str:
    return lifecycle.position(row, lifecycle.status(row, asking), **kw)


@pytest.mark.parametrize("over,asking,kw,expected", [
    ({}, False, {"idle": True}, "agent_idle"),
    ({}, False, {"idle": False}, "agent_active"),
    ({"claude_working": 1}, False, {"idle": True}, "agent_idle"),
    ({}, False, {"idle": True, "session_state": "working"}, "agent_active"),
    ({}, False, {"idle": True, "session_state": "working_subagent"}, "agent_active"),
    ({}, False, {"idle": True, "session_state": "question"}, "external_wait"),
    ({}, False, {"idle": True, "session_state": "notice"}, "external_wait"),
    ({}, False, {"idle": True, "list_held": True}, "external_wait"),
    ({"kind": "waiting"}, False, {"idle": True}, "external_wait"),
    ({"state": "waiting"}, False, {"idle": True}, "external_wait"),
    ({"card_holder": "agent:3"}, False, {"idle": True}, "external_wait"),
    ({"card_queued": 1}, False, {"idle": True}, "external_wait"),
    ({"swarm_ref": "trust:4:ab"}, False, {"idle": True}, "external_wait"),
    ({"trigger_kind": "at", "trigger_fire_at": 9.0, "trigger_fired_at": None, "trigger_error": None}, False, {"idle": True}, "external_wait"),
    ({"state": "todo"}, False, {"idle": True}, "parked"),
    ({"state": "done"}, False, {"idle": True}, "done"),
    ({"state": "review"}, False, {"idle": True}, "joe_turn"),
    ({}, True, {"idle": True}, "joe_turn"),
    ({"look_parts": '{"action": "tick"}'}, False, {"idle": True}, "joe_turn"),
    ({"look_parts": '{"action": "read"}'}, False, {"idle": True}, "agent_idle"),
    ({"nudge_stalled_at": 5.0}, False, {"idle": True}, "agent_idle"),
    ({"joe_seq": 3}, False, {"idle": True}, "joe_outbox"),
    ({"state": "done", "joe_seq": 3}, False, {"idle": True}, "joe_outbox"),
    ({"state": "todo", "joe_seq": 3}, False, {"idle": True}, "joe_outbox"),
])
def test_position_table(over, asking, kw, expected):
    assert where(make_row(**over), asking, **kw) == expected


def test_a_stall_stamp_owes_no_unstick_action_any_more():
    assert not hasattr(lifecycle, "UNSTICK")
    for status in ("open", "working", "waiting"):
        assert lifecycle.needs_action(status) is None
    assert lifecycle.needs_action("question") == "answer"
    assert lifecycle.row_action(make_row(nudge_stalled_at=5.0), "working") is None


def cand(now: float, quiet_s: float, **over) -> planning.Candidate:
    row = make_row(**over)
    return planning.Candidate(row, lifecycle.status(row, False), now - quiet_s, "b")


def plan(cands, now, **kw):
    kw = {"interval_s": 3600.0, "tries": 3, "session_state": "idle", "list_held": False, **kw}
    return planning.plan(cands, now=now, position=lifecycle.position, **kw)


def test_only_idle_items_past_the_interval_are_nudged():
    now = 100000.0
    quiet, fresh, working_row = cand(now, 3700), cand(now, 600, id=2), cand(now, 3700, id=3, claude_working=1)
    out = plan([quiet, fresh, working_row], now)
    assert [c.id for c in out.nudge] == [1, 3] and out.stall == []


def test_a_busy_or_blocked_session_a_held_tell_or_joes_turn_nudges_nothing():
    now = 100000.0
    c = cand(now, 9000)
    for kw in ({"session_state": "working"}, {"session_state": "question"}, {"list_held": True}):
        assert plan([c], now, **kw).nudge == []
    asked = planning.Candidate(make_row(), lifecycle.QUESTION, now - 9000, "b")
    assert plan([asked], now).nudge == []


def test_back_off_is_linear_and_tries_then_one_more_interval_stalls():
    now = 100000.0
    quiet = 9000.0
    second_early = cand(now, quiet, nudge_count=1, nudge_last_at=now - 3600)
    assert plan([second_early], now).nudge == []
    second_due = cand(now, quiet, nudge_count=1, nudge_last_at=now - 7300)
    assert [c.id for c in plan([second_due], now).nudge] == [1]
    last_sent = cand(now, 20000, nudge_count=3, nudge_last_at=now - 3600)
    assert plan([last_sent], now).stall == [] and plan([last_sent], now).nudge == []
    answered_never = cand(now, 30000, nudge_count=3, nudge_last_at=now - 14500)
    out = plan([answered_never], now)
    assert [c.id for c in out.stall] == [1] and out.nudge == []


def test_the_lead_line_names_at_most_five_working_first_and_the_ways_to_answer():
    now = 100000.0
    cands = [cand(now, 3700, id=i, position=i, text=f"item {i}", claude_working=int(i == 6)) for i in range(1, 8)]
    line = lines.claimed_line(cands, now, TEXTS, 5)
    assert line.startswith("huddle nudge: no progress for 61 min on ")
    assert line.index('"item 6" (working: you hold its claim)') < line.index('"item 1" (open)') and "and 2 more" in line and '"item 7"' not in line
    assert "task_manager_progress_set" in line and "task_manager_ask" in line and "review" in line and line.endswith(". ")
    assert "\n" not in line


def test_settings_are_bounded_and_unusable_values_take_the_default():
    assert settings.clamp_number("nudgeMinutes", 5) == 15.0 and settings.clamp_number("nudgeMinutes", 99999) == 1440.0
    assert settings.clamp_number("nudgeMinutes", "x") == 60.0 and settings.clamp_number("nudgeMinutes", True) == 60.0 and settings.clamp_number("nudgeMinutes", 90) == 90.0
    assert settings.clamp_number("nudgeTries", 0) == 1 and settings.clamp_number("nudgeTries", 99) == 10 and settings.clamp_number("nudgeTries", None) == 3
    assert planning.sweep_period_s(15) == 150.0 and planning.sweep_period_s(60) == 300.0 and planning.sweep_period_s(1440) == 300.0


def test_a_waiting_task_is_never_the_nudges_target():
    row = make_row(state="waiting")
    for kw in ({"idle": True}, {"idle": False}, {"idle": True, "session_state": "working"}, {"idle": True, "session_state": "idle"}):
        assert where(row, **kw) == "external_wait" or kw["idle"] is False and where(row, **kw) == "external_wait"
    assert where(make_row(state="waiting", joe_seq=3), idle=True) == "joe_outbox"
    now = 100000.0
    assert plan([cand(now, 20000, state="waiting")], now).nudge == [] and plan([cand(now, 20000, state="waiting")], now).stall == []


def owned(now: float, quiet_s: float, *, state: str = "idle", session_quiet_s: float = 99999.0, key: str = "a", **over) -> planning.Candidate:
    base = cand(now, quiet_s, **over)
    return planning.Candidate(base.row, base.status, base.last_activity, base.basis, session_key=key, session_state=state,
                              session_last=now - session_quiet_s)


def test_an_owned_task_is_due_only_when_its_own_session_is_idle_and_quiet():
    now = 100000.0
    assert [c.id for c in plan([owned(now, 3700)], now, session_state="working").nudge] == [1]
    assert plan([owned(now, 3700, state="working")], now).nudge == []
    assert plan([owned(now, 3700, state="question")], now).nudge == []
    assert plan([owned(now, 3700, state="unknown")], now).nudge == []
    assert [c.id for c in plan([owned(now, 3700, state="finished_unread")], now).nudge] == [1]
    assert plan([owned(now, 3700, session_quiet_s=600)], now).nudge == []


def test_an_owned_task_stalls_after_its_tries_counted_from_the_later_quiet():
    now = 100000.0
    spent = owned(now, 30000, nudge_count=3, nudge_last_at=now - 14500)
    assert [c.id for c in plan([spent], now).stall] == [1]
    assert plan([owned(now, 30000, nudge_count=3, nudge_last_at=now - 14500, state="working")], now).stall == []


def test_stall_line_is_fixed_copy_naming_the_session_and_minutes_only():
    assert lines.stall_line("alex", 5400, 3) == "alex has been idle for 90 min with this task still open, after 3 nudges."
    assert lines.stall_line("", 60, 1).startswith("its session has been idle for 1 min")

def test_every_default_text_is_a_template_the_lines_fill_and_a_custom_one_is_used():
    now = 100000.0
    c = cand(now, 3720, title="ship it")
    custom = {**TEXTS, settings.CLAIMED_TEXT: "look at {items} ({minutes} min), {nope}"}
    assert lines.claimed_line([c], now, custom, 5) == 'look at "ship it" (open) (62 min), {nope} '
    assert not hasattr(settings, "INSTALL_TEXT") and "installText" not in settings.TEXT_KEYS
    assert settings.read({settings.CLAIMED_TEXT: "   "}).texts[settings.CLAIMED_TEXT] == settings.default(settings.CLAIMED_TEXT)
    assert lines.unclaimed_line(c, now, TEXTS).startswith('huddle nudge: "ship it" has sat open and unclaimed for 62 min.')
    assert lines.pickup_line(c, now, TEXTS).startswith("huddle nudge: you have been idle for 62 min and hold no swarm item.")
