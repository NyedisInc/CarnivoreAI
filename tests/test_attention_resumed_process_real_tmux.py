
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_QUEUED_REINVOKE,
    REASON_REGISTRY_STALE,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.registry_record import REG_OK
from src.core.attention.registry_index import read_registry_index
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import read_transcript_facts
from src.core.listing_attention import attention_reads_for_name
from src.core.session_status import LIVENESS_LIVE
from tests.socket_guard import TEST_SOCKET_NAME
from tests.test_attention_transcript_facts import (
    _assistant_tool_use,
    _enqueue,
    _turn_end,
    _user_prompt,
)

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

CONVERSATION = "26003627-1a7b-42f9-baba-abacc8720544"

CLAUDE_VERSION = "2.1.283"

STAMP_AGE_SECONDS = 5400


def _tmux(*args: str) -> str:
    result = subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture
def pane(tmux_test_socket: str) -> Iterator[Tuple[str, int, str, int]]:
    name = "cloude_t601_%s" % uuid.uuid4().hex[:8]
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


def _read(tmp_path: Path, pane_facts: Tuple[str, int, str, int],
          records: List[Dict[str, Any]], started_at: datetime,
          now: datetime) -> Evidence:
    name, created, pane_id, pane_pid = pane_facts
    registry_dir = tmp_path / "sessions"
    registry_dir.mkdir()
    millis = int(started_at.timestamp() * 1000)
    (registry_dir / ("%d.json" % pane_pid)).write_text(json.dumps({
        "pid": pane_pid, "sessionId": CONVERSATION, "cwd": str(tmp_path),
        "startedAt": millis, "version": CLAUDE_VERSION, "kind": "interactive",
        "tmux": "%s:@1.%s" % (name, pane_id), "status": "idle",
        "updatedAt": millis, "statusUpdatedAt": millis,
    }))
    transcript = tmp_path / (CONVERSATION + ".jsonl")
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    registry, facts = attention_reads_for_name(
        name, registry_index=read_registry_index(str(registry_dir)),
        session_started_epoch=created, claude_session_uuid=CONVERSATION,
        working_dir=str(tmp_path), now=now,
        transcript_reader=lambda _u, _w, now=None: read_transcript_facts(
            str(transcript), now=now
        ),
        pane_id=pane_id, pane_pid=pane_pid,
    )
    assert registry.verdict == REG_OK, registry.detail
    return Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=registry, transcript=facts, pane=None, now=now,
    )


def _clock() -> Tuple[datetime, datetime]:
    started = datetime.now(timezone.utc) + timedelta(seconds=2)
    return started, started + timedelta(seconds=STAMP_AGE_SECONDS)


@requires_tmux
def test_resumed_process_over_a_previous_open_turn_reads_rest(tmp_path, pane):
    started, now = _clock()
    old = started - timedelta(days=2)
    evidence = _read(tmp_path, pane, [
        _user_prompt(_iso(old)),
        _assistant_tool_use(_iso(old + timedelta(seconds=5)), "Bash", "toolu_old"),
    ], started, now)
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED)
    assert "has run no turn" in verdict.detail


@requires_tmux
def test_resumed_process_over_a_previous_queued_reinvoke_reads_rest(tmp_path, pane):
    started, now = _clock()
    old = started - timedelta(hours=2)
    evidence = _read(tmp_path, pane, [
        _turn_end(_iso(old), pending=1, version=CLAUDE_VERSION),
        _enqueue(_iso(old + timedelta(minutes=3)), "ac21bf29", "toolu_01"),
    ], started, now)
    assert evidence.transcript.queued_reinvoke is True
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED)


@requires_tmux
def test_control_a_record_written_by_this_process_still_refuses(tmp_path, pane):
    started, now = _clock()
    evidence = _read(tmp_path, pane, [
        _user_prompt(_iso(started + timedelta(seconds=10))),
        _assistant_tool_use(_iso(started + timedelta(seconds=15)), "Bash", "toolu_new"),
    ], started, now)
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_REGISTRY_STALE)


@requires_tmux
def test_control_a_reinvoke_this_process_queued_is_still_work(tmp_path, pane):
    started, now = _clock()
    evidence = _read(tmp_path, pane, [
        _turn_end(_iso(started + timedelta(seconds=10)), pending=1, version=CLAUDE_VERSION),
        _enqueue(_iso(started + timedelta(seconds=40)), "ac21bf29", "toolu_01"),
    ], started, now)
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_QUEUED_REINVOKE)
