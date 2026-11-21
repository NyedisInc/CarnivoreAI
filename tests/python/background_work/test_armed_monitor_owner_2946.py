
from __future__ import annotations

import json
from datetime import datetime

from src.core.attention import output_holders
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_SUBAGENTS,
    STATE_BUSY,
    TIER_TRANSCRIPT,
)
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.background_work.open_count import BackgroundCountReader
from src.core.subagents import parked_work
from src.core.subagents.parked_work import PARKED_LIVE, ParkedWorkReader
from tests.test_subagent_parked_work import (
    CLAUDE_PID,
    FEATURELIST,
    SHELL,
    _Probe,
    _at,
    _axes,
    _evidence,
    _registry,
    _write,
)

STARTED = "2026-09-27T20:00:00.000Z"
TURN_END = "2026-09-27T20:56:13.606Z"
INSIDE = "2026-09-27T20:56:17.000Z"
AFTER = "2026-09-27T21:02:00.000Z"


SHELL_PID = 7001


def _leftovers(parent, now: datetime, started: datetime) -> frozenset:
    tasks = parent.parent / "tasks"
    reader = BackgroundCountReader(stdout_of=lambda pid: str(tasks / ("%s.output" % SHELL)))
    found = reader.read_leftovers(parent, claude_pid=CLAUDE_PID, process_parents={SHELL_PID: CLAUDE_PID},
                                  process_started_at=started, now=now)
    assert found is not None
    return found


def test_an_owner_with_an_armed_monitor_is_not_finished_and_its_shell_is_live_work(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    parent = _write(tmp_path, FEATURELIST, until=INSIDE)
    registry = _registry(STARTED, TURN_END, session=FEATURELIST["session"])
    now = _at(INSIDE)
    skip = _leftovers(parent, now, registry.started_at)
    records = [json.loads(line) for line in parent.read_text().splitlines()]
    facts = classify_transcript_records(records, now=now, window_is_whole_file=True)
    parked = ParkedWorkReader().read(
        FAMILY_CLAUDE, parent, registry, facts, now, process_started_at=registry.started_at,
        process_parents=lambda: {1: 0}, skip_task_ids=skip,
    )
    verdict = resolve_attention(_evidence(registry, facts, now, parked))
    assert _axes(verdict) == (STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT), verdict.detail
    assert parked.state == PARKED_LIVE, parked.detail
    assert skip == frozenset()


def test_once_the_monitor_expires_the_shell_is_a_leftover_again(tmp_path):
    parent = _write(tmp_path, FEATURELIST, until=INSIDE)
    started = _at(STARTED)
    assert _leftovers(parent, _at(AFTER), started) == frozenset({SHELL})
