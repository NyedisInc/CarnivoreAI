
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_STARTING,
    REASON_SUBAGENTS,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_NEEDS_USER,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.process_scope import evidence_process_floor
from src.core.attention.registry_record import REG_OK, REG_STALE, STALE_CAUSE_CONVERSATION
from src.core.attention.registry_index import read_registry_index
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import read_transcript_facts
from src.core.listing_attention import attention_reads_for_name
from src.core.session_status import LIVENESS_LIVE
from tests.socket_guard import TEST_SOCKET_NAME
from tests.test_attention_transcript_facts import (
    _assistant_tool_use,
    _turn_end,
    _user_prompt,
)

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

OLD_CONVERSATION = "11111111-1a7b-42f9-baba-abacc8720544"

NEW_CONVERSATION = "22222222-1a7b-42f9-baba-abacc8720544"

CLAUDE_VERSION = "2.1.283"


def _tmux(*args: str) -> str:
    result = subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture
def pane(tmux_test_socket: str) -> Iterator[Tuple[str, int, str, int]]:
    name = "cloude_t1323_%s" % uuid.uuid4().hex[:8]
    _tmux("new-session", "-d", "-s", name, "sleep 600")
    try:
        created, pane_id, pane_pid = _tmux(
            "list-panes", "-t", "=%s:" % name, "-F",
            "#{session_created} #{pane_id} #{pane_pid}",
        ).split()
        yield name, int(created), pane_id, int(pane_pid)
    finally:
        subprocess.run(
            ["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", "=" + name],
            capture_output=True, check=False, timeout=10,
        )


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _clock() -> Tuple[datetime, datetime, datetime]:
    base = datetime.now(timezone.utc) + timedelta(seconds=2)
    return base, base + timedelta(seconds=30), base + timedelta(seconds=31)


def _read(
    tmp_path: Path,
    pane_facts: Tuple[str, int, str, int],
    records: List[Dict[str, Any]],
    *,
    registry_started: Optional[datetime],
    restarted_at: Optional[datetime],
    now: datetime,
    record_conversation: str = OLD_CONVERSATION,
) -> Evidence:
    name, created, pane_id, pane_pid = pane_facts
    registry_dir = tmp_path / "sessions"
    registry_dir.mkdir()
    if registry_started is not None:
        millis = int(registry_started.timestamp() * 1000)
        (registry_dir / ("%d.json" % pane_pid)).write_text(json.dumps({
            "pid": pane_pid, "sessionId": record_conversation, "cwd": str(tmp_path),
            "startedAt": millis, "version": CLAUDE_VERSION, "kind": "interactive",
            "tmux": "%s:@1.%s" % (name, pane_id), "status": "idle",
            "updatedAt": millis, "statusUpdatedAt": millis,
        }))
    transcript = tmp_path / (OLD_CONVERSATION + ".jsonl")
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    registry, facts = attention_reads_for_name(
        name, registry_index=read_registry_index(str(registry_dir)),
        session_started_epoch=created, claude_session_uuid=OLD_CONVERSATION,
        working_dir=str(tmp_path), now=now,
        transcript_reader=lambda _u, _w, now=None: read_transcript_facts(
            str(transcript), now=now
        ),
        pane_id=pane_id, pane_pid=pane_pid, process_floor_at=restarted_at,
    )
    return Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=registry, transcript=facts, pane=None, now=now,
        process_floor_at=evidence_process_floor(created, restarted_at),
    )


def _question_tail(asked: datetime) -> List[Dict[str, Any]]:
    return [
        _user_prompt(_iso(asked - timedelta(seconds=5))),
        _assistant_tool_use(_iso(asked), "AskUserQuestion", "toolu_q"),
    ]


@requires_tmux
def test_w1_restart_over_an_unanswered_question_is_not_a_question(tmp_path, pane):
    old_started, restarted, new_started = _clock()
    tail = _question_tail(old_started + timedelta(seconds=10))
    (tmp_path / "before").mkdir()
    before = resolve_attention(_read(
        tmp_path / "before", pane, tail, registry_started=None,
        restarted_at=restarted, now=restarted + timedelta(seconds=1),
    ))
    assert (before.state, before.reason) == (STATE_UNKNOWN, REASON_STARTING), before.detail
    (tmp_path / "after").mkdir()
    after = resolve_attention(_read(
        tmp_path / "after", pane, tail, registry_started=new_started,
        restarted_at=restarted, now=new_started + timedelta(seconds=5),
    ))
    assert (after.state, after.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED), after.detail


@requires_tmux
def test_w1_control_a_question_asked_after_the_restart_still_asks(tmp_path, pane):
    _old, restarted, new_started = _clock()
    verdict = resolve_attention(_read(
        tmp_path, pane, _question_tail(new_started + timedelta(seconds=10)),
        registry_started=new_started, restarted_at=restarted,
        now=new_started + timedelta(seconds=20),
    ))
    assert verdict.state == STATE_NEEDS_USER, verdict.detail


@requires_tmux
def test_w1_control_with_no_floor_the_old_question_still_wins(tmp_path, pane):
    old_started, _restarted, _new = _clock()
    verdict = resolve_attention(_read(
        tmp_path, pane, _question_tail(old_started + timedelta(seconds=10)),
        registry_started=None, restarted_at=None,
        now=old_started + timedelta(seconds=40),
    ))
    assert verdict.state == STATE_NEEDS_USER


@requires_tmux
def test_w2_restart_over_pending_background_agents_is_not_working(tmp_path, pane):
    old_started, restarted, _new = _clock()
    tail = [_turn_end(_iso(old_started + timedelta(seconds=10)), pending=2,
                      version=CLAUDE_VERSION)]
    verdict = resolve_attention(_read(
        tmp_path, pane, tail, registry_started=None, restarted_at=restarted,
        now=restarted + timedelta(seconds=1),
    ))
    assert verdict.state != STATE_BUSY, verdict.detail
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_STARTING)


@requires_tmux
def test_w2_control_with_no_floor_the_count_still_reads_as_work(tmp_path, pane):
    old_started, _restarted, _new = _clock()
    tail = [_turn_end(_iso(old_started + timedelta(seconds=10)), pending=2,
                      version=CLAUDE_VERSION)]
    verdict = resolve_attention(_read(
        tmp_path, pane, tail, registry_started=None, restarted_at=None,
        now=old_started + timedelta(seconds=40),
    ))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)


@requires_tmux
def test_w3_fresh_conversation_restart_reads_rest_at_once(tmp_path, pane):
    old_started, restarted, new_started = _clock()
    tail = [_turn_end(_iso(old_started + timedelta(seconds=10)), pending=0,
                      version=CLAUDE_VERSION)]
    evidence = _read(
        tmp_path, pane, tail, registry_started=new_started, restarted_at=restarted,
        now=new_started + timedelta(seconds=5), record_conversation=NEW_CONVERSATION,
    )
    assert evidence.registry.verdict == REG_OK, evidence.registry.detail
    assert evidence.registry.stale_cause == STALE_CAUSE_CONVERSATION
    assert evidence.registry.record_session_uuid == NEW_CONVERSATION
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED)


@requires_tmux
def test_w3_control_with_no_floor_the_conversation_gate_still_refuses(tmp_path, pane):
    old_started, _restarted, new_started = _clock()
    tail = [_turn_end(_iso(old_started + timedelta(seconds=10)), pending=0,
                      version=CLAUDE_VERSION)]
    evidence = _read(
        tmp_path, pane, tail, registry_started=new_started, restarted_at=None,
        now=new_started + timedelta(seconds=5), record_conversation=NEW_CONVERSATION,
    )
    assert evidence.registry.verdict == REG_STALE
    assert evidence.registry.stale_cause == STALE_CAUSE_CONVERSATION


@requires_tmux
def test_w4_the_dying_process_record_is_not_this_instance(tmp_path, pane):
    old_started, restarted, _new = _clock()
    evidence = _read(
        tmp_path, pane, [], registry_started=old_started, restarted_at=restarted,
        now=restarted + timedelta(seconds=1),
    )
    assert evidence.registry.verdict == REG_STALE, evidence.registry.detail
    assert evidence.registry.instance_present is False


@requires_tmux
def test_w4_control_with_no_floor_the_same_record_is_this_instance(tmp_path, pane):
    old_started, _restarted, _new = _clock()
    evidence = _read(
        tmp_path, pane, [], registry_started=old_started, restarted_at=None,
        now=old_started + timedelta(seconds=40),
    )
    assert evidence.registry.verdict == REG_OK
    assert evidence.registry.instance_present is True
