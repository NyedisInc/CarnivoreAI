
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import pytest

from src.core.attention import fs_trigger
from src.core.attention.evidence import FAMILY_CLAUDE, STATE_BUSY, Evidence
from src.core.attention.ledger import AttentionLedger
from src.core.attention.registry_index import read_registry_index
from src.core.attention.transcript_facts import read_transcript_facts
from src.core.attention.watcher import AttentionWatcher, Observation, WatchTarget
from src.core.listing_attention import attention_reads_for_name
from src.core.session_status import LIVENESS_LIVE
from tests.socket_guard import TEST_SOCKET_NAME

pytestmark = [
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH"),
    pytest.mark.skipif(not fs_trigger.KQUEUE_AVAILABLE, reason="no kqueue"),
]

CONVERSATION = "76200000-1a7b-42f9-baba-abacc8720762"
CLAUDE_VERSION = "2.1.283"
TICK_SECONDS = 30.0
WINDOW_SECONDS = 2.0


def _tmux(*args: str) -> str:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True,
                          text=True, check=True, timeout=10).stdout.strip()


@pytest.fixture
def pane(tmux_test_socket: str) -> Iterator[Tuple[str, int, str, int]]:
    name = "cloude_t762_%s" % uuid.uuid4().hex[:8]
    _tmux("new-session", "-d", "-s", name, "sleep 600")
    try:
        created, pane_id, pane_pid = _tmux(
            "list-panes", "-t", "=%s:" % name, "-F",
            "#{session_created} #{pane_id} #{pane_pid}").split()
        yield name, int(created), pane_id, int(pane_pid)
    finally:
        subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", "=" + name],
                       capture_output=True, check=False, timeout=10)


def _record(pane_facts, status: str) -> str:
    name, created, pane_id, pane_pid = pane_facts
    millis = int(time.time() * 1000)
    return json.dumps({
        "pid": pane_pid, "sessionId": CONVERSATION, "cwd": "/tmp",
        "startedAt": created * 1000, "version": CLAUDE_VERSION,
        "kind": "interactive", "tmux": "%s:@1.%s" % (name, pane_id),
        "status": status, "updatedAt": millis, "statusUpdatedAt": millis,
    })


def _rewrite_in_place(path: Path, text: str) -> None:
    with open(path, "r+") as handle:
        handle.seek(0)
        handle.truncate()
        handle.write(text)


def _run(tmp_path: Path, pane_facts, *, trigger: bool) -> Tuple[Optional[str], List[str]]:
    name, created, pane_id, pane_pid = pane_facts
    registry_dir = tmp_path / "sessions"
    registry_dir.mkdir()
    record = registry_dir / ("%d.json" % pane_pid)
    record.write_text(_record(pane_facts, "idle"))
    transcript = tmp_path / (CONVERSATION + ".jsonl")
    transcript.write_text("")
    target = WatchTarget("ses_762", "%s@%d" % (name, created))

    def read(_target: WatchTarget, now: datetime) -> Evidence:
        registry, facts = attention_reads_for_name(
            name, registry_index=read_registry_index(str(registry_dir)),
            session_started_epoch=created, claude_session_uuid=CONVERSATION,
            working_dir=str(tmp_path), now=now,
            transcript_reader=lambda _u, _w, now=None: read_transcript_facts(
                str(transcript), now=now),
            pane_id=pane_id, pane_pid=pane_pid,
        )
        return Evidence(tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
                        registry=registry, transcript=facts, pane=None, now=now)

    seen: List[Tuple[float, str]] = []

    async def drive() -> Tuple[Optional[str], List[str]]:
        watcher = AttentionWatcher(
            list_targets=lambda: [target], read_evidence=read,
            raise_toast=lambda *a: None, set_unread=lambda *a: None,
            on_busy_edge=lambda *a: None, ledger=AttentionLedger(),
            on_observation=lambda _t, obs: seen.append(
                (time.monotonic(), obs.verdict.state)),
            tick_seconds=TICK_SECONDS, registry_directory=str(registry_dir),
            watch_paths=(lambda ids: {"ses_762": (str(record), str(transcript))})
            if trigger else None,
        )
        task = asyncio.create_task(watcher.run())
        try:
            while not seen:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.2)
            before = seen[-1][1]
            written = time.monotonic()
            _rewrite_in_place(record, _record(pane_facts, "busy"))
            await asyncio.sleep(WINDOW_SECONDS)
            return before, [state for at, state in seen if at > written]
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return asyncio.run(drive())


def test_an_in_place_registry_rewrite_is_observed_before_the_tick(tmp_path, pane) -> None:
    before, after = _run(tmp_path, pane, trigger=True)
    assert before != STATE_BUSY
    assert STATE_BUSY in after


def test_without_the_trigger_the_same_write_waits_for_the_tick(tmp_path, pane) -> None:
    before, after = _run(tmp_path, pane, trigger=False)
    assert before != STATE_BUSY
    assert after == []
