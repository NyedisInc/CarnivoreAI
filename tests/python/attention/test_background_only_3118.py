
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from src.core.attention import output_holders
from src.core.attention.display import to_display
from src.core.attention.evidence import (
    ACTIVITY_HINT_BACKGROUND,
    FAMILY_CLAUDE,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    Evidence,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.background_work.measured import (
    STATE_RUNNING,
    BackgroundMeasure,
    ProcessSnapshot,
    measure_background,
)
from src.core.background_work.servers import TTL_SECONDS, ServerProbe
from src.core.conversation_writers import MeasureError
from src.core.session_status import LIVENESS_LIVE, STATUS_UNKNOWN, STATUS_WORKING_SUBAGENT
from src.core.subagents import parked_work
from src.core.unread_store import UnreadStore
from tests.python.background_work.test_parked_agent_not_leftover_3101 import PARKED_AT, _lay, _verdict_at
from tests.test_attention_background_shell_busy import (
    CAPTURED_REGISTRY,
    OBSERVED_AT,
    _captured_transcript,
)
from tests.test_attention_side_effects import EPOCH, TARGET, TMUX_NAME, wired  # noqa: F401
from tests.test_subagent_parked_work import _at, _Probe


def _resolve(*, measure=None, registry_overrides=None, **facts_overrides):
    raw = dict(CAPTURED_REGISTRY, **(registry_overrides or {}))
    facts = classify_transcript_records(_captured_transcript())
    facts = dataclasses.replace(facts, **facts_overrides) if facts_overrides else facts
    return resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=parse_registry_record(raw, path_pid=54252), transcript=facts, pane=None, now=OBSERVED_AT,
        background_process=measure,
    ))


def test_a_main_agent_shell_at_rest_is_working_subagent_with_the_background_hint():
    verdict = _resolve()
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)
    assert verdict.activity_hint == ACTIVITY_HINT_BACKGROUND
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == STATUS_WORKING_SUBAGENT


def test_a_running_shell_that_is_not_a_server_still_spins():
    assert _resolve(measure=BackgroundMeasure(STATE_RUNNING, 1, servers=0)).activity_hint == ACTIVITY_HINT_BACKGROUND


def test_a_parked_subagent_on_its_own_shell_is_the_gray_spinner_not_green(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    verdict, parked, _skip = _verdict_at(_lay(tmp_path, until=PARKED_AT), _at(PARKED_AT), live=True)
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)
    assert verdict.activity_hint == ACTIVITY_HINT_BACKGROUND


def test_a_busy_record_with_a_non_server_shell_stays_green_not_gray():
    verdict = _resolve(measure=BackgroundMeasure(STATE_RUNNING, 1, servers=0), registry_overrides={"status": "busy"})
    assert verdict.state == STATE_BUSY
    assert verdict.activity_hint is None


def test_a_busy_record_with_a_parked_subagent_stays_green_not_gray(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    verdict, _parked, _skip = _verdict_at(_lay(tmp_path, until=PARKED_AT), _at(PARKED_AT), live=True, status="busy")
    assert verdict.state == STATE_BUSY
    assert verdict.activity_hint is None


def test_background_agents_or_workflows_are_agent_work_and_stay_green():
    for field in ("pending_background_agents", "pending_workflows", "open_async_agents"):
        verdict = _resolve(**{field: 1})
        assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS), field
        assert verdict.activity_hint is None, field


def test_a_shell_that_listens_on_a_port_is_a_server_and_the_session_reads_done():
    verdict = _resolve(measure=BackgroundMeasure(STATE_RUNNING, 1, servers=1))
    assert (verdict.state, verdict.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED)
    assert verdict.activity_hint is None


def test_one_server_beside_one_job_is_still_a_spinner():
    verdict = _resolve(measure=BackgroundMeasure(STATE_RUNNING, 2, servers=1))
    assert verdict.activity_hint == ACTIVITY_HINT_BACKGROUND


def test_a_busy_record_keeps_the_claims_even_when_the_shell_is_a_server():
    verdict = _resolve(measure=BackgroundMeasure(STATE_RUNNING, 1, servers=1), registry_overrides={"status": "busy"})
    assert verdict.state == STATE_BUSY


def test_measure_background_counts_the_shells_whose_tree_listens():
    mark = "/bin/zsh -c source /u/.claude/shell-snapshots/snapshot-zsh-1.sh && "
    snapshot = ProcessSnapshot(
        parents={7: 1, 20: 7, 21: 20, 30: 7},
        commands={20: mark + "npm run dev", 21: "node server.js", 30: mark + "sleep 600"},
    )
    seen = []
    probe = ServerProbe(holds_listener=lambda pid: seen.append(pid) or pid == 21)
    measure = measure_background(7, snapshot, stdout_of=lambda pid: None, is_server=probe.is_server)
    assert (measure.state, measure.count, measure.servers) == (STATE_RUNNING, 2, 1)
    assert sorted(set(seen)) == [20, 21, 30]


def test_the_listener_answer_is_cached_and_a_failed_read_never_flaps_it():
    now = [100.0]
    calls = []
    broken = [False]

    def holds(pid):
        calls.append(pid)
        if broken[0]:
            raise MeasureError("libproc unavailable")
        return True

    probe = ServerProbe(holds_listener=holds, clock=lambda: now[0])
    assert probe.is_server(5, "sh -c x", [5]) is True
    for _ in range(10):
        now[0] += 2
        assert probe.is_server(5, "sh -c x", [5]) is True
    assert len(calls) == 1 or now[0] - 100 >= TTL_SECONDS
    broken[0] = True
    now[0] += TTL_SECONDS + 1
    assert probe.is_server(5, "sh -c x", [5]) is True
    assert ServerProbe(holds_listener=holds).is_server(9, "sh -c y", [9]) is False


def test_the_finished_flag_fires_once_when_the_background_work_ends():
    key = UnreadStore.compose_key("cloude_Sauna", 1757000000)
    ledger = AttentionLedger()
    working = _resolve()
    rest = _resolve(measure=BackgroundMeasure(STATE_RUNNING, 1, servers=1))
    start = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert ledger.observe(key, working, start) is None
    for i in range(1, 6):
        assert ledger.observe(key, working, start.replace(second=2 * i)) is None
    edge = ledger.observe(key, rest, start.replace(second=20))
    assert edge is not None and edge.state == STATE_DONE_IDLE and edge.previous_state == STATE_BUSY
    assert ledger.observe(key, rest, start.replace(second=22)) is None


def test_the_flag_is_set_at_that_edge_unless_the_owner_is_focused_on_the_terminal(wired):  # noqa: F811
    from src.core.attention.viewer_focus import get_tracker
    from src.core.terminal_size import TerminalSizeNegotiator

    manager, effects, _calls = wired
    neg = TerminalSizeNegotiator()
    manager._terminal_size_negotiator = neg
    tracker = get_tracker(manager)
    sid = TARGET.session_id
    neg.set_client_size(sid, "ws", 80, 24, voting=True)
    tracker.report(sid, "ws", False)
    effects.set_unread(TARGET)
    assert manager.unread_writes == [(TMUX_NAME, "auto", True, EPOCH)]
    manager.unread_writes.clear()
    tracker.report(sid, "ws", True)
    effects.set_unread(TARGET)
    assert manager.unread_writes == []
