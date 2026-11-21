
import os
import subprocess
import sys
import types

import pytest

from src.core import host_metrics
from src.core.attention import codex_pane_home as cph
from src.core.attention.codex_gather import DEFAULT_CODEX_HOME
from src.core.conversation_writers import process_cwd
from src.core.session_sleep import _transcript_absent

THREAD = "019a0000-0000-7000-8000-000000000001"
GONE = b"no such session: =carnivore_gone\n"


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(cph, "time", types.SimpleNamespace(monotonic=fake.monotonic))
    cph.clear_cache()
    yield fake
    cph.clear_cache()


@pytest.fixture()
def tmux(monkeypatch):
    state = types.SimpleNamespace(calls=0, stderr=GONE, rc=1, stdout=b"", recorded=0)

    def fake_run(argv, **_kwargs):
        state.calls += 1
        return subprocess.CompletedProcess(argv, state.rc, state.stdout, state.stderr)

    def fake_recorded(_socket, _name):
        state.recorded += 1
        return None

    monkeypatch.setattr("src.core.tmux_transport.run.control_run", lambda *_a, **_k: None)
    monkeypatch.setattr("src.core.tmux_transport.run.tmux_argv_prefix", lambda socket: ["tmux", "-L", socket])
    monkeypatch.setattr("src.core.tmux_transport.run.subprocess.run", fake_run)
    monkeypatch.setattr(cph, "_recorded_home", fake_recorded)
    return state


def _row(epoch=1, record=None):
    return {"agent_family": "codex", "tmux_socket": "cloude", "tmux_name": "carnivore_gone", "tmux_created_epoch": epoch,
            "launch_record": record}


def _absent_calls(monkeypatch, row, clock, count, step):
    seen = []

    def presence(_uuid, *, codex_home):
        seen.append(codex_home)
        return types.SimpleNamespace(missing=True)

    monkeypatch.setattr("src.core.session_transcript_presence.codex_rollout_presence", presence)
    for _ in range(count):
        assert _transcript_absent(row, THREAD) is True
        clock.now += step
    return seen


def test_gone_session_is_asked_once_not_every_three_seconds(monkeypatch, clock, tmux):
    homes = _absent_calls(monkeypatch, _row(), clock, 10, 3.5)
    assert homes == [DEFAULT_CODEX_HOME] * 10
    assert tmux.calls == 1 and tmux.recorded == 1


def test_gone_answer_is_asked_again_when_the_row_identity_changes(monkeypatch, clock, tmux):
    _absent_calls(monkeypatch, _row(epoch=1), clock, 3, 3.5)
    _absent_calls(monkeypatch, _row(epoch=2), clock, 3, 3.5)
    assert tmux.calls == 2


def test_gone_answer_expires_after_the_long_bound(monkeypatch, clock, tmux):
    _absent_calls(monkeypatch, _row(), clock, 2, cph.GONE_TTL_SECONDS + 1)
    assert tmux.calls == 2


def test_an_unreadable_pane_that_is_not_proven_gone_keeps_the_short_retry(monkeypatch, clock, tmux):
    tmux.stderr = b"server exited unexpectedly\n"
    _absent_calls(monkeypatch, _row(), clock, 4, 3.5)
    assert tmux.calls == 4


def test_a_row_naming_an_account_is_never_remembered(monkeypatch, clock, tmux):
    record = '{"account": {"id": "ab12-work-relay-codex", "mode": "pinned"}}'
    _absent_calls(monkeypatch, _row(record=record), clock, 4, 3.5)
    assert tmux.calls == 4


def test_a_pane_that_becomes_readable_is_read_at_once(monkeypatch, clock, tmux, tmp_path):
    _absent_calls(monkeypatch, _row(), clock, 2, 3.5)
    assert tmux.calls == 1
    tmux.rc, tmux.stderr, tmux.stdout = 0, b"", f"CODEX_HOME={tmp_path}\n".encode()
    clock.now += 3.5
    assert cph.pane_codex_home("cloude", "carnivore_gone") == str(tmp_path)
    tmux.rc, tmux.stderr, tmux.stdout = 1, GONE, b""
    clock.now += cph.ANSWER_TTL_SECONDS + 1
    homes = _absent_calls(monkeypatch, _row(), clock, 1, 0)
    assert tmux.calls == 3
    assert homes == [DEFAULT_CODEX_HOME]


def test_a_readable_pane_answers_as_before(monkeypatch, clock, tmux, tmp_path):
    tmux.rc, tmux.stderr, tmux.stdout = 0, b"", f"CODEX_HOME={tmp_path}\n".encode()
    homes = _absent_calls(monkeypatch, _row(), clock, 5, 3.5)
    assert homes == [str(tmp_path)] * 5
    assert tmux.calls == 1


def test_callers_without_an_identity_behave_as_before(monkeypatch, clock, tmux):
    for _ in range(4):
        assert cph.pane_codex_home("cloude", "carnivore_gone") == DEFAULT_CODEX_HOME
        clock.now += 3.5
    assert tmux.calls == 4


def test_vm_stat_is_shared_inside_the_window_and_refreshed_after_it(monkeypatch):
    reads = []
    monkeypatch.setattr(host_metrics, "_static_sysctl_int", lambda _name: 16 * 1024 ** 3)
    monkeypatch.setattr(host_metrics, "_run", lambda argv: reads.append(argv) or "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\n")
    now = [50.0]
    monkeypatch.setattr(host_metrics, "_clock", lambda: now[0])
    host_metrics.clear_vm_stat_cache()
    first = host_metrics._memory_darwin()
    now[0] += host_metrics.VM_STAT_SHARE_SECONDS / 2
    assert host_metrics._memory_darwin() == first
    assert len(reads) == 1
    now[0] += host_metrics.VM_STAT_SHARE_SECONDS
    host_metrics._memory_darwin()
    assert len(reads) == 2
    host_metrics.clear_vm_stat_cache()


def test_a_failed_vm_stat_is_not_shared(monkeypatch):
    reads = []
    monkeypatch.setattr(host_metrics, "_static_sysctl_int", lambda _name: 16 * 1024 ** 3)
    monkeypatch.setattr(host_metrics, "_run", lambda argv: reads.append(argv))
    host_metrics.clear_vm_stat_cache()
    assert host_metrics._memory_darwin()["available"] is False
    assert host_metrics._memory_darwin()["available"] is False
    assert len(reads) == 2


@pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")
def test_process_cwd_comes_from_libproc_and_equals_lsof(monkeypatch, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    child = subprocess.Popen(["/bin/sleep", "30"], cwd=str(folder))
    try:
        from src.core import conversation_writers as cw

        expected = cw.lsof_cwd(child.pid)
        spawned = []
        real_run = subprocess.run
        monkeypatch.setattr(cw.subprocess, "run", lambda *a, **k: spawned.append(a) or real_run(*a, **k))
        assert process_cwd(child.pid) == expected == os.path.realpath(folder)
        assert spawned == []
    finally:
        child.kill()
        child.wait()


@pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")
def test_process_cwd_of_a_dead_pid_is_unknown_like_lsof():
    child = subprocess.Popen(["/usr/bin/true"])
    child.wait()
    from src.core import conversation_writers as cw

    assert process_cwd(child.pid) is None
    assert cw.lsof_cwd(child.pid) is None
