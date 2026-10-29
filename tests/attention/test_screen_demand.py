
from datetime import datetime, timezone

import pytest

from src.core.attention import screen_demand as sd
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    FAMILY_CODEX,
    REASON_STREAMING,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    TIER_REGISTRY,
    TIER_TRANSCRIPT,
    AttentionVerdict,
    PaneVerdict,
)
from src.core.attention.registry_read import parse_registry_record, registry_for_session

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
PROC_START = "Thu Oct 15 15:52:02 2026"


def record(status="busy", *, version="2.1.300", waiting_for=None, proc_start=PROC_START):
    payload = {"pid": 4242, "sessionId": "u", "cwd": "/w", "startedAt": 1792079000000,
               "version": version, "kind": "interactive", "tmux": "carnivore_a:@1.%1",
               "status": status, "statusUpdatedAt": 1792079000000}
    if waiting_for:
        payload["waitingFor"] = waiting_for
    if proc_start:
        payload["procStart"] = proc_start
    return parse_registry_record(payload, path_pid=None)


def verdict(state=STATE_BUSY, reason=REASON_STREAMING, tier=TIER_REGISTRY, veto=True):
    return AttentionVerdict(state, reason, tier, pane_may_veto=veto)


def decide(**overrides):
    args = dict(family=FAMILY_CLAUDE, registry=record(), identity_proven=True, ask_open=False,
                paneless=verdict(), sticky=False, seconds_since_read=2.0)
    args.update(overrides)
    return sd.decide(**args)


def test_a_proven_busy_record_skips_the_screen():
    assert decide() == sd.ScreenDecision(False, sd.SKIP_RECORD)


@pytest.mark.parametrize("status", ["idle", "shell"])
def test_a_proven_rest_record_skips_the_screen(status):
    rest = verdict(STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY, veto=False)
    assert decide(registry=record(status), paneless=rest).read is False


def test_a_waiting_record_reads():
    got = decide(registry=record("waiting", waiting_for="permission prompt"),
                 paneless=verdict(STATE_NEEDS_USER, "permission", TIER_REGISTRY, veto=False))
    assert got == sd.ScreenDecision(True, sd.READ_WAITING)


def test_no_record_reads():
    absent = registry_for_session(tmux_name="carnivore_a", index={})
    assert decide(registry=absent, identity_proven=None).reason == sd.READ_NO_RECORD


def test_a_codex_session_reads():
    assert decide(family=FAMILY_CODEX) == sd.ScreenDecision(True, sd.READ_CODEX)


def test_the_safety_look_fires_at_thirty_seconds():
    assert decide(seconds_since_read=29.9).read is False
    assert decide(seconds_since_read=sd.SAFETY_LOOK_SECONDS).reason == sd.READ_SAFETY_LOOK
    assert decide(seconds_since_read=None).reason == sd.READ_SAFETY_LOOK


@pytest.mark.parametrize("proven", [None, False])
def test_an_unproven_identity_reads(proven):
    assert decide(identity_proven=proven).reason == sd.READ_IDENTITY_UNPROVEN


@pytest.mark.parametrize("version", ["2.1.282", None])
def test_an_older_or_unversioned_claude_reads(version):
    assert decide(registry=record(version=version)).reason == sd.READ_OLD_CLAUDE


def test_an_open_ask_reads_until_the_screen_shows_it_closed():
    assert decide(ask_open=True).reason == sd.READ_ASK_OPEN


def test_a_question_the_transcript_names_reads():
    ask = verdict(STATE_NEEDS_USER, "question", TIER_TRANSCRIPT, veto=False)
    assert decide(registry=record("idle"), paneless=ask).reason == sd.READ_NEEDS_USER


def test_transcript_claimed_work_reads_for_the_resting_hold():
    claim = verdict(STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert decide(registry=record("idle"), paneless=claim).reason == sd.READ_TRANSCRIPT_WORK


def test_work_the_busy_record_confirms_skips():
    claim = verdict(STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert sd.withdrawable_busy(claim, record("busy")) is False
    assert decide(registry=record("busy"), paneless=claim).read is False


def test_a_sticky_pane_reads():
    assert decide(sticky=True).reason == sd.READ_STICKY


def test_forced_reads_whatever_the_record_says():
    assert decide(forced=True).reason == sd.READ_FORCED


def sticky(**overrides):
    args = dict(text="spinner", pane=PaneVerdict(permission_dialog=False, question_dialog=False,
                                                 resting_prompt=False),
                dialog=None, startup_screen=None, paneless=verdict(), registry=record())
    args.update(overrides)
    return sd.stays_sticky(**args)


def test_a_plain_busy_screen_is_not_sticky():
    assert sticky() is False


def test_a_dialog_a_trust_screen_or_a_failed_capture_stays_sticky():
    assert sticky(dialog=object()) is True
    assert sticky(startup_screen=object()) is True
    assert sticky(text=None) is True
    assert sticky(pane=PaneVerdict(permission_dialog=True)) is True


def test_a_resting_prompt_under_a_busy_record_stays_sticky_for_the_hold():
    resting = PaneVerdict(permission_dialog=False, question_dialog=False, resting_prompt=True)
    assert sticky(pane=resting) is True
    confirmed = verdict(STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT)
    assert sticky(pane=resting, paneless=confirmed) is False


def test_screen_demand_memory_is_bounded_by_the_live_rows():
    demand = sd.ScreenDemand()
    demand.record_read("ses_1", 10.0, True)
    assert demand.since_read("ses_1", 12.5) == 2.5 and demand.sticky("ses_1")
    demand.retain_only({"ses_2"})
    assert demand.since_read("ses_1", 12.5) is None and not demand.sticky("ses_1")
