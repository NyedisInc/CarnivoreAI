
from __future__ import annotations

import threading
import time

import pytest

from src.core.sessions.pane_listing_cache import PANE_LISTING_CACHE, args_mutate_sessions
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_transport import local as tmux_transport_local
from tests.python.tmux_exact_targets.pane_rows import pane_row

ROW = pane_row("cloude_a", pid=4821).encode()


@pytest.fixture
def backend(monkeypatch, tmp_path):
    PANE_LISTING_CACHE.invalidate()
    calls: list = []

    def fake_run(self, *args, **kwargs):
        calls.append(args)
        time.sleep(0.05)
        return 0, ROW, b""

    monkeypatch.setattr(TmuxBackend, "_run_tmux_sync", fake_run)
    monkeypatch.setattr(tmux_transport_local, "resolve_tmux_path", lambda: "/usr/bin/tmux")
    monkeypatch.setattr(tmux_transport_local, "tmux_argv_prefix", lambda socket: ["/usr/bin/tmux", "-L", socket])
    probe = TmuxBackend.for_external(
        session_name="__t__", working_dir=tmp_path, on_output=None, socket_name="test-cache-sock")
    yield probe, calls
    PANE_LISTING_CACHE.invalidate()


def _listing_calls(calls):
    return [c for c in calls if c and c[0] == "list-panes"]


def test_concurrent_callers_share_one_spawn_and_invalidate_respawns(backend):
    probe, calls = backend
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(probe.list_pane_status_all()))
               for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_listing_calls(calls)) == 1
    assert len(results) == 12 and all(r.sessions == results[0].sessions for r in results)
    assert results[0].sessions[0]["name"] == "cloude_a"

    again = probe.list_pane_status_all()
    assert len(_listing_calls(calls)) == 1 and again.sessions == results[0].sessions

    probe.list_pane_status_all(fresh=True)
    assert len(_listing_calls(calls)) == 2

    probe._run_tmux_sync("kill-session", "-t", "=cloude_a")
    PANE_LISTING_CACHE.invalidate("test-cache-sock")
    after = probe.list_pane_status_all()
    assert len(_listing_calls(calls)) == 3 and after.sessions == results[0].sessions


def test_real_runner_invalidates_on_mutating_verbs(monkeypatch, tmp_path):
    PANE_LISTING_CACHE.invalidate()
    spawned: list = []

    class Done:
        returncode, stdout, stderr = 0, ROW, b""

    monkeypatch.setattr("subprocess.run", lambda argv, **kw: (spawned.append(argv), Done())[1])
    monkeypatch.setattr(tmux_transport_local, "resolve_tmux_path", lambda: "/usr/bin/tmux")
    monkeypatch.setattr(tmux_transport_local, "tmux_argv_prefix", lambda socket: ["/usr/bin/tmux", "-L", socket])
    probe = TmuxBackend.for_external(
        session_name="__t__", working_dir=tmp_path, on_output=None, socket_name="test-cache-sock2")
    probe.list_pane_status_all()
    probe.list_pane_status_all()
    assert sum("list-panes" in a for a in spawned) == 1
    probe._run_tmux_sync("respawn-pane", "-k", "-t", "=x")
    probe.list_pane_status_all()
    assert sum("list-panes" in a for a in spawned) == 2
    PANE_LISTING_CACHE.invalidate()


def test_failed_probe_is_not_cached_and_verbs():
    assert args_mutate_sessions(["new-session", "-d"]) and not args_mutate_sessions(["list-panes", "-a"])
    cache = __import__("src.core.sessions.pane_listing_cache", fromlist=["x"]).PaneListingCache()
    n = {"c": 0}

    def load():
        n["c"] += 1
        return False

    cache.get("k", load, cacheable=bool)
    cache.get("k", load, cacheable=bool)
    assert n["c"] == 2
