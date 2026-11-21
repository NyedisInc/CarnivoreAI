
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.pack.jobs import gitio, guards, paths, policy
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import (HostJob, HostState, JobError, JobRecord, JobRequest, JobState, StartBody)

UID = "uid12345678"


@pytest.fixture()
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "state dir")


def test_set_state_one_event_and_refuses_after_terminal(store: JobStore):
    store.create_job(JobRecord(id="job_000000000001", state=JobState.WAITING_APPROVAL))
    before = len(store.events("job_000000000001"))
    rec = store.set_state("job_000000000001", JobState.RUNNING, note="go", peer_label="b")
    assert rec.state is JobState.RUNNING and rec.peer_label == "b"
    assert len(store.events("job_000000000001")) == before + 1
    store.set_state("job_000000000001", JobState.DONE, exit_code=0)
    assert store.get_job("job_000000000001").ended_at is not None
    with pytest.raises(JobError) as err:
        store.set_state("job_000000000001", JobState.FAILED)
    assert err.value.code == "job_ended"
    with pytest.raises(TypeError):
        store.set_state("job_000000000001", JobState.DONE, bogus=1)


def test_find_live_by_idem_ignores_terminal(store: JobStore):
    store.create_job(JobRecord(id="job_000000000002", idem_key="k", state=JobState.WAITING_APPROVAL))
    assert store.find_live_by_idem("k").id == "job_000000000002"
    store.set_state("job_000000000002", JobState.STOPPED)
    assert store.find_live_by_idem("k") is None
    assert [j.id for j in store.list_jobs(live_only=True)] == []
    assert len(store.list_jobs(project_uid="")) == 1


def test_host_rows(store: JobStore):
    first = store.host_put(HostJob(job_id="job_000000000003", caller_install="a"))
    again = store.host_put(HostJob(job_id="job_000000000003", caller_install="other"))
    assert again.caller_install == "a" and first.state is HostState.PREPARING
    assert store.host_set("job_000000000003", state=HostState.RUNNING).state is HostState.RUNNING
    assert [h.job_id for h in store.host_list([HostState.RUNNING])] == ["job_000000000003"]
    assert store.host_list([HostState.FAILED]) == []


def test_slot_claim_three_then_none_and_free_reuse(store: JobStore):
    got = [store.slot_claim(UID, "/r", lambda n: f"/s/slot{n}", f"j{i}") for i in range(3)]
    assert [g[0] for g in got] == [1, 2, 3] and all(g[2] for g in got)
    assert store.slot_claim(UID, "/r", lambda n: f"/s/slot{n}", "j9") is None
    store.slot_free("/s/slot2", memo={"a": "b"})
    again = store.slot_claim(UID, "/r", lambda n: f"/s/slot{n}", "j9")
    assert again == (2, "/s/slot2", False)
    assert store.slot_rows(UID)[1]["memo"] == {"a": "b"}
    store.slot_free("/s/slot1", keep_until=9e12)
    assert store.slot_claim(UID, "/r", lambda n: f"/s/slot{n}", "j10") is None
    store.slot_drop("/s/slot1")
    assert len(store.slot_rows(UID)) == 2


def test_concurrent_claims_never_share(store: JobStore):
    results, lock = [], threading.Lock()

    def claim(i: int) -> None:
        r = JobStore(store._path.parent).slot_claim(UID, "/r", lambda n: f"/s/slot{n}", f"j{i}")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    won = [r for r in results if r]
    assert len(won) == 3 and len({r[1] for r in won}) == 3


def test_policy_defaults_and_lists(store: JobStore):
    p = policy.get(store, UID)
    assert (p.auto_delegate, p.never_use, p.carry, p.bring_back, p.setup) == (False, [], [], [], None)
    policy.set_auto(store, UID, True)
    policy.set_lists(store, UID, never_use=["iid-x"], setup=["make deps"])
    p = policy.get(store, UID)
    assert p.auto_delegate and p.never_use == ["iid-x"] and p.setup == ["make deps"] and p.carry == []
    policy.set_lists(store, UID, setup=[])
    assert policy.get(store, UID).setup is None
    policy.record_auto_replica(store, UID, "iid-b")
    policy.record_auto_replica(store, UID, "iid-b")
    assert policy.auto_replicas(store, UID) == ["iid-b"]
    policy.forget_auto_replica(store, UID, "iid-b")
    assert policy.auto_replicas(store, UID) == []


def test_peer_bases(store: JobStore):
    assert store.base_get(UID, "p") is None
    store.base_set(UID, "p", "a" * 40)
    store.base_set(UID, "p", "b" * 40)
    assert store.base_get(UID, "p") == "b" * 40
    store.base_clear(UID, "p")
    assert store.base_get(UID, "p") is None


def test_gitio_strips_planted_git_env(tmp_path: Path, monkeypatch):
    repo = tmp_path / "re po"
    repo.mkdir()
    gitio.run(["init", "-q"], cwd=str(repo))
    planted = tmp_path / "planted index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(planted))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
    (repo / "f.txt").write_text("x")
    gitio.run(["add", "f.txt"], cwd=str(repo))
    assert not planted.exists() and (repo / ".git" / "index").exists()
    assert gitio.out(gitio.run(["ls-files"], cwd=str(repo))) == "f.txt"
    cp = subprocess.run(["git", "add", "f.txt"], cwd=repo, capture_output=True)
    assert cp.returncode != 0 or planted.exists()
    with pytest.raises(JobError) as err:
        gitio.run(["rev-parse", "nope-ref"], cwd=str(repo))
    assert err.value.code == "git_failed" and err.value.detail == "git rev-parse exited 128"
    assert gitio.run(["rev-parse", "nope-ref"], cwd=str(repo), check=False).returncode != 0


def test_paths(tmp_path: Path):
    with pytest.raises(JobError) as err:
        paths.check_root(tmp_path / "Dropbox" / "jobs")
    assert err.value.code == "jobs_root_in_cloud"
    root = paths.check_root(tmp_path / "jobs root")
    assert paths.side_repo_dir(root, UID) == root / "repos" / f"{UID}.git"
    assert paths.slot_dir(root, "tra der/x", UID, 2) == root / "folders" / f"tra_der_x-{UID[:8]}" / "slot2"
    m = paths.meta_dir(root, "job_0123456789ab")
    assert oct(m.stat().st_mode & 0o777) == "0o700"
    assert paths.session_name("job_0123456789ab") == "cvjob_0123456789ab"
    for bad in ("../x", "a/b", "short"):
        with pytest.raises(JobError):
            paths.side_repo_dir(root, bad)
    with pytest.raises(JobError):
        paths.meta_dir(root, "job_../../etc")
    assert paths.new_job_id().startswith("job_") and len(paths.new_job_id()) == 16


def test_guards(tmp_path: Path):
    d = tmp_path / "n"
    d.mkdir()
    big = d / "big"
    with open(big, "wb") as fh:
        fh.truncate(guards.MAX_UNTRACKED_BYTES + 1)
    assert "node_modules" in guards.skip_reason("web/node_modules/a.js", str(d))
    assert guards.skip_reason("sub/", str(d)) == "a nested repository"
    (d / ".git").mkdir()
    assert guards.skip_reason("n", str(d)) == "a nested repository"
    assert "MiB" in guards.skip_reason("big", str(big))
    assert guards.skip_reason("ok.txt", str(d / "missing")) is None
    assert ":(exclude,glob)**/node_modules/**" in guards.exclude_pathspecs()


def test_request_and_start_body_validation():
    JobRequest(command="x", folder="/a b").validate()
    for kw in ({"folder": "rel"}, {"kind": "nope"}, {"time_cap_s": 0}, {"command": ""}, {"outputs": ["../x"]},
               {"env": {"1bad": "v"}}, {"env": {"A": "v\0"}}):
        with pytest.raises(JobError):
            JobRequest(**{"command": "x", "folder": "/a", **kw}).validate()
    ok = dict(job_id="job_0123456789ab", project_uid=UID, snapshot_commit="a" * 40, snapshot_blob_id="b1", command="x", kind="suite",
              caller_roots=["/r"])
    assert StartBody(**ok).setup is None
    for bad in ({"scope": "../x"}, {"outputs": ["/abs"]}, {"caller_roots": []}, {"caller_roots": ["rel"]},
                {"setup": ["x"] * 11}, {"job_id": "bad"}, {"extra": 1}):
        with pytest.raises(ValidationError):
            StartBody(**{**ok, **bad})
