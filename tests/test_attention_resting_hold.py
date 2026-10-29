
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_RESTING_PROMPT,
    STATE_BUSY,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.pane_markers import classify_pane_tail
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.attention.watcher import (
    RESTING_HOLD_SECONDS,
    AttentionWatcher,
    WatchTarget,
)
from src.core.session_status import LIVENESS_LIVE

START = datetime(2026, 9, 18, 6, 0, 0, tzinfo=timezone.utc)

KEY = "cloude_Argent@1788294271"

RESTING = classify_pane_tail(
    [
        "⏺ Remote Control disconnected",
        "─" * 40,
        "❯ ",
        "─" * 40,
        "  ALEX-Docs | Opus 5 (1M context)",
    ]
)

WORKING = classify_pane_tail(
    [
        "✻ Waiting for 1 background agent to finish",
        "─" * 40,
        "❯ ",
        "─" * 40,
    ]
)

BLANK = classify_pane_tail([])

REGISTRY_PAYLOAD = {
    "sessionId": "90c5c356-e7d1-4151-b385-78eab7f60f4d",
    "cwd": "/Users/alex/Projects/Acme/ALEX-Docs",
    "pid": 91992,
    "startedAt": 1788294281973,
    "version": "2.1.266",
    "kind": "interactive",
    "entrypoint": "cli",
    "tmux": "cloude_Argent:@3.%3",
    "status": "busy",
    "updatedAt": 1788857113338,
    "statusUpdatedAt": 1788857113338,
}


def _busy_evidence(pane, now: datetime) -> Evidence:
    payload = dict(REGISTRY_PAYLOAD)
    payload["statusUpdatedAt"] = int((now - timedelta(minutes=40)).timestamp() * 1000)
    end = now - timedelta(minutes=40)
    return Evidence(
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        registry=parse_registry_record(payload, path_pid=None),
        transcript=TranscriptFacts(
            verdict=FACTS_FOUND,
            pending_background_agents=1,
            pending_field_present=True,
            turn_end_at=end,
            newest_assistant_at=end - timedelta(seconds=1),
            newest_append_at=end,
            detail="the turn ended with 1 background agent pending",
        ),
        pane=pane,
        now=now,
    )


class _Harness:

    def __init__(self) -> None:
        self.now = START
        self.pane = RESTING
        self.verdicts: List[object] = []
        self.target = WatchTarget(session_id="ses_argent", key=KEY)
        self.watcher = AttentionWatcher(
            list_targets=lambda: [self.target],
            read_evidence=self._read,
            raise_toast=lambda *a: None,
            set_unread=lambda *a: None,
            on_busy_edge=lambda *a: None,
            on_observation=self._observe,
            ledger=AttentionLedger(),
            now=lambda: self.now,
            tick_seconds=0.0,
            registry_directory="/nonexistent-for-this-test",
        )

    def _read(self, target: WatchTarget, now: datetime) -> Optional[Evidence]:
        return _busy_evidence(self.pane, now)

    def _observe(self, target: WatchTarget, observation) -> None:
        self.verdicts.append(observation.verdict)

    def tick(self, pane, *, advance: float = 2.0) -> object:
        self.now = self.now + timedelta(seconds=advance)
        self.pane = pane
        asyncio.run(self.watcher.tick_once())
        return self.verdicts[-1]


def test_the_first_sight_of_a_resting_prompt_does_not_veto_anything():
    harness = _Harness()
    verdict = harness.tick(RESTING, advance=0.0)
    assert verdict.state == STATE_BUSY, verdict.detail


def test_two_seconds_of_resting_is_still_not_enough():
    harness = _Harness()
    harness.tick(RESTING, advance=0.0)
    verdict = harness.tick(RESTING, advance=2.0)
    assert verdict.state == STATE_BUSY, verdict.detail


def test_four_seconds_of_continuous_resting_withdraws_the_busy_verdict():
    harness = _Harness()
    harness.tick(RESTING, advance=0.0)
    harness.tick(RESTING, advance=2.0)
    verdict = harness.tick(RESTING, advance=2.0)
    assert verdict.state == STATE_UNKNOWN, verdict.detail
    assert verdict.reason == REASON_RESTING_PROMPT
    assert RESTING_HOLD_SECONDS == 4.0


def test_a_busy_capture_in_the_middle_resets_the_hold():
    harness = _Harness()
    harness.tick(RESTING, advance=0.0)
    harness.tick(RESTING, advance=2.0)
    harness.tick(WORKING, advance=2.0)
    harness.tick(RESTING, advance=2.0)
    verdict = harness.tick(RESTING, advance=2.0)
    assert verdict.state == STATE_BUSY, (
        "a working capture must clear the hold, not pause it: " + verdict.detail
    )


def test_a_capture_we_could_not_read_breaks_the_hold_as_well():
    harness = _Harness()
    harness.tick(RESTING, advance=0.0)
    harness.tick(RESTING, advance=2.0)
    harness.tick(BLANK, advance=2.0)
    harness.tick(RESTING, advance=2.0)
    verdict = harness.tick(RESTING, advance=2.0)
    assert verdict.state == STATE_BUSY, verdict.detail


def test_the_hold_is_kept_per_instance_key_and_not_shared():
    panes: Dict[str, object] = {"a": RESTING, "b": WORKING}
    seen: Dict[str, object] = {}
    targets = [
        WatchTarget(session_id="ses_a", key="cloude_a@1"),
        WatchTarget(session_id="ses_b", key="cloude_b@2"),
    ]
    clock = {"now": START}

    def read(target: WatchTarget, now: datetime) -> Evidence:
        which = "a" if target.session_id == "ses_a" else "b"
        return _busy_evidence(panes[which], now)

    def observe(target: WatchTarget, observation) -> None:
        seen[target.session_id] = observation.verdict

    watcher = AttentionWatcher(
        list_targets=lambda: targets,
        read_evidence=read,
        raise_toast=lambda *a: None,
        set_unread=lambda *a: None,
        on_busy_edge=lambda *a: None,
        on_observation=observe,
        ledger=AttentionLedger(),
        now=lambda: clock["now"],
        tick_seconds=0.0,
        registry_directory="/nonexistent-for-this-test",
    )
    for step in range(3):
        clock["now"] = START + timedelta(seconds=2 * step)
        asyncio.run(watcher.tick_once())

    assert seen["ses_a"].state == STATE_UNKNOWN, seen["ses_a"].detail
    assert seen["ses_a"].reason == REASON_RESTING_PROMPT
    assert seen["ses_b"].state == STATE_BUSY, seen["ses_b"].detail


def test_a_target_that_goes_away_does_not_leave_its_hold_behind():
    harness = _Harness()
    harness.tick(RESTING, advance=0.0)
    harness.tick(RESTING, advance=2.0)
    live = [harness.target]
    harness.watcher._list_targets = lambda: live
    live.clear()
    harness.now = harness.now + timedelta(seconds=2)
    asyncio.run(harness.watcher.tick_once())
    live.append(harness.target)
    verdict = harness.tick(RESTING, advance=2.0)
    assert verdict.state == STATE_BUSY, (
        "a target that left the list must come back with no hold: "
        + verdict.detail
    )
