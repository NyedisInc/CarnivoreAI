
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional, Tuple

import pytest

from src.core.attention.pane_agent_proof import registered_agent_in_foreground
from src.core.attention.registry_index import read_registry_index
from src.core.session_one_shot_gate import PANE_NOT_AN_AGENT, OneShotRefused, check_can_paste
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None or shutil.which("zsh") is None, reason="tmux or zsh not on PATH"
)

PaneFacts = Tuple[str, int, str, int]


def _tmux(*args: str) -> str:
    result = subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return result.stdout.strip()


def _facts(name: str) -> PaneFacts:
    created, pane_id, pane_pid = _tmux(
        "list-panes", "-t", "=%s:" % name, "-F", "#{session_created} #{pane_id} #{pane_pid}",
    ).split()
    return name, int(created), pane_id, int(pane_pid)


def _current_command(name: str) -> str:
    return _tmux("display-message", "-p", "-t", "=%s:" % name, "#{pane_current_command}")


def _child_of(pid: int) -> Optional[int]:
    for _ in range(50):
        done = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False)
        pids = [int(p) for p in done.stdout.split()]
        if pids:
            return pids[0]
        time.sleep(0.1)
    return None


@pytest.fixture
def make_pane(tmux_test_socket: str) -> Iterator:
    names = []

    def make(command: str) -> PaneFacts:
        name = "cloude_tprof_%s" % uuid.uuid4().hex[:8]
        names.append(name)
        _tmux("new-session", "-d", "-s", name, command)
        return _facts(name)

    yield make
    for name in names:
        subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", "=" + name],
                       capture_output=True, check=False, timeout=10)


def _registry(tmp_path: Path, facts: PaneFacts, pid: int) -> dict:
    name, _created, pane_id, _pane_pid = facts
    directory = tmp_path / "sessions"
    directory.mkdir(exist_ok=True)
    millis = int(time.time() * 1000) + 1000
    (directory / ("%d.json" % pid)).write_text(json.dumps({
        "pid": pid, "sessionId": str(uuid.uuid4()), "cwd": str(tmp_path), "startedAt": millis,
        "version": "2.1.288", "kind": "interactive", "tmux": "%s:@1.%s" % (name, pane_id),
        "status": "idle", "updatedAt": millis, "statusUpdatedAt": millis,
    }))
    return read_registry_index(str(directory))


def _proof(facts: PaneFacts, index: dict) -> bool:
    name, created, pane_id, pane_pid = facts
    return registered_agent_in_foreground(
        tmux_name=name, pane_id=pane_id, pane_pid=pane_pid,
        session_started_epoch=created, index=index,
    )


def _gate(command: str, proven: bool) -> None:
    check_can_paste(pane_current_command=command, pane_dead="0", agent_type="claude",
                    activity_status="idle", startup_gate="ready", foreground_agent_proven=proven)


@requires_tmux
def test_profile_launched_agent_under_zsh_is_proven_and_passes(tmp_path, make_pane):
    wrapper = tmp_path / "wrapper.zsh"
    wrapper.write_text("command sleep 600\n")
    facts = make_pane("zsh -f -c 'source %s'" % wrapper)
    agent = _child_of(facts[3])
    assert agent is not None, "the wrapper's child never started"
    assert _current_command(facts[0]) == "zsh"
    with pytest.raises(OneShotRefused):
        _gate("zsh", proven=False)
    assert _proof(facts, _registry(tmp_path, facts, agent)) is True
    _gate("zsh", proven=True)


@requires_tmux
def test_plain_shell_with_no_registered_agent_still_refuses(tmp_path, make_pane):
    facts = make_pane("zsh -f")
    assert _current_command(facts[0]) == "zsh"
    directory = tmp_path / "empty"
    directory.mkdir()
    proven = _proof(facts, read_registry_index(str(directory)))
    assert proven is False
    with pytest.raises(OneShotRefused) as refused:
        _gate("zsh", proven=proven)
    assert refused.value.code == PANE_NOT_AN_AGENT


@requires_tmux
def test_record_naming_the_pane_with_a_pid_outside_it_refuses(tmp_path, make_pane):
    facts = make_pane("zsh -f")
    assert _proof(facts, _registry(tmp_path, facts, os.getpid())) is False


@requires_tmux
def test_row_with_no_agent_record_and_no_uuid_passes_on_the_registry_proof(tmp_path, make_pane):
    wrapper = tmp_path / "wrapper.zsh"
    wrapper.write_text("command sleep 600\n")
    facts = make_pane("zsh -f -c 'source %s'" % wrapper)
    agent = _child_of(facts[3])
    assert agent is not None, "the wrapper's child never started"
    name, created, pane_id, pane_pid = facts
    proven = registered_agent_in_foreground(
        tmux_name=name, pane_id=pane_id, pane_pid=pane_pid, session_started_epoch=created,
        claude_session_uuid=None, index=_registry(tmp_path, facts, agent),
    )
    assert proven is True
    check_can_paste(pane_current_command="zsh", pane_dead="0", agent_type=None,
                    activity_status="idle", startup_gate="ready", foreground_agent_proven=proven)

    shell = make_pane("zsh -f")
    empty = tmp_path / "none"
    empty.mkdir()
    assert _proof(shell, read_registry_index(str(empty))) is False
    with pytest.raises(OneShotRefused) as refused:
        check_can_paste(pane_current_command="zsh", pane_dead="0", agent_type=None,
                        activity_status="idle", startup_gate="ready", foreground_agent_proven=False)
    assert refused.value.code == PANE_NOT_AN_AGENT
