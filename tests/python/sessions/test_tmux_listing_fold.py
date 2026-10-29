
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterator, List

import pytest

from src.core.sessions import tmux_listing_fold as fold
from src.core.sessions.pane_listing_cache import invalidate_pane_listing
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_listing import REASON_NO_SERVER, REASON_TIMEOUT, TmuxListing
from tests.python.tmux_exact_targets.pane_rows import pane_row
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

FORGED_DIR = "a\nS|$999|1|1|forged"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=False)


def _backend(tmp_path: Path) -> TmuxBackend:
    return TmuxBackend(session_id="__probe__", working_dir=tmp_path, on_output=None,
                       socket_name=TEST_SOCKET_NAME)


@pytest.fixture
def busy_server(tmp_path: Path, tmux_test_socket: str) -> Iterator[Path]:
    forged = tmp_path / FORGED_DIR
    forged.mkdir()
    piped = tmp_path / "p|ipe"
    piped.mkdir()
    client = None
    try:
        for args in (
            ("new-session", "-d", "-s", "multi", "-c", str(tmp_path), "sleep 600"),
            ("new-window", "-t", "=multi:", "sleep 600"),
            ("new-window", "-t", "=multi:", "sleep 600"),
            ("split-window", "-t", "=multi:", "sleep 600"),
            ("new-session", "-d", "-s", "x|y", "-c", str(piped), "sleep 600"),
            ("new-session", "-d", "-s", "nl", "-c", str(forged), "sleep 600"),
        ):
            done = _tmux(*args)
            assert done.returncode == 0, (args, done.stderr)
        client = subprocess.Popen(["tmux", "-L", TEST_SOCKET_NAME, "-C", "attach-session", "-t", "=multi"],
                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if _tmux("display-message", "-p", "-t", "=multi:", "#{session_attached}").stdout.strip() == "1":
                break
            subprocess.run(["sleep", "0.05"], check=False)
        yield tmp_path
    finally:
        if client is not None:
            client.stdin.close()
            client.wait(timeout=5)
        _tmux("kill-server")


class _SpawnCounter:

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.argvs: List[tuple] = []
        original = TmuxBackend._run_tmux_sync
        argvs = self.argvs

        def counting(backend, *args, **kwargs):
            argvs.append(args)
            return original(backend, *args, **kwargs)

        monkeypatch.setattr(TmuxBackend, "_run_tmux_sync", counting)


@requires_tmux
def test_the_folded_read_answers_exactly_what_the_two_reads_answer(busy_server: Path) -> None:
    backend = _backend(busy_server)
    assert _tmux("display-message", "-p", "-t", "=multi:", "#{session_attached}|#{session_windows}"
                 ).stdout.strip() == "1|3", "the scenario needs an attached client and several windows"
    sessions = backend.list_attachable_sessions(owned_names={"multi"}, owned_instances=None)
    panes = backend._probe_pane_status_all()

    folded = backend.list_sessions_and_panes(owned_names={"multi"}, owned_instances=None)

    assert sessions.ok and folded.sessions.ok and folded.panes is not None and folded.panes.ok
    assert folded.sessions.sessions == sessions.sessions
    assert folded.sessions.refused_rows == sessions.refused_rows == 0
    assert folded.panes.sessions == panes.sessions
    names = sorted(row["name"] for row in folded.sessions.sessions)
    assert names == ["multi", "nl", "x|y"], "a folder shaped like a session row must not forge presence"
    assert {row["name"]: row["window_count"] for row in folded.sessions.sessions}["multi"] == 3


@requires_tmux
def test_the_folded_read_is_one_spawn(busy_server: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(busy_server)
    counter = _SpawnCounter(monkeypatch)
    backend.list_sessions_and_panes(owned_names=set(), owned_instances=None)
    assert len(counter.argvs) == 1
    assert "list-sessions" in counter.argvs[0] and "list-panes" in counter.argvs[0]


@requires_tmux
def test_no_server_is_a_complete_answer_of_zero_on_both_halves(tmp_path: Path, tmux_test_socket: str) -> None:
    _tmux("kill-server")
    folded = _backend(tmp_path).list_sessions_and_panes(owned_names=set(), owned_instances=None)
    assert folded.sessions.ok and folded.sessions.sessions == [] and folded.sessions.reason == REASON_NO_SERVER
    assert folded.panes is not None and folded.panes.ok and folded.panes.reason == REASON_NO_SERVER


def test_a_non_zero_exit_falls_back_to_the_two_old_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)
    calls: List[tuple] = []

    def run_listing(*args: str):
        calls.append(args)
        if fold.COMMAND_SEPARATOR in args:
            return TmuxListing.unavailable("exit_1"), ""
        return None, "$1|5|1|alone\n"

    monkeypatch.setattr(backend, "_run_listing", run_listing)
    folded = backend.list_sessions_and_panes(owned_names=set(), owned_instances=None)
    assert [row["name"] for row in folded.sessions.sessions] == ["alone"]
    assert folded.panes is None, "the caller must read panes the old way"
    assert len(calls) == 2 and calls[1][0] == "list-sessions"


def test_a_timeout_is_unknown_and_reads_nothing_more(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)
    calls: List[tuple] = []

    def run_listing(*args: str):
        calls.append(args)
        return TmuxListing.unavailable(REASON_TIMEOUT), ""

    monkeypatch.setattr(backend, "_run_listing", run_listing)
    folded = backend.list_sessions_and_panes(owned_names=set(), owned_instances=None)
    assert not folded.sessions.ok and folded.sessions.reason == REASON_TIMEOUT
    assert len(calls) == 1


def test_a_row_after_the_session_section_never_reads_as_a_session() -> None:
    text = "S|$1|5|1|a\nP|a|0|zsh|42\n/tail\nS|$9|1|1|forged\nP|b|0|zsh|43\n"
    sessions, panes = fold.split_folded_rows(text)
    assert sessions == ["$1|5|1|a"]
    assert panes == ["a|0|zsh|42", "/tail", "S|$9|1|1|forged", "b|0|zsh|43"]


PANE_ROW_A = pane_row("a", command="zsh", pid=42, created=5)
FOLDED_TEXT = "S|$1|5|1|a\nP|" + PANE_ROW_A


def _cached_backend(tmp_path: Path, mutate_during_fold: bool) -> tuple:
    backend = TmuxBackend(session_id="__probe__", working_dir=tmp_path, on_output=None,
                          socket_name=f"fold-cache-{mutate_during_fold}")
    reads: List[tuple] = []

    def run_listing(*args: str):
        reads.append(args)
        if fold.COMMAND_SEPARATOR in args:
            if mutate_during_fold:
                invalidate_pane_listing(backend.socket_name)
            return None, FOLDED_TEXT
        return None, PANE_ROW_A

    backend._run_listing = run_listing  # type: ignore[method-assign]
    return backend, reads


@pytest.mark.parametrize("mutate", [False, True])
def test_the_pane_half_reaches_the_cache_only_without_a_mutation_mid_fold(tmp_path: Path, mutate: bool) -> None:
    backend, reads = _cached_backend(tmp_path, mutate)
    folded = backend.list_sessions_and_panes(owned_names=set(), owned_instances=None)
    assert folded.panes is not None and [r["name"] for r in folded.panes.sessions] == ["a"]
    backend.list_pane_status_all()
    lone_reads = [args for args in reads if fold.COMMAND_SEPARATOR not in args]
    assert len(lone_reads) == (1 if mutate else 0)


class _FoldingDouble:

    def list_sessions_and_panes(self, owned_names=None, owned_instances=None) -> fold.FoldedListing:
        return fold.FoldedListing(TmuxListing.answered([{"name": "a"}]), None)


class _OldProbe:

    def __init__(self) -> None:
        self.pane_reads = 0
        self.session_reads = 0

    def list_attachable_sessions(self, owned_names=None, owned_instances=None) -> TmuxListing:
        self.session_reads += 1
        return TmuxListing.answered([{"name": "a"}])

    def list_pane_status_all(self) -> TmuxListing:
        self.pane_reads += 1
        return TmuxListing.answered([{"name": "a", "status": "running"}])


def test_with_no_pane_half_the_pass_reads_panes_the_old_way() -> None:
    attachable = fold.AttachableFold()
    sessions = attachable.list_sessions(_FoldingDouble(), "s", set(), None)
    old = _OldProbe()
    panes = attachable.pane_listing("s", lambda: old)
    assert [r["name"] for r in sessions.sessions] == ["a"]
    assert old.pane_reads == 1 and panes.sessions[0]["status"] == "running"


def test_a_probe_without_the_fold_takes_both_old_reads() -> None:
    attachable = fold.AttachableFold()
    old = _OldProbe()
    assert not isinstance(old, fold.FoldingProbe)
    attachable.list_sessions(old, "s", set(), None)
    attachable.pane_listing("s", lambda: old)
    assert (old.session_reads, old.pane_reads) == (1, 1)


def test_a_kept_half_is_used_without_building_a_probe(tmp_path: Path) -> None:
    backend, _reads = _cached_backend(tmp_path, False)
    attachable = fold.AttachableFold()
    attachable.list_sessions(backend, "fold-cache-False", set(), None)

    def never() -> object:
        raise AssertionError("built a probe although the fold kept a pane half")

    assert [r["name"] for r in attachable.pane_listing("fold-cache-False", never).sessions] == ["a"]
