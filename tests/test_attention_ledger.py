
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.attention.evidence import (
    AttentionVerdict,
    REASON_INPUT,
    REASON_PERMISSION,
    REASON_QUESTION,
    REASON_STREAMING,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    REASON_NO_EVIDENCE,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    STATE_UNKNOWN,
    TIER_PANE,
    TIER_REGISTRY,
    TIER_TRANSCRIPT,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.resolve import DONE_QUIET_SECONDS, SETTLE_SECONDS
from src.core.unread_store import UnreadStore

T0 = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)

KEY = UnreadStore.compose_key("cloude_Garden", 1757000000)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def busy(reason: str = REASON_STREAMING) -> AttentionVerdict:
    return AttentionVerdict(
        state=STATE_BUSY, reason=reason, tier=TIER_REGISTRY, settle_required=False
    )


def done() -> AttentionVerdict:
    return AttentionVerdict(
        state=STATE_DONE_IDLE,
        reason=REASON_TURN_ENDED,
        tier=TIER_REGISTRY,
        pending_background_agents=0,
        settle_required=False,
    )


def needs_user(
    reason: str = REASON_QUESTION, *, settle: bool = True
) -> AttentionVerdict:
    return AttentionVerdict(
        state=STATE_NEEDS_USER,
        reason=reason,
        tier=TIER_PANE if settle else TIER_REGISTRY,
        settle_required=settle,
    )


def unknown() -> AttentionVerdict:
    return AttentionVerdict(
        state=STATE_UNKNOWN, reason=REASON_NO_EVIDENCE, tier=TIER_TRANSCRIPT
    )




def test_first_sight_of_a_key_is_a_baseline_and_raises_nothing():
    ledger = AttentionLedger()
    assert ledger.observe(KEY, done(), T0) is None
    assert ledger.confirmed_state(KEY) == STATE_DONE_IDLE


def test_a_tick_of_already_idle_sessions_after_a_restart_raises_nothing():
    ledger = AttentionLedger()
    keys = [UnreadStore.compose_key("cloude_s%d" % i, 1757000000) for i in range(12)]
    first = [ledger.observe(key, done(), T0) for key in keys]
    assert first == [None] * 12
    second = [ledger.observe(key, done(), at(2)) for key in keys]
    assert second == [None] * 12


def test_the_baseline_state_is_still_news_after_a_real_detour():
    ledger = AttentionLedger()
    assert ledger.observe(KEY, done(), T0) is None
    assert ledger.observe(KEY, busy(), at(2)) is not None
    edge = ledger.observe(KEY, done(), at(4))
    assert edge is not None
    assert edge.state == STATE_DONE_IDLE
    assert edge.previous_state == STATE_BUSY




def test_a_settle_required_verdict_is_held_on_its_first_sighting():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    assert ledger.observe(KEY, needs_user(), at(1)) is None


def test_a_settle_required_verdict_is_still_held_just_under_the_window():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe(KEY, needs_user(), at(1))
    assert ledger.observe(KEY, needs_user(), at(1 + SETTLE_SECONDS - 0.01)) is None


def test_a_settle_required_verdict_transitions_on_the_second_sighting():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe(KEY, needs_user(), at(1))
    edge = ledger.observe(KEY, needs_user(), at(1 + SETTLE_SECONDS))
    assert edge is not None
    assert (edge.state, edge.reason) == (STATE_NEEDS_USER, REASON_QUESTION)


def test_a_different_verdict_in_between_resets_the_settle():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    assert ledger.observe(KEY, needs_user(REASON_QUESTION), at(1)) is None
    assert ledger.observe(KEY, needs_user(REASON_PERMISSION), at(2)) is None
    assert ledger.observe(KEY, needs_user(REASON_QUESTION), at(3)) is None
    edge = ledger.observe(KEY, needs_user(REASON_QUESTION), at(3 + SETTLE_SECONDS))
    assert edge is not None


def test_a_registry_decided_verdict_needs_no_settle_at_all():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    edge = ledger.observe(KEY, needs_user(REASON_INPUT, settle=False), at(0.1))
    assert edge is not None
    assert edge.reason == REASON_INPUT




def test_done_idle_is_held_until_the_transcript_has_been_quiet():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    held = ledger.observe(
        KEY, done(), at(10), last_append_at=at(10 - DONE_QUIET_SECONDS + 0.5)
    )
    assert held is None


def test_done_idle_passes_once_the_quiet_window_has_elapsed():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe(KEY, done(), at(10), last_append_at=at(9))
    edge = ledger.observe(
        KEY, done(), at(12), last_append_at=at(12 - DONE_QUIET_SECONDS)
    )
    assert edge is not None
    assert edge.state == STATE_DONE_IDLE


def test_an_unmeasurable_append_time_skips_the_quiet_gate():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    assert ledger.observe(KEY, done(), at(10), last_append_at=None) is not None


def test_the_quiet_gate_does_not_apply_to_any_other_state():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    edge = ledger.observe(
        KEY, needs_user(REASON_INPUT, settle=False), at(10), last_append_at=at(9.9)
    )
    assert edge is not None




def test_unknown_raises_nothing_and_confirms_nothing():
    ledger = AttentionLedger()
    assert ledger.observe(KEY, unknown(), T0) is None
    assert ledger.confirmed_state(KEY) is None


def test_a_flicker_through_unknown_cannot_manufacture_a_second_edge():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe(KEY, done(), at(4), last_append_at=T0)
    assert ledger.observe(KEY, unknown(), at(6)) is None
    assert ledger.observe(KEY, done(), at(8), last_append_at=T0) is None
    assert ledger.confirmed_state(KEY) == STATE_DONE_IDLE


def test_unknown_does_not_reset_a_settle_in_progress():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    assert ledger.observe(KEY, needs_user(), at(1)) is None
    assert ledger.observe(KEY, unknown(), at(1.5)) is None
    edge = ledger.observe(KEY, needs_user(), at(1 + SETTLE_SECONDS))
    assert edge is not None


def test_unknown_as_the_very_first_reading_still_leaves_a_baseline_owed():
    ledger = AttentionLedger()
    ledger.observe(KEY, unknown(), T0)
    assert ledger.observe(KEY, done(), at(2)) is None
    assert ledger.confirmed_state(KEY) == STATE_DONE_IDLE




def test_a_state_that_holds_raises_exactly_once():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe(KEY, needs_user(), at(1))
    edges = [
        ledger.observe(KEY, needs_user(), at(1 + SETTLE_SECONDS + n))
        for n in range(0, 300, 2)
    ]
    assert len([edge for edge in edges if edge is not None]) == 1


def test_a_new_reason_inside_one_state_is_news():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    first = ledger.observe(KEY, needs_user(REASON_INPUT, settle=False), at(1))
    second = ledger.observe(KEY, needs_user(REASON_PERMISSION, settle=False), at(2))
    assert first is not None and second is not None
    assert second.reason == REASON_PERMISSION


def test_the_emitted_set_is_cleared_when_the_state_actually_moves():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    soft = needs_user(REASON_INPUT, settle=False)
    assert ledger.observe(KEY, soft, at(1)) is not None
    assert ledger.observe(KEY, busy(REASON_SUBAGENTS), at(2)) is not None
    assert ledger.observe(KEY, soft, at(3)) is not None


def test_a_busy_reason_change_is_an_edge_but_the_state_does_not_move():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(REASON_STREAMING), T0)
    edge = ledger.observe(KEY, busy(REASON_SUBAGENTS), at(2))
    assert edge is not None
    assert edge.previous_state == STATE_BUSY




def test_two_instances_of_one_tmux_name_are_two_keys():
    ledger = AttentionLedger()
    old = UnreadStore.compose_key("cloude_a", 1757000000)
    new = UnreadStore.compose_key("cloude_a", 1757999999)
    assert old != new
    assert ledger.observe(old, done(), T0) is None
    transition = ledger.observe(new, needs_user(settle=False), at(1))
    assert transition is not None
    assert transition.previous_state is None


def test_forget_drops_the_entry_so_the_next_sighting_is_a_baseline():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.forget(KEY)
    assert ledger.confirmed_state(KEY) is None
    assert ledger.observe(KEY, done(), at(2)) is None


def test_forget_is_idempotent_on_a_key_never_seen():
    ledger = AttentionLedger()
    ledger.forget("never-seen")
    assert ledger.tracked_keys() == ()


def test_tracked_keys_reports_what_the_ledger_is_holding():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe("other@1", busy(), T0)
    assert set(ledger.tracked_keys()) == {KEY, "other@1"}


def test_a_naive_clock_cannot_crash_the_ledger():
    ledger = AttentionLedger()
    ledger.observe(KEY, busy(), T0)
    ledger.observe(KEY, needs_user(), at(1))
    naive = datetime(2026, 9, 13, 12, 0, 30)
    assert ledger.observe(KEY, needs_user(), naive) is None
