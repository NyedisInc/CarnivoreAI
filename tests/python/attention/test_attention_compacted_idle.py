
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from src.core.attention.evidence import (
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    TIER_REGISTRY,
)
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_NO_RECORD,
    FACTS_TAIL_BYTES,
    read_transcript_facts,
)
from src.core.attention.transcript_records import TURN_END_DURATION
from tests.test_attention_claude_rest_shapes import (
    NOW,
    _assistant_text,
    _assistant_tool_use,
    _base,
    _prompt,
    _resolve,
    _turn_end,
    _write,
)

_ATTACHMENT_SIZES = (134000, 58000, 14000, 20000, 15000)


def _compact_boundary(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("system", seconds_before_now)
    record.update(
        {"subtype": "compact_boundary", "content": "Conversation compacted",
         "isMeta": False, "level": "info"}
    )
    return record


def _compact_summary(seconds_before_now: float) -> Dict[str, Any]:
    record = _base("user", seconds_before_now)
    record["isVisibleInTranscriptOnly"] = True
    record["isCompactSummary"] = True
    record["message"] = {"role": "user", "content": "s" * 34000}
    return record


def _attachment(seconds_before_now: float, kind: str, size: int) -> Dict[str, Any]:
    record = _base("attachment", seconds_before_now)
    record["attachment"] = {"type": kind, "content": "a" * size}
    return record


def _compaction_dump(seconds_before_now: float) -> List[Dict[str, Any]]:
    records = [_compact_boundary(seconds_before_now), _compact_summary(seconds_before_now)]
    for index, size in enumerate(_ATTACHMENT_SIZES):
        records.append(_attachment(seconds_before_now - 0.1, "file_%d" % index, size))
    notice = _base("system", seconds_before_now - 0.5)
    notice.update(
        {"subtype": "informational", "level": "notice", "isMeta": False,
         "content": "Compacted while idle, before the prompt cache expired"}
    )
    return records + [notice]


def _finished_turn() -> List[Dict[str, Any]]:
    return [_prompt(7300), _assistant_text(7290), _turn_end(7289)]


def test_the_dump_is_wider_than_the_tail_window():
    assert sum(_ATTACHMENT_SIZES) + 34000 > FACTS_TAIL_BYTES


def test_compacted_while_idle_reads_idle_from_the_registry(tmp_path):
    path = _write(tmp_path, _finished_turn() + _compaction_dump(3600))
    facts = read_transcript_facts(path, now=NOW)

    assert facts.verdict == FACTS_FOUND
    assert facts.turn_end_kind == TURN_END_DURATION
    assert facts.pending_background_agents == 0
    assert facts.newest_user_prompt_at == NOW - timedelta(seconds=7300)

    verdict = _resolve(facts)
    assert (verdict.state, verdict.reason, verdict.tier) == (
        STATE_DONE_IDLE,
        REASON_TURN_ENDED,
        TIER_REGISTRY,
    )


def test_before_the_fix_the_same_file_was_unknown(tmp_path):
    path = _write(tmp_path, _finished_turn() + _compaction_dump(3600))
    facts = read_transcript_facts(
        path, now=NOW, tail_bytes=FACTS_TAIL_BYTES, wide_tail_bytes=FACTS_TAIL_BYTES
    )

    assert facts.verdict == FACTS_NO_RECORD
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_a_compact_followed_by_a_live_turn_still_reads_working(tmp_path):
    records = (
        _finished_turn()
        + _compaction_dump(60)
        + [_prompt(8), _assistant_tool_use(4, "toolu_live", "Read")]
    )
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)

    assert facts.newest_user_prompt_at == NOW - timedelta(seconds=8)
    assert _resolve(facts).state == STATE_BUSY


def test_a_compact_over_a_pending_background_agent_is_not_idle(tmp_path):
    counted = _turn_end(7289)
    counted["pendingBackgroundAgentCount"] = 1
    records = [_prompt(7300), _assistant_text(7290), counted] + _compaction_dump(3600)
    facts = read_transcript_facts(_write(tmp_path, records), now=NOW)

    assert facts.pending_background_agents == 1
    assert _resolve(facts).state != STATE_DONE_IDLE


def test_a_dump_with_no_turn_end_anywhere_stays_unknown(tmp_path):
    facts = read_transcript_facts(_write(tmp_path, _compaction_dump(3600)), now=NOW)

    assert facts.verdict == FACTS_NO_RECORD
    assert _resolve(facts).state != STATE_DONE_IDLE
