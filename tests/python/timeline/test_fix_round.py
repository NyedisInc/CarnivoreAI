
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.pipeline import contract as C
from src.core.timeline import extract as extract_module
from src.core.timeline import index, plugin
from src.core.timeline.model import Kind, Pos, TimelineEvent
from src.core.transcript_contract.lines import parse_range
from tests.python.timeline.test_cold_index import CONV, _appended, _count, _db, _record, _turn, _write

CANARY = "ZQXJ CANARY words, typed by a person"
CANARY_BARE = "ZQXJ!CANARY!nospaces"


def _removed(path: Path) -> C.FileRemoved:
    return C.FileRemoved(conversation_id=CONV, path=str(path), file_kind="conversation")


def _text_cells(conn: sqlite3.Connection) -> List[str]:
    cells: List[str] = []
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        for row in conn.execute(f"SELECT * FROM {table}"):
            cells.extend(value for value in row if isinstance(value, str))
    return cells


def test_a_file_removed_then_back_is_reindexed_not_skipped(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    data = _write(path, _turn(1) + _turn(10))
    conn, on = _db(), plugin.TIMELINE.on_events
    on(conn, (_appended(path, data),))
    on(conn, (_removed(path),))
    assert conn.execute("SELECT gone FROM files").fetchone()[0] == 1
    on(conn, (_appended(path, data),))
    assert conn.execute("SELECT gone FROM files").fetchone()[0] == 0
    assert _count(conn, "markers") == 0 and _count(conn, "turns") == 2
    small = _write(path, _turn(30))
    on(conn, (_removed(path),))
    on(conn, (_appended(path, small),))
    assert conn.execute("SELECT indexed_to FROM files").fetchone()[0] == len(small)
    assert _count(conn, "turns") == 1 and conn.execute("SELECT turn FROM turns").fetchone()[0] > 0


def test_a_file_rewritten_longer_with_other_lines_is_reindexed(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    first = _write(path, _turn(1))
    conn, on = _db(), plugin.TIMELINE.on_events
    on(conn, (_appended(path, first),))
    second = _write(path, _turn(40) + _turn(50))
    on(conn, (_appended(path, second),))
    assert conn.execute("SELECT opened_at FROM turns ORDER BY start_off").fetchall() == [
        ("2026-01-01T00:00:40.000Z",), ("2026-01-01T00:00:50.000Z",)]
    assert conn.execute("SELECT indexed_to FROM files").fetchone()[0] == len(second)


def test_the_same_file_under_a_redelivery_is_not_called_stale(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    data = _write(path, _turn(1))
    conn, on = _db(), plugin.TIMELINE.on_events
    on(conn, (_appended(path, data),))
    on(conn, (_appended(path, data),))
    assert conn.execute("SELECT calls FROM turns").fetchone()[0] == 1


def _canary_records(c: str = CANARY) -> List[Dict[str, Any]]:
    notice = {"origin": {"kind": "task-notification"}, "message": {"role": "user", "content":
              f"<task-notification><task-id>x1</task-id><tool-use-id>tAgent</tool-use-id><status>{c}</status></task-notification>"}}
    return [
        _record("user", 1, message={"role": "user", "content": f"prompt {c}"}, origin={"kind": "human"}),
        _record("assistant", 2, message={"role": "assistant", "model": f"m {c}", "id": f"msg {c}", "stop_reason": "tool_use",
                "content": [{"type": "thinking", "thinking": c}, {"type": "text", "text": c},
                            {"type": "tool_use", "id": "tRead", "name": "Read", "input": {"file_path": f"/x/{c}"}},
                            {"type": "tool_use", "id": "tAgent", "name": "Agent", "input": {"prompt": c, "description": c,
                                                                                           "subagent_type": c}},
                            {"type": "tool_use", "id": f"t {c}", "name": f"mcp__{c}", "input": {}},
                            {"type": "tool_use", "id": "tLong", "name": "mcp__" + "y" * 200, "input": {}}]}),
        _record("user", 3, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tRead", "content": c}]}),
        _record("user", 4, message={"role": "user", "content": f"<task-notification><status>{c}</status></task-notification>"}),
        _record("user", 5, **notice),
        _record("system", 6, subtype="compact_boundary", compactMetadata={"trigger": c, "preTokens": 5}),
        _record("history-suppression", 7, cause=c),
        _record("assistant", 8, message={"role": "assistant", "model": "m", "id": "m2", "stop_reason": ["end_turn", c],
                                         "content": [{"type": "text", "text": c}]}),
        {**_record("system", 9, subtype="turn_duration", durationMs=5), "timestamp": f"{c} a timestamp field"},
        {**_record("user", 10, message={"role": "user", "content": "x"}, forkedFrom={"sessionId": c}), "uuid": c},
    ]


@pytest.mark.parametrize("canary", [CANARY, CANARY_BARE], ids=["with-spaces", "no-spaces"])
def test_canary_text_in_every_field_reaches_no_column_of_the_index(tmp_path: Path, canary: str) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    data = _write(path, _canary_records(canary))
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, data),))
    assert conn.execute("SELECT indexed_to FROM files").fetchone()[0] == len(data)
    assert _count(conn, "turns") > 0
    leaked = [cell for cell in _text_cells(conn) if "ZQXJ" in cell or "CANARY" in cell or " " in cell]
    assert leaked == []


def test_a_user_prompt_that_starts_like_a_task_notice_is_a_prompt(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    records = [_record("user", 1, message={"role": "user", "content": "go"}, origin={"kind": "human"}),
               _record("assistant", 2, message={"role": "assistant", "id": "m", "model": "m", "stop_reason": "tool_use",
                       "content": [{"type": "tool_use", "id": "tA", "name": "Agent", "input": {}}]}),
               _record("user", 3, message={"role": "user", "content": "<task-notification><tool-use-id>tA</tool-use-id>"
                                                                      "<status>completed</status></task-notification>"})]
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, _write(path, records)),))
    assert conn.execute("SELECT status FROM threads").fetchall() == [("running",)]


def test_a_thread_status_is_an_enum_and_a_timestamp_must_be_iso() -> None:
    conn = _db()
    conn.execute("INSERT INTO threads VALUES (1, 1, 'agent', 'a1', 'tA', 5, NULL, 'running')")
    end = TimelineEvent(pos=Pos(conv="c", file_key="main", offset=9, serial="s"), kind=Kind.SUBAGENT_END,
                        data={"agent_id": "a1", "status": "some words"})
    index.apply_events(conn, 1, 1, [end], 5)
    assert conn.execute("SELECT status FROM threads").fetchone()[0] == "other"
    with pytest.raises(ValueError):
        TimelineEvent(pos=Pos(conv="c", file_key="main", offset=1, serial="s"), kind=Kind.NOTICE, t="free text here")


def test_ident_refuses_text_instead_of_cutting_it() -> None:
    from src.core.timeline.extract_message import ident
    assert ident("mcp__a.b:c/d-e") == "mcp__a.b:c/d-e"
    assert ident("two words") is None and ident("y" * 200) is None and ident("a\n") is None and ident(["x"]) is None


def test_a_forks_switch_marker_is_stored_though_its_line_is_inherited(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    head = _record("user", 1, message={"role": "user", "content": "copied"}, forkedFrom={"sessionId": "src-1"})
    data = _write(path, [head] + _turn(10))
    rng = parse_range(data, 0, "claude")
    inherited_end = rng.lines[0].length
    event = C.Appended(conversation_id=CONV, family="claude", path=str(path), file_kind="conversation", start=0,
                       end=rng.complete_end, lines=rng.lines, inherited_start=0, inherited_end=inherited_end,
                       lineage=None, trigger="t")
    conn = _db()
    plugin.TIMELINE.on_events(conn, (event,))
    assert conn.execute("SELECT kind FROM markers").fetchall() == [("switch",)]
    assert _count(conn, "turns") == 1


def test_a_list_stop_reason_does_not_stall_the_file(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    bad = _record("assistant", 2, message={"role": "assistant", "id": "m", "model": "m", "stop_reason": ["end_turn"],
                                           "content": [{"type": "text", "text": "hi"}]})
    data = _write(path, [_turn(1)[0], bad] + _turn(10))
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, data),))
    assert conn.execute("SELECT indexed_to FROM files").fetchone()[0] == len(data) and _count(conn, "turns") == 2


@pytest.mark.parametrize("error", [TypeError, KeyError, AttributeError])
def test_a_rule_that_raises_any_malformed_field_error_skips_the_line(tmp_path: Path, monkeypatch, error) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    data = _write(path, _turn(1))
    real = plugin.extract_line
    calls = {"n": 0}

    def flaky(ctx, raw, end, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise error("malformed")
        return real(ctx, raw, end, **kw)
    monkeypatch.setattr(plugin, "extract_line", flaky)
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, data),))
    assert conn.execute("SELECT indexed_to FROM files").fetchone()[0] == len(data)


def test_the_replay_is_bounded_by_the_budget_and_resumes(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    turns = [r for n in range(1, 200, 10) for r in _turn(n)]
    data = _write(path, turns[:40])
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, data),))
    plugin._contexts.clear()
    full = _write(path, turns)
    event = _appended(path, full, start=len(data))
    budget, total, rounds = 2000, 0, 0
    while True:
        answer = plugin.catch_up(conn, event, budget)
        rounds += 1
        total += answer.bytes_read
        assert answer.bytes_read <= budget + 1000
        if answer.ready:
            break
        assert rounds < 100
    assert rounds > 1 and total == len(data)
    plugin.TIMELINE.on_events(conn, (event,))
    straight = _db()
    plugin.TIMELINE.on_events(straight, (_appended(path, full),))
    assert conn.execute("SELECT turn, calls, replies, end_via FROM turns ORDER BY turn").fetchall() == \
        straight.execute("SELECT turn, calls, replies, end_via FROM turns ORDER BY turn").fetchall()


def test_a_delivered_line_is_not_parsed_again_for_its_serial(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    data = _write(path, _turn(1))

    def boom(_line):
        raise AssertionError("line_serial re-parsed a delivered line")
    monkeypatch.setattr(plugin, "line_serial", boom)
    monkeypatch.setattr(extract_module, "line_serial", boom)
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, data),))
    last = parse_range(data, 0, "claude").last_serial
    assert conn.execute("SELECT last_serial FROM files").fetchone()[0] == last


def test_advance_with_no_serial_keeps_the_stored_one() -> None:
    conn = _db()
    file_id = index.add_file(conn, 1, "/x", "main", "conversation")
    index.advance(conn, file_id, 10, "u1")
    index.advance(conn, file_id, 20, None)
    assert conn.execute("SELECT indexed_to, last_serial FROM files").fetchone() == (20, "u1")


def _agent_launch_then_notice(notice: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = ("<task-notification><task-id>x1</task-id><tool-use-id>tA</tool-use-id>"
            "<status>completed</status></task-notification>")
    return [_record("user", 1, message={"role": "user", "content": "go"}, origin={"kind": "human"}),
            _record("assistant", 2, message={"role": "assistant", "id": "m", "model": "m", "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": "tA", "name": "Agent", "input": {"run_in_background": True}}]}),
            _record("user", 3, message={"role": "user", "content": text}, **notice)]


@pytest.mark.parametrize("notice, status", [
    ({"version": "2.1.90"}, "completed"),
    ({"version": "2.1.150", "origin": {"kind": "task-notification"}}, "completed"),
    ({"version": "2.1.150"}, "running"),
    ({}, "running"),
], ids=["old-origin-less", "new-with-origin", "new-origin-less", "unversioned"])
def test_an_origin_less_task_notice_of_an_old_release_still_ends_its_thread(tmp_path: Path, notice: Dict[str, Any],
                                                                            status: str) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, _write(path, _agent_launch_then_notice(notice))),))
    assert conn.execute("SELECT status FROM threads").fetchall() == [(status,)]


def test_a_uuid_that_is_text_still_moves_the_stored_serial(tmp_path: Path) -> None:
    path = tmp_path / f"{CONV}.jsonl"
    records = _turn(1)
    records[-1] = {**records[-1], "uuid": "some words here"}
    conn = _db()
    plugin.TIMELINE.on_events(conn, (_appended(path, _write(path, records)),))
    stored = conn.execute("SELECT last_serial FROM files").fetchone()[0]
    assert stored.startswith("sha256:") and stored != records[-2]["uuid"]
    data = path.read_bytes()
    plugin.TIMELINE.on_events(conn, (_appended(path, data),))
    assert conn.execute("SELECT calls FROM turns").fetchone()[0] == 1


@pytest.mark.parametrize("canary", [CANARY, CANARY_BARE], ids=["with-spaces", "no-spaces"])
def test_the_extractor_alone_emits_no_canary_text(canary: str) -> None:
    from src.core.timeline.context import ExtractContext
    ctx = ExtractContext(conv=CONV)
    seen: List[str] = []
    for number, record in enumerate(_canary_records(canary), start=1):
        for event in extract_module.extract_line(ctx, json.dumps(record).encode(), number * 1000, serial=f"s{number}"):
            seen += [value for value in event.data.values() if isinstance(value, str)]
            seen += [value for value in (event.t,) if isinstance(value, str)]
    assert [value for value in seen if "ZQXJ" in value] == []
