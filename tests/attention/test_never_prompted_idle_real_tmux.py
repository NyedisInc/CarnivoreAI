
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Tuple

import pytest

from src.core import claude_transcript_correlate
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_NO_EVIDENCE,
    REASON_TURN_ENDED,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.process_scope import evidence_process_floor
from src.core.attention.registry_read import REG_OK, read_registry_index
from src.core.attention.resolve import resolve_attention
from src.core.listing_attention import attention_reads_for_name
from src.core.session_status import LIVENESS_LIVE
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

CONVERSATION = "caef7ffd-cfb3-4df8-80c7-ecd1746bc72a"

CLAUDE_VERSION = "2.1.289"


def _tmux(*args: str) -> str:
    result = subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture
def pane(tmux_test_socket: str) -> Iterator[Tuple[str, int, str, int]]:
    name = "cloude_tfresh_%s" % uuid.uuid4().hex[:8]
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


def _resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pane_facts: Tuple[str, int, str, int],
    *,
    status_changed_after_start: float,
    corpus_readable: bool = True,
):
    name, created, pane_id, pane_pid = pane_facts
    corpus = tmp_path / "projects"
    if corpus_readable:
        (corpus / "-some-other-project").mkdir(parents=True)
        (corpus / "-some-other-project" / (str(uuid.uuid4()) + ".jsonl")).write_text("{}\n")
    monkeypatch.setattr(claude_transcript_correlate, "default_projects_dir", lambda: corpus)
    started = datetime.now(timezone.utc) + timedelta(seconds=2)
    status_at = started + timedelta(seconds=status_changed_after_start)
    registry_dir = tmp_path / "sessions"
    registry_dir.mkdir()
    (registry_dir / ("%d.json" % pane_pid)).write_text(json.dumps({
        "pid": pane_pid, "sessionId": CONVERSATION, "cwd": str(tmp_path / "fresh"),
        "startedAt": int(started.timestamp() * 1000), "version": CLAUDE_VERSION,
        "kind": "interactive", "tmux": "%s:@1.%s" % (name, pane_id), "status": "idle",
        "updatedAt": int(status_at.timestamp() * 1000),
        "statusUpdatedAt": int(status_at.timestamp() * 1000),
    }))
    now = max(started, status_at) + timedelta(seconds=10)
    registry, facts = attention_reads_for_name(
        name, registry_index=read_registry_index(str(registry_dir)),
        session_started_epoch=created, claude_session_uuid=CONVERSATION,
        working_dir=str(tmp_path / "fresh"), now=now,
        pane_id=pane_id, pane_pid=pane_pid,
    )
    evidence = Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=registry, transcript=facts, pane=None, now=now,
        process_floor_at=evidence_process_floor(created, None),
    )
    return evidence, resolve_attention(evidence)


@requires_tmux
def test_a_never_prompted_claude_at_its_prompt_is_idle(tmp_path, monkeypatch, pane):
    evidence, verdict = _resolve(tmp_path, monkeypatch, pane, status_changed_after_start=-0.1)
    assert evidence.registry.verdict == REG_OK, evidence.registry.detail
    assert evidence.transcript.absent is True, evidence.transcript.detail
    assert (verdict.state, verdict.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED), verdict.detail


@requires_tmux
def test_control_a_status_that_changed_after_start_is_not_never_prompted(
    tmp_path, monkeypatch, pane
):
    _evidence, verdict = _resolve(tmp_path, monkeypatch, pane, status_changed_after_start=60.0)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_NO_EVIDENCE), verdict.detail


@requires_tmux
def test_control_a_corpus_that_could_not_be_read_is_not_an_absence(
    tmp_path, monkeypatch, pane
):
    evidence, verdict = _resolve(
        tmp_path, monkeypatch, pane, status_changed_after_start=-0.1, corpus_readable=False,
    )
    assert evidence.transcript.absent is False
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_NO_EVIDENCE), verdict.detail
