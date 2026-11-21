
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from src.core.messaging import batch
from src.core.timeline import prompts
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.model import Kind, TimelineEvent
from tests.python.timeline.conftest import run_fixture


def _events(manifest: Dict[str, Dict[str, Any]], name: str) -> List[TimelineEvent]:
    return [e for _r, es in run_fixture(manifest[name]) for e in es]


def test_a_channel_and_a_peer_delivery_are_prompts_that_open_a_turn(manifest: Dict[str, Dict[str, Any]]) -> None:
    events = _events(manifest, "delivery_cases")
    prompts_seen = [e for e in events if e.kind is Kind.PROMPT]
    assert [(e.data["origin"], e.data["plain"]) for e in prompts_seen[:2]] == [("channel", False), ("crosstalk", False)]
    for opener in prompts_seen[:2]:
        assert opener.turn == opener.pos.offset
    replies = [e for e in events if e.kind is Kind.REPLY]
    assert [r.turn for r in replies[:2]] == [p.pos.offset for p in prompts_seen[:2]]


def test_a_bare_meta_user_record_is_still_nothing() -> None:
    record = {"type": "user", "isMeta": True, "message": {"role": "user", "content": "caveat text here"}}
    assert extract_line(ExtractContext(conv="c"), json.dumps(record).encode(), 10, serial="s") == []


@pytest.mark.parametrize("fields, origin", [
    ({"promptSource": "system", "origin": {"kind": "channel"}}, "channel"),
    ({"promptSource": "system", "origin": {"kind": "peer"}}, "crosstalk"),
    ({"promptSource": "system"}, "system"),
    ({"promptSource": "sdk", "origin": {"kind": "human"}}, None),
    ({"promptSource": "typed", "origin": {"kind": "human"}}, None),
    ({"promptSource": "queued", "origin": {"kind": "human"}}, None),
    ({"promptSource": "suggestion_accepted", "origin": {"kind": "human"}}, None),
    ({"promptSource": "sdk", "origin": {"kind": "peer"}}, "crosstalk"),
])
def test_the_measured_source_and_kind_pairs_name_their_origin(fields: Dict[str, Any], origin: Any) -> None:
    assert prompts.harness_origin(fields) == origin


def test_a_split_thinking_and_text_message_ends_its_turn_after_the_answer(manifest: Dict[str, Dict[str, Any]]) -> None:
    events = _events(manifest, "delivery_cases")
    opener = [e for e in events if e.kind is Kind.PROMPT][2]
    split = [e for e in events if e.msg == "msg_split1"]
    assert split and {e.turn for e in split} == {opener.pos.offset}
    turn = [e for e in events if e.turn == opener.pos.offset]
    ends = [i for i, e in enumerate(turn) if e.kind is Kind.TURN_END]
    final = [i for i, e in enumerate(turn) if e.kind is Kind.REPLY and e.data.get("final") is True]
    assert len(ends) == 1 and final and final[0] < ends[0]
    assert turn[ends[0]].data.get("merged") is None


def test_a_thinking_only_record_with_a_stop_reason_does_not_end_the_turn() -> None:
    ctx = ExtractContext(conv="c")
    extract_line(ctx, json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}).encode(), 10, serial="a")
    record = {"type": "assistant", "message": {"role": "assistant", "model": "m", "id": "m1", "stop_reason": "end_turn",
                                               "content": [{"type": "thinking", "thinking": "hmm hmm hmm"}]}}
    events = extract_line(ctx, json.dumps(record).encode(), 20, serial="b")
    assert [e.kind for e in events] == [Kind.THINKING] and ctx.turn_ended is False


def test_a_bare_meta_record_that_drives_a_turn_gets_a_turn_with_no_prompt(manifest: Dict[str, Dict[str, Any]]) -> None:
    events = _events(manifest, "meta_cases")
    assert [e.kind for e in events if e.kind is not Kind.REPLY] == [Kind.TURN_END] * 3
    replies = [e for e in events if e.kind is Kind.REPLY]
    assert len(replies) == 3 and all(r.turn == r.pos.offset for r in replies)
    assert len({r.turn for r in replies}) == 3


def test_a_reply_of_another_message_after_the_end_opens_a_turn_with_no_prompt() -> None:
    def line(record: Dict[str, Any]) -> bytes:
        return json.dumps(record).encode()
    ctx = ExtractContext(conv="c")
    base = {"role": "assistant", "model": "m", "stop_reason": "end_turn"}
    extract_line(ctx, line({"type": "user", "message": {"role": "user", "content": "go"}}), 10, serial="a")
    extract_line(ctx, line({"type": "assistant", "message": {**base, "id": "m1", "content": [
        {"type": "text", "text": "done"}]}}), 20, serial="b")
    (same,) = extract_line(ctx, line({"type": "assistant", "message": {**base, "id": "m1", "stop_reason": "tool_use",
                                     "content": [{"type": "text", "text": "tail"}]}}), 25, serial="c")
    (late,) = extract_line(ctx, line({"type": "assistant", "message": {**base, "id": "m2", "stop_reason": "tool_use",
                                     "content": [{"type": "text", "text": "later"}]}}), 30, serial="d")
    assert same.turn == 10 and late.turn == 30


def test_one_helper_reads_the_origin_kind_for_both_predicates() -> None:
    assert prompts.origin_kind({"origin": {"kind": "peer"}}) == "peer"
    assert prompts.origin_kind({"origin": "x"}) is None and prompts.origin_kind({}) is None
    assert [prompts.is_delivery_kind(k) for k in ("channel", "human", "task-notification", None)] == [
        True, False, False, False]


@pytest.mark.parametrize("stamp", [{"origin": {"kind": "task-notification"}}, {"version": "2.1.90"}],
                         ids=["origin-carrying", "origin-less-old-release"])
def test_a_task_notice_does_not_reopen_a_turn_still_open(stamp: Dict[str, Any]) -> None:
    ctx = ExtractContext(conv="c")
    notice = {"type": "user", **stamp,
              "message": {"role": "user", "content": "<task-notification>\n<task-id>t1</task-id>\n"
                                                    "<status>completed</status>\n</task-notification>"}}
    extract_line(ctx, json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}).encode(), 10, serial="a")
    extract_line(ctx, json.dumps(notice).encode(), 20, serial="b")
    assert ctx.turn == 10 and ctx.turn_ended is False


def test_an_oversize_user_prompt_is_a_prompt_stub_that_opens_a_turn() -> None:
    ctx = ExtractContext(conv="c")
    raw = (b'{"type":"user","message":{"role":"user","content":"' + b"p" * 5000 + b'"}}')
    (event,) = extract_line(ctx, raw, 77, serial="s", max_bytes=100)
    assert event.kind is Kind.PROMPT
    assert event.data == {"origin": "other", "plain": False, "bytes": len(raw), "oversize": True}
    assert ctx.turn == 77 and event.turn == 77


def test_the_messaging_header_pattern_matches_the_real_dated_line() -> None:
    copy = {"messaging.batch.age_now": "just now", "messaging.batch.age_minutes": "{m}m ago",
            "messaging.batch.age_hours": "{h}h {m}m ago", "messaging.batch.age_days": "{d}d {h}h ago",
            "messaging.batch.held_dialog": "held", "messaging.batch.held_asleep": "held",
            "messaging.batch.held_not_running": "held", "messaging.batch.offline": "offline"}
    stamp = datetime(2026, 10, 9, 14, 2, tzinfo=timezone.utc).timestamp()
    row = batch.Pending(row_id="r1", text="hello", sent_at=stamp, received_at=stamp)
    line = batch.dated_line(row, stamp + 7800, timezone.utc, copy)
    assert prompts.MESSAGING_HEADER_RE.match(line), line
