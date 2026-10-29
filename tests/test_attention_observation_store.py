import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, get_ident
import time

from src.core.attention.codex_reader import (
    CodexEvidence, CodexPaneFacts, CodexRecordFacts, CODEX_RECORD_BUSY,
)
from src.core.attention.evidence import (
    Evidence, FAMILY_CODEX, STATE_UNKNOWN, STATE_NEEDS_USER,
    AttentionVerdict, REASON_PERMISSION, TIER_PANE,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.registry_read import parse_registry_record
from src.core.attention.transcript_facts import TranscriptFacts, FACTS_NO_RECORD
from src.core.attention.watcher import (
    AttentionWatcher, STALL_BACKSTOP_SECONDS, WatchTarget,
)
from src.core.session_status import LIVENESS_LIVE

START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def evidence(now: datetime, **kwargs) -> Evidence:
    return Evidence(
        LIVENESS_LIVE, FAMILY_CODEX, parse_registry_record({}, path_pid=None), TranscriptFacts(verdict=FACTS_NO_RECORD), None, now,
        codex=CodexEvidence(record=CodexRecordFacts(verdict=CODEX_RECORD_BUSY),
                            pane=CodexPaneFacts(approval_dialog=False)), **kwargs,
    )


def watcher(reader, targets, clock, observations=None) -> AttentionWatcher:
    return AttentionWatcher(
        list_targets=lambda: targets, read_evidence=reader,
        raise_toast=lambda *args: None, set_unread=lambda *args: None,
        on_busy_edge=lambda *args: None, ledger=AttentionLedger(),
        now=lambda: clock[0],
        on_observation=(lambda target, value: observations.append(value))
        if observations is not None else None,
    )


def test_expiry_publishes_unknown_once_and_success_recovers() -> None:
    clock, observed, targets = [START], [], [WatchTarget('s', 'pane@1')]
    reading = [True]
    w = watcher(lambda target, now: evidence(now) if reading[0] else None,
                targets, clock, observed)
    asyncio.run(w.tick_once())
    reading[0] = False
    for seconds in (2, 4, 6, 8):
        clock[0] = START + timedelta(seconds=seconds)
        asyncio.run(w.tick_once())
    assert len(observed) == 2
    assert observed[-1].stale
    assert w.observation_for('s').verdict.state == STATE_UNKNOWN
    reading[0] = True
    asyncio.run(w.tick_once())
    assert not w.observation_for('s').stale
    targets.clear()
    asyncio.run(w.tick_once())
    assert w.observation_for('s') is None
    assert not w._ledger.tracked_keys()


def test_slow_cycles_that_observe_the_session_never_go_unknown() -> None:
    clock, observed, targets = [START], [], [WatchTarget('s', 'pane@1')]
    w = watcher(lambda target, now: evidence(now), targets, clock, observed)
    for step in range(1, 6):
        clock[0] = START + timedelta(seconds=9 * step)
        asyncio.run(w.tick_once())
        clock[0] += timedelta(seconds=8)
        assert not w.observation_for('s').stale
        assert w.observation_for('s').verdict.state != STATE_UNKNOWN
    assert not any(value.stale for value in observed)


def test_session_missing_from_three_completed_cycles_goes_unknown() -> None:
    clock, reading = [START], [True]
    w = watcher(lambda target, now: evidence(now) if reading[0] else None,
                [WatchTarget('s', 'pane@1')], clock)
    asyncio.run(w.tick_once())
    reading[0] = False
    for _ in range(2):
        asyncio.run(w.tick_once())
        assert not w.observation_for('s').stale
    asyncio.run(w.tick_once())
    observation = w.observation_for('s')
    assert observation.stale
    assert observation.verdict.state == STATE_UNKNOWN


def test_hung_watcher_trips_the_wall_clock_backstop() -> None:
    clock = [START]
    w = watcher(lambda target, now: evidence(now), [WatchTarget('s', 'pane@1')], clock)
    asyncio.run(w.tick_once())
    clock[0] = START + timedelta(seconds=STALL_BACKSTOP_SECONDS - 1)
    assert not w.observation_for('s').stale
    clock[0] = START + timedelta(seconds=STALL_BACKSTOP_SECONDS)
    observation = w.observation_for('s')
    assert observation.stale
    assert observation.verdict.state == STATE_UNKNOWN


def test_identity_change_resets_codex_resting_hold() -> None:
    clock, identity = [START], [('pane', 1, 'conversation')]

    def read(target, now):
        value = evidence(now, identity=identity[0])
        return replace(value, codex=replace(value.codex,
                       pane=CodexPaneFacts(resting_prompt=True, approval_dialog=False)))

    w = watcher(read, [WatchTarget('s', 'pane@1')], clock)
    asyncio.run(w.tick_once())
    clock[0] += timedelta(seconds=4)
    asyncio.run(w.tick_once())
    assert w.observation_for('s').evidence.resting_prompt_held
    identity[0] = ('pane', 2, 'conversation')
    clock[0] += timedelta(seconds=2)
    asyncio.run(w.tick_once())
    assert not w.observation_for('s').evidence.resting_prompt_held


def test_reads_run_off_loop_with_bounded_parallelism() -> None:
    active, peak = [0], [0]
    lock = Lock()

    def read(target, now):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        return evidence(now)

    w = watcher(read, [WatchTarget(str(i), str(i)) for i in range(8)], [START])
    asyncio.run(w.tick_once())
    assert 1 < peak[0] <= 4


def test_slow_codex_lock_probes_leave_loop_free_and_apply_on_owner(monkeypatch, tmp_path) -> None:
    from src.core.attention import codex_stores
    from src.core.attention.codex_gather import gather_codex_evidence

    locks = tmp_path / "thread-writer-locks"
    locks.mkdir()
    targets = [WatchTarget(str(i), str(i)) for i in range(4)]
    for target in targets:
        (locks / f"{target.session_id}.lock").touch()
    entered, released = Event(), Event()
    reader_threads, apply_threads = [], []
    owner = get_ident()

    def parked_probe(path: str) -> set[int]:
        reader_threads.append(get_ident())
        entered.set()
        assert released.wait(5), "Codex evidence blocked the event loop"
        return set()

    def read(target: WatchTarget, now: datetime) -> Evidence:
        codex = gather_codex_evidence(target.session_id, codex_home=str(tmp_path), now=now)
        return replace(evidence(now), codex=codex)

    monkeypatch.setattr(codex_stores, "_lsof_holders", parked_probe)
    w = watcher(read, targets, [START])
    w._on_observation = lambda *_: apply_threads.append(get_ident())

    async def scenario() -> None:
        task = asyncio.create_task(w.tick_once())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert not task.done()
            released.set()
            await task
        finally:
            released.set()
            await task

    asyncio.run(scenario())
    assert len(reader_threads) == len(apply_threads) == 4
    assert all(thread != owner for thread in reader_threads)
    assert apply_threads == [owner] * 4


def test_boot_permission_settles_and_alerts_once() -> None:
    ledger = AttentionLedger()
    verdict = AttentionVerdict(STATE_NEEDS_USER, REASON_PERMISSION, TIER_PANE,
                               settle_required=True)
    assert ledger.observe('pane', verdict, START) is None
    assert ledger.observe('pane', verdict, START + timedelta(seconds=2)) is not None
    assert ledger.observe('pane', verdict, START + timedelta(seconds=4)) is None


def test_failed_capture_does_not_dismiss_confirmed_permission() -> None:
    clock, captured = [START], [True]
    observed, raised, busy = [], [], []

    def read(target, now):
        value = evidence(now)
        return replace(value, codex=replace(value.codex, pane=(
            CodexPaneFacts(approval_dialog=True) if captured[0] else None)))

    w = watcher(read, [WatchTarget('s', 'pane@1')], clock, observed)
    w._raise_toast = lambda *args: raised.append(args)
    w._on_busy_edge = lambda *args: busy.append(args)
    asyncio.run(w.tick_once())
    clock[0] += timedelta(seconds=2)
    asyncio.run(w.tick_once())
    assert len(raised) == 1
    captured[0] = False
    clock[0] += timedelta(seconds=2)
    asyncio.run(w.tick_once())
    assert observed[-1].verdict.state == STATE_UNKNOWN
    assert not busy
    assert w._ledger.confirmed_state('pane@1') == STATE_NEEDS_USER


def test_missing_identity_measurements_do_not_realert_permission() -> None:
    clock, identity = [START], [('pane', 42, 'conversation')]
    raised = []

    def read(target, now):
        value = evidence(now, identity=identity[0])
        return replace(value, codex=replace(value.codex,
                       pane=CodexPaneFacts(approval_dialog=True)))

    w = watcher(read, [WatchTarget('s', 'pane@1')], clock)
    w._raise_toast = lambda *args: raised.append(args)
    for seconds, measured in (
        (0, ('pane', 42, 'conversation')), (2, ('pane', 42, 'conversation')),
        (4, ('pane', None, None)), (6, ('pane', 42, 'conversation')),
        (8, ('pane', 42, 'conversation')),
    ):
        clock[0], identity[0] = START + timedelta(seconds=seconds), measured
        asyncio.run(w.tick_once())
    assert len(raised) == 1
    assert w.observation_for('s').evidence.identity == ('pane', 42, 'conversation')


def test_target_replaced_during_read_cannot_publish_old_evidence() -> None:
    targets = [WatchTarget('s', 'pane@1')]
    observed = []

    def read(target, now):
        targets[:] = [WatchTarget('s', 'pane@2')]
        return evidence(now)

    w = watcher(read, targets, [START], observed)
    asyncio.run(w.tick_once())
    assert observed == []
    assert w.observation_for('s') is None


def test_same_key_backend_replacement_during_read_is_discarded() -> None:
    targets = [WatchTarget('s', 'pane@1', generation=(123, 42))]
    observed = []

    def read(target, now):
        targets[:] = [WatchTarget('s', 'pane@1', generation=(456, 43))]
        return evidence(now)

    w = watcher(read, targets, [START], observed)
    asyncio.run(w.tick_once())
    assert not observed
    assert w.observation_for('s') is None


def test_invalidate_withdraws_cached_evidence_without_inventing_identity() -> None:
    target = WatchTarget('s', 'pane@1')
    w = watcher(lambda target, now: evidence(now), [target], [START])
    asyncio.run(w.tick_once())
    state = w._ledger.confirmed_state(target.key)
    w.invalidate_session('s')
    assert w.observation_for('s') is None
    assert w._ledger.confirmed_state(target.key) == state
    w.invalidate_session('absent')


def test_done_edge_runs_after_unread_before_toast() -> None:
    from src.core.attention.evidence import STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY
    from src.core.attention.ledger import Transition

    events = []
    target = WatchTarget('s', 'pane@1')
    w = watcher(lambda target, now: evidence(now), [target], [START])
    w._set_unread = lambda *args: events.append('unread')
    w._on_done_edge = lambda *args: events.append('done')
    w._raise_toast = lambda *args: events.append('toast')
    verdict = AttentionVerdict(STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_REGISTRY)
    transition = Transition(target.key, verdict.state, verdict.reason,
                            verdict, STATE_NEEDS_USER, START)
    w._act(target, transition)
    assert events == ['unread', 'done', 'toast']
