
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.core.perf_hooks import executors
from src.core.attention_reader import AttentionEvidenceReader
from src.core.catalog import hosted_api
from src.core.pack.jobs import engine as jobs_engine, gitio
from src.core.swarm import learning


def test_bulkhead_executors_are_isolated_from_default() -> None:
    att = executors.attention_executor()
    pre = executors.precheck_executor()
    mnt = executors.maintenance_executor()
    assert att is not pre
    assert pre is not mnt
    assert att is not mnt
    assert executors.interactive_max_workers() >= 16


def test_git_info_fast_resolves_repo_and_worktree_without_subprocess(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)

    wt_gitdir = repo / ".git" / "worktrees" / "wt1"
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "commondir").write_text("../..\n")
    wt = tmp_path / "wt1"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_gitdir}\n")

    def forbid_git(*args, **kwargs):
        raise AssertionError("git subprocess must not run for standard repo or worktree")

    monkeypatch.setattr(gitio, "run", forbid_git)

    top, common = jobs_engine.Engine._git_info_fast(str(sub.resolve()))
    assert top == str(repo.resolve())
    assert common == str((repo / ".git").resolve())

    wt_top, wt_common = jobs_engine.Engine._git_info_fast(str(wt.resolve()))
    assert wt_top == str(wt.resolve())
    assert wt_common == str((repo / ".git").resolve())


def test_attention_reader_prepare_pass_reuses_within_window() -> None:
    mgr = MagicMock()
    mgr._build_tmux_status_map.return_value = MagicMock(complete=False)
    mgr._wrappers_reader.return_value = {}
    reader = AttentionEvidenceReader(mgr, instance_for=lambda _sid: (None, None))

    t0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    reader.prepare_pass(t0, allow_reuse=False)
    assert mgr._build_tmux_status_map.call_count == 1

    reader.prepare_pass(t0 + timedelta(milliseconds=150), allow_reuse=True)
    assert mgr._build_tmux_status_map.call_count == 1

    reader.prepare_pass(t0 + timedelta(milliseconds=200), allow_reuse=False)
    assert mgr._build_tmux_status_map.call_count == 2


def test_learning_wake_failure_backoff_pauses_permanent_refusals() -> None:
    learning.clear_backoff()
    d1 = learning._record_wake_failure(99, "transient error", 100.0)
    assert d1 == learning._FAILURE_BACKOFF_S[0]
    d2 = learning._record_wake_failure(99, "transient error", 101.0)
    assert d2 == learning._FAILURE_BACKOFF_S[1]

    d_perm = learning._record_wake_failure(100, "recreate_refused: cannot_determine", 100.0)
    assert d_perm == learning._FAILURE_BACKOFF_S[-1]

    learning.clear_backoff(99)
    assert 99 not in learning._wake_backoff
    learning.clear_backoff()


@pytest.mark.asyncio
async def test_catalog_hosted_circuit_breaker_fails_fast_after_connect_timeout(monkeypatch) -> None:
    calls = 0

    def timeout_transport(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_transport))

    async def fake_shared():
        return client

    hosted_api.reset_circuit_breaker()
    monkeypatch.setattr(hosted_api, "shared_client", fake_shared)
    try:
        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/me")
        first_attempts = calls
        assert first_attempts >= 1

        with pytest.raises(hosted_api.HostedUnavailable):
            await hosted_api.call("https://catalog.example/api/v1", "GET", "/me")
        assert calls == first_attempts
    finally:
        hosted_api.reset_circuit_breaker()
        await client.aclose()
