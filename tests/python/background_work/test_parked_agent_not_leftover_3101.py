
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet

from src.core.attention import output_holders
from src.core.attention.display import to_display
from src.core.attention.evidence import (
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    TIER_TRANSCRIPT,
)
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.background_work import leftovers as bw_leftovers
from src.core.background_work.listing import ListedProcess
from src.core.background_work.open_count import BackgroundCountReader
from src.core.session_token_usage.cache import IncrementalCache
from src.core.session_status import STATUS_UNKNOWN, STATUS_WORKING_SUBAGENT
from src.core.subagents import parked_work
from src.core.subagents.parent_index import (
    CompletionIndex,
    RecordedEnd,
    decode_index,
    encode_index,
    parked_agent_ids,
    read_completion_index,
)
from src.core.subagents.parked_work import PARKED_LIVE, PARKED_NONE, ParkedWorkReader
from tests.test_subagent_parked_work import CLAUDE_PID, _at, _axes, _clone, _evidence, _Probe, _registry, _write

FIXTURE = json.loads((Path(__file__).parents[2] / "fixtures" / "parked_notice_shapes.json").read_text())
AGENT = "a1b2c3d4e5f607182"
SHELL = "shell0001"
FIRST_SHELL = "bo00ldjlt"
SHELL_PID = 7001
STARTED = "2026-11-21T15:00:00.000Z"
PARKED_AT = "2026-11-21T16:31:00.000Z"
FINISH_AT = "2026-11-21T16:41:00.000Z"


def _leftovers(parent: Path, now: datetime, *, live: bool = True) -> FrozenSet[str]:
    tasks = parent.parent / "tasks"
    reader = BackgroundCountReader(stdout_of=lambda pid: str(tasks / ("%s.output" % SHELL)))
    found = reader.read_leftovers(
        parent, claude_pid=CLAUDE_PID, process_parents={SHELL_PID: CLAUDE_PID} if live else {1: 0},
        process_started_at=_at(STARTED), now=now)
    assert found is not None
    return found


def _verdict_at(parent: Path, now: datetime, *, live: bool, status: str = "shell"):
    registry = _registry(STARTED, now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), status=status, session=FIXTURE["session"])
    skip = _leftovers(parent, now, live=live)
    records = [json.loads(line) for line in parent.read_text().splitlines()]
    facts = classify_transcript_records(records, now=now, window_is_whole_file=True)
    parked = ParkedWorkReader().read(
        None, parent, registry, facts, now, process_started_at=registry.started_at,
        process_parents=lambda: {SHELL_PID: CLAUDE_PID} if live else {1: 0}, skip_task_ids=skip)
    return resolve_attention(_evidence(registry, facts, now, parked)), parked, skip


def _lay(tmp_path: Path, *, until: str, **kwargs: Any) -> Path:
    parent = _write(tmp_path, FIXTURE, until=until, **kwargs)
    (tmp_path / "tasks" / ("%s.output" % SHELL)).write_text("")
    return parent


def _finish_records() -> Dict[str, list]:
    shell_done = json.loads(json.dumps(FIXTURE["shell_done_notice"]).replace(FIRST_SHELL, SHELL))
    shell_done["timestamp"] = "2026-11-21T16:35:00.000Z"
    notices = [_clone(r, "2026-11-21T16:40:00.%03dZ" % (i * 20)) for i, r in enumerate(FIXTURE["final_notice"])]
    return {"parent": [shell_done] + notices + [
        _clone(FIXTURE["parent"][3], "2026-11-21T16:40:05.000Z"),
        _clone(FIXTURE["parent"][4], "2026-11-21T16:40:05.100Z")]}


def test_a_parked_subagent_with_its_shell_alive_reads_working_subagent(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    parent = _lay(tmp_path, until=PARKED_AT)
    now = _at(PARKED_AT)
    verdict, parked, skip = _verdict_at(parent, now, live=True)
    assert skip == frozenset()
    assert parked.state == PARKED_LIVE and SHELL in parked.detail and AGENT in parked.detail
    assert _axes(verdict) == (STATE_BUSY, REASON_SUBAGENTS, TIER_TRANSCRIPT), verdict.detail
    assert to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN) == STATUS_WORKING_SUBAGENT


def test_the_same_moment_reads_finished_when_the_parked_signal_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    monkeypatch.setattr(bw_leftovers, "parked_agent_ids", lambda index, agents: frozenset())
    parent = _lay(tmp_path, until=PARKED_AT)
    verdict, parked, skip = _verdict_at(parent, _at(PARKED_AT), live=True)
    assert skip == frozenset({SHELL})
    assert parked.state == PARKED_NONE
    assert _axes(verdict)[:2] == (STATE_DONE_IDLE, REASON_TURN_ENDED)


def test_after_the_subagent_really_finishes_the_normal_finished_path_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.NOT_HELD))
    extra = _finish_records()
    parent = _lay(tmp_path, until=FINISH_AT, extra_parent=extra["parent"])
    now = _at(FINISH_AT)
    assert bw_leftovers.finished_agent_ids(parent, [AGENT], process_started_at=_at(STARTED), now=now) == {AGENT}
    verdict, parked, skip = _verdict_at(parent, now, live=False, status="idle")
    assert parked.state == PARKED_NONE and skip == frozenset()
    assert _axes(verdict)[:2] == (STATE_DONE_IDLE, REASON_TURN_ENDED)


def test_a_main_agent_shell_with_no_subagent_still_reads_idle_with_a_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.HELD))
    parent = _write(tmp_path, {**FIXTURE, "agents": {}}, until=PARKED_AT,
                    drop_parent=lambda r: "task-notification" in json.dumps(r))
    (tmp_path / "tasks" / ("%s.output" % SHELL)).write_text("")
    verdict, parked, skip = _verdict_at(parent, _at(PARKED_AT), live=True)
    assert parked.state == PARKED_NONE and skip == frozenset()
    assert _axes(verdict)[:2] == (STATE_DONE_IDLE, REASON_TURN_ENDED)


def test_a_parked_notice_whose_shell_is_gone_and_never_resumed_does_not_hold_the_session(tmp_path, monkeypatch):
    monkeypatch.setattr(parked_work, "probe_output_holders", _Probe(output_holders.NOT_HELD))
    parent = _lay(tmp_path, until=PARKED_AT)
    verdict, parked, skip = _verdict_at(parent, _at(PARKED_AT), live=False)
    assert skip == frozenset()
    assert parked.state == PARKED_NONE
    assert _axes(verdict)[:2] == (STATE_DONE_IDLE, REASON_TURN_ENDED)


def test_the_shell_of_a_parked_subagent_is_not_counted_as_a_leftover(tmp_path):
    parent = _lay(tmp_path, until=PARKED_AT)
    shell = ListedProcess(pid=SHELL_PID, start="s", task_id=SHELL, started_at=None, children=0, summary=None)
    finished = bw_leftovers.finished_agent_ids(parent, [AGENT], process_started_at=_at(STARTED), now=_at(PARKED_AT))
    assert finished == frozenset()
    marks = bw_leftovers.owner_finished_by_pid([shell], {SHELL: AGENT}, True, finished)
    assert marks == {SHELL_PID: False}
    assert bw_leftovers.leftover_count(marks) == 0


def test_the_parked_note_is_read_from_the_real_notice_and_the_newest_end_wins(tmp_path):
    records = [FIXTURE["parent"][1], FIXTURE["parent"][2]]
    index = _scan(tmp_path, records)
    assert index.by_agent_id[AGENT].parked and index.by_agent_id[AGENT].status == "completed"
    assert parked_agent_ids(index, [AGENT, "other"]) == frozenset({AGENT})
    later = _scan(tmp_path, records + [_clone(FIXTURE["final_notice"][0], "2026-11-21T16:40:00.000Z")])
    assert not later.by_agent_id[AGENT].parked
    quoted = json.loads(json.dumps(FIXTURE["final_notice"][0]))
    quoted["content"] = quoted["content"].replace(
        "<result>redacted</result>", "<result>the note says This agent stopped with background work of its own still running</result>")
    assert not _scan(tmp_path, [quoted]).by_agent_id[AGENT].parked


def test_the_parked_flag_survives_the_persisted_codec(tmp_path):
    index = _scan(tmp_path, [FIXTURE["parent"][1]])
    again = decode_index(encode_index(index))
    assert again.by_agent_id == index.by_agent_id
    assert again.by_agent_id[AGENT] == RecordedEnd(index.by_agent_id[AGENT].at, "completed", True)


def _scan(tmp_path: Path, records: list) -> CompletionIndex:
    path = tmp_path / ("scan-%d.jsonl" % len(list(tmp_path.glob("scan-*.jsonl"))))
    path.write_text("".join(json.dumps(r) + "\n" for r in records).replace("{TASKS}", "/t").replace("{SESSION}", "s"))
    index = read_completion_index(path, cache=IncrementalCache())
    assert index is not None
    return index
