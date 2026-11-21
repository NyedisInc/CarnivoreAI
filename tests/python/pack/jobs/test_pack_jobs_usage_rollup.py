
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.core.pack.jobs import ddl
from src.core.pack.jobs.usage_rollup import delegated_for
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobRecord, JobState
from src.models.session_token_usage import SessionTokenUsage


def _job(store: JobStore, n: int, caller: str, body: str, usage: dict | None, label: str | None = None) -> None:
    store.create_job(JobRecord(id=f"job_{n:012x}", caller_session=caller, state=JobState.RUNNING))
    store.set_state(f"job_{n:012x}", JobState.DONE, body=body, account_label=label, usage_json=json.dumps(usage) if usage else None)


def test_sums_only_this_sessions_agent_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    _job(store, 1, "uuid-a", "agent", {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 2, "cache_write_tokens": 1, "cost_usd": 0.25}, "work")
    _job(store, 2, "ses_a", "agent", {"input_tokens": 100, "output_tokens": 50, "cost_usd": None}, "home")
    _job(store, 3, "uuid-a", "agent", {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.5}, "work")
    _job(store, 4, "uuid-b", "agent", {"input_tokens": 999, "output_tokens": 999})
    _job(store, 5, "uuid-a", "command", {"input_tokens": 777, "output_tokens": 777})
    _job(store, 6, "uuid-a", "agent", None)
    got = delegated_for("ses_a", "uuid-a", state_dir=tmp_path)
    assert got is not None
    assert (got.jobs, got.input_tokens, got.output_tokens, got.cache_read_tokens, got.cache_write_tokens) == (3, 111, 56, 2, 1)
    assert got.cost_usd == 0.75 and got.accounts == ["work", "home"]


def test_none_when_nothing_delegated(tmp_path: Path) -> None:
    assert delegated_for("ses_a", "uuid-a", state_dir=tmp_path) is None
    assert not (tmp_path / ddl.FILENAME).exists()
    JobStore(tmp_path).create_job(JobRecord(id="job_000000000001", caller_session="x", state=JobState.DONE))
    assert delegated_for("ses_a", "uuid-a", state_dir=tmp_path) is None
    assert delegated_for(None, None, state_dir=tmp_path) is None


def test_unpriced_jobs_leave_cost_none(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    _job(store, 1, "uuid-a", "agent", {"input_tokens": 3, "output_tokens": 4})
    got = delegated_for(None, "uuid-a", state_dir=tmp_path)
    assert got is not None and got.cost_usd is None and got.jobs == 1


def test_read_only_and_old_file(tmp_path: Path) -> None:
    db = tmp_path / ddl.FILENAME
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jobs (id TEXT, caller_session TEXT)")
    conn.commit()
    conn.close()
    before = db.read_bytes()
    assert delegated_for("ses_a", "uuid-a", state_dir=tmp_path) is None
    assert db.read_bytes() == before


def test_usage_answer_carries_delegated_only_when_set() -> None:
    assert SessionTokenUsage(state="absent", as_of="2026-11-16T00:00:00Z").delegated is None
    assert "delegated" in SessionTokenUsage.model_fields


def test_a_hostile_stored_number_never_reaches_the_sum(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    _job(store, 1, "uuid-a", "agent", {"input_tokens": 7, "output_tokens": 10 ** 29, "cost_usd": float("inf")}, "work")
    _job(store, 2, "uuid-a", "agent", {"input_tokens": float("nan"), "output_tokens": 3, "cost_usd": 1e300})
    got = delegated_for(None, "uuid-a", state_dir=tmp_path)
    assert got is not None and (got.input_tokens, got.output_tokens, got.cost_usd) == (7, 3, None)
    assert json.dumps(got.model_dump(), allow_nan=False)


def test_running_on_a_peer_counts_live_jobs_even_without_usage(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    for n, state, peer in ((1, JobState.RUNNING, "p1"), (2, JobState.COLLECTING, "p1"), (3, JobState.PLACING, None), (4, JobState.QUESTION, "p1")):
        store.create_job(JobRecord(id=f"job_{n:012x}", caller_session="uuid-a", state=state, peer_install_id=peer, peer_label="tower" if peer else None))
    got = delegated_for("ses_a", "uuid-a", state_dir=tmp_path)
    assert got is not None and (got.jobs, got.running, got.running_on) == (0, 2, ["tower"])


def test_command_only_history_counts_remote_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    for n in (1, 2):
        store.create_job(JobRecord(id=f"job_{n:012x}", caller_session="uuid-a", state=JobState.RUNNING))
        store.set_state(f"job_{n:012x}", JobState.DONE, body="command", peer_install_id="inst-1", peer_label="tower")
    _job(store, 3, "uuid-a", "command", None)
    got = delegated_for(None, "uuid-a", state_dir=tmp_path)
    assert got is not None and (got.jobs, got.remote_jobs, got.ran_on, got.running) == (0, 2, ["tower"], 0)
