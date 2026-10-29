
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List

from src.core.subagents import files as files_mod
from src.core.subagents import parent_index as pi
from src.core.subagents import parked_launches as pl
from src.core.transcript_contract import LineScan, UnknownRecord, complete_lines, typed_record

T0 = "2026-09-26T18:33:00.281Z"
T1 = "2026-09-26T18:34:00.281Z"

UNKNOWN: Dict[str, Any] = {
    "type": "zz-future-record", "timestamp": T1,
    "note": "<task-notification><task-id>ghost</task-id><status>completed</status></task-notification>",
    "toolUseResult": {"agentId": "ghost", "status": "completed"},
    "marks": ["tool_result", "backgroundTaskId", "persistent", "task_type"],
    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_ghost"}]},
}


def _jsonl(records: List[Dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(r).encode() + b"\n" for r in records)


def _notice(agent_id: str, status: str = "completed") -> Dict[str, Any]:
    text = f"<task-notification><task-id>{agent_id}</task-id><status>{status}</status></task-notification>"
    return {"type": "queue-operation", "operation": "enqueue", "content": text,
            "sessionId": "s", "timestamp": T0}


def _sync_result(tool_use_id: str, agent_id: str) -> Dict[str, Any]:
    return {"type": "user", "timestamp": T0, "toolUseResult": {"agentId": agent_id, "status": "completed"},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id}]}}


def _index(data: bytes, *, spawner: bool = False) -> pi.CompletionIndex:
    return pi.scan_parent_lines(io.BytesIO(data), pi.CompletionIndex(), spawner=spawner)[0]


def _shape(index: pi.CompletionIndex) -> Dict[str, Any]:
    return {"a": {k: (v.at, v.status) for k, v in index.by_agent_id.items()},
            "t": {k: (v.at, v.status) for k, v in index.by_tool_use.items()}}


def test_line_scan_resumes_at_the_last_complete_line() -> None:
    data = b'{"a":1}\n{"mark":1}\n{"b":2}\n{"torn'
    scan = LineScan(io.BytesIO(data), (b'"mark"',))
    assert list(scan) == [b'{"mark":1}\n']
    assert scan.offset == len(b'{"a":1}\n{"mark":1}\n{"b":2}\n')


def test_line_scan_names_the_mark_it_found() -> None:
    scan = LineScan(io.BytesIO(b"xx one xx\ntwo\nzip\n"), (b"one", b"two"))
    hits = [(line.strip(), scan.hit) for line in scan]
    assert hits == [(b"xx one xx", b"one"), (b"two", b"two")]


def test_complete_lines_drops_the_cut_head_and_the_torn_tail() -> None:
    assert complete_lines(b'ab\n{"x":1}\n{"y"', at_start=False) == [b'{"x":1}']
    assert complete_lines(b'{"x":1}\n{"y"', at_start=True) == [b'{"x":1}']


def test_unknown_record_is_typed_as_unknown_and_kept() -> None:
    parsed = typed_record(dict(UNKNOWN))
    assert parsed.known is False
    assert isinstance(parsed.record, UnknownRecord)
    assert parsed.raw["toolUseResult"]["agentId"] == "ghost"


def test_unknown_record_changes_nothing_in_the_completion_index() -> None:
    base = _jsonl([_notice("a1"), _sync_result("toolu_1", "a2")])
    with_unknown = _jsonl([_notice("a1"), UNKNOWN, _sync_result("toolu_1", "a2")])
    for spawner in (False, True):
        assert _shape(_index(with_unknown, spawner=spawner)) == _shape(_index(base, spawner=spawner))
    assert "ghost" not in _index(with_unknown, spawner=True).by_agent_id
    assert "toolu_ghost" not in _index(with_unknown, spawner=True).by_tool_use


def test_unknown_record_changes_nothing_in_the_launch_ledger() -> None:
    ledger = pl._Ledger()
    ledger, offset = pl._scan_launches(io.BytesIO(_jsonl([UNKNOWN])), ledger, "ae6d")
    assert (ledger.launches, ledger.stopped) == ({}, set())
    assert offset == len(_jsonl([UNKNOWN]))


def test_unknown_record_changes_nothing_in_the_file_facts(tmp_path: Path) -> None:
    work = {"type": "assistant", "timestamp": T0, "version": "2.1.283", "isSidechain": True,
            "message": {"role": "assistant", "content": []}}
    plain, extended = tmp_path / "agent-aa.jsonl", tmp_path / "agent-bb.jsonl"
    plain.write_bytes(_jsonl([work]))
    extended.write_bytes(_jsonl([work, UNKNOWN]))
    files_mod.reset_caches_for_tests()
    before, after = files_mod.read_line_facts(plain), files_mod.read_line_facts(extended)
    assert (after.state, after.last_at, after.last_type) == (before.state, before.last_at, before.last_type)


def test_notification_text_reads_each_of_the_three_shapes_typed() -> None:
    block = "<task-notification><task-id>x</task-id></task-notification>"
    shapes = [
        {"type": "queue-operation", "operation": "enqueue", "content": block},
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": block}},
        {"type": "user", "origin": {"kind": "task-notification"},
         "message": {"role": "user", "content": block}},
        {"type": "user", "origin": {"kind": "task-notification"},
         "message": {"role": "user", "content": [{"type": "text", "text": "<task-notification>"},
                                                 {"type": "text", "text": "<task-id>x</task-id></task-notification>"}]}},
    ]
    assert [pi._notification_text(r) for r in shapes] == [block, block, block, block]


def test_notification_text_ignores_quotes_and_wrong_shapes() -> None:
    block = "<task-notification><task-id>x</task-id></task-notification>"
    ignored = [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": block}]}},
        {"type": "queue-operation", "operation": "dequeue", "content": block},
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": [block]}},
        {"type": "user", "message": {"role": "user", "content": block}},
    ]
    assert [pi._notification_text(r) for r in ignored] == [None] * 4
