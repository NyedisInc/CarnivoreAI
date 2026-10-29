
from __future__ import annotations

import os
import subprocess
import time
import tracemalloc
from contextlib import closing
from pathlib import Path

import pytest
import structlog
import structlog.testing

from src.core.db import connect, db_path_for
from src.core.db_steps import run_chain
from src.core.swarm import commit, store, visibility

SLUG = "loki"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("hi\n")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "init")
    return r


@pytest.fixture
def conn(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as c:
        run_chain(c, 0, 60)
        yield c


def _agent(repo: Path) -> dict:
    return {"slug": SLUG, "rank": "project", "memory_scope": "project", "repo_dir": str(repo)}


def _write_memory(repo: Path, text: str = "a fact\n") -> None:
    mem = repo / ".claude" / "agent-memory" / SLUG
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "MEMORY.md").write_text(text)


def _stub(verdict: str, calls: list | None = None):
    def fetch(owner: str, name: str) -> str:
        if calls is not None:
            calls.append((owner, name))
        return verdict
    return fetch


TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def _hook(repo: Path, body: str, name: str = "pre-commit") -> None:
    path = repo / ".git" / "hooks" / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def test_only_memory_paths_land_and_owner_staged_file_stays_staged(repo, conn):
    _write_memory(repo)
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / f"{SLUG}.md").write_text("---\nname: loki\n---\nbody\n")
    (repo / "owner.txt").write_text("staged by owner\n")
    _git(repo, "add", "owner.txt")
    (repo / "dirty.txt").write_text("unstaged junk\n")
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.COMMITTED and res.sha
    landed = set(_git(repo, "show", "--name-only", "--format=", "HEAD").split())
    assert landed == {f".claude/agent-memory/{SLUG}/MEMORY.md", f".claude/agents/{SLUG}.md"}
    assert _git(repo, "diff", "--cached", "--name-only").split() == ["owner.txt"]
    assert "dirty.txt" in _git(repo, "status", "--porcelain")
    assert _git(repo, "log", "-1", "--format=%B").strip() == f"swarm: {SLUG} memory"


def test_clean_paths_make_no_commit(repo, conn):
    assert commit.commit_memory(conn, _agent(repo)).status == commit.NOTHING


def test_mid_rebase_skips_and_leaves_no_commit(repo, conn):
    _write_memory(repo)
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / ".git" / "rebase-merge").mkdir()
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.SKIPPED and res.reason == "in_progress_rebase_merge"
    assert _git(repo, "rev-parse", "HEAD").strip() == head


def test_detached_head_skips(repo, conn):
    _write_memory(repo)
    _git(repo, "checkout", "-q", "--detach")
    assert commit.commit_memory(conn, _agent(repo)).reason == "detached_head"


def test_public_origin_records_pending_approval_then_approval_commits(repo, conn):
    _git(repo, "remote", "add", "origin", "https://tok:x@github.com/o/r.git")
    _write_memory(repo)
    head = _git(repo, "rev-parse", "HEAD").strip()
    res = commit.commit_memory(conn, _agent(repo), fetch=_stub("public"))
    assert res.status == commit.PENDING_APPROVAL and res.detail == "public"
    assert _git(repo, "rev-parse", "HEAD").strip() == head
    row = store.get_visibility(conn, str(repo))
    assert row["visibility"] == "public" and row["approved_at"] is None
    assert row["remote_url"] == "https://github.com/o/r.git"
    assert visibility.approve(conn, str(repo), res.fingerprint)
    assert commit.commit_memory(conn, _agent(repo), fetch=_stub("public")).status == commit.COMMITTED


def test_unknown_visibility_fails_closed_and_private_commits(repo, conn):
    _git(repo, "remote", "add", "origin", "https://example.com/o/r.git")
    _write_memory(repo)
    assert commit.commit_memory(conn, _agent(repo)).status == commit.PENDING_APPROVAL
    _git(repo, "remote", "set-url", "origin", "https://github.com/o/r")
    conn.execute("DELETE FROM swarm_repo_visibility")
    assert commit.commit_memory(conn, _agent(repo), fetch=_stub("private")).status == commit.COMMITTED


def test_secret_in_changed_file_refuses_without_the_value(repo, conn):
    head = _git(repo, "rev-parse", "HEAD").strip()
    _write_memory(repo, "token AKIAIOSFODNN7EXAMPLE and ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8\n")
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.REFUSED_SECRET and res.detail.endswith("MEMORY.md")
    assert "AKIA" not in repr(res)
    assert _git(repo, "rev-parse", "HEAD").strip() == head


def test_task_rank_skips(repo, conn):
    _write_memory(repo)
    agent = _agent(repo) | {"rank": "task", "memory_scope": "local"}
    assert commit.commit_memory(conn, agent).reason == "local_scope"



def test_folder_below_the_git_root_is_skipped_and_nothing_lands(repo, conn):
    sub = repo / "carnivore" / "foo"
    sub.mkdir(parents=True)
    _write_memory(sub, "token " + TOKEN + "\n")
    head = _head(repo)
    res = commit.commit_memory(conn, _agent(sub))
    assert res.status == commit.SKIPPED and res.reason == "not_repo_root"
    assert _head(repo) == head and _git(repo, "ls-files").split() == ["README.md"]


def test_unreadable_listed_file_is_refused_not_clean(repo, conn):
    _write_memory(repo)
    mem = repo / ".claude" / "agent-memory" / SLUG / "MEMORY.md"
    mem.chmod(0)
    try:
        if os.access(mem, os.R_OK):
            pytest.skip("running as a user that ignores file modes")
        head = _head(repo)
        res = commit.commit_memory(conn, _agent(repo))
        assert res.status == commit.SKIPPED and res.reason == "unscannable_file" and res.detail.endswith("MEMORY.md")
        assert _head(repo) == head
    finally:
        mem.chmod(0o644)


def test_oversize_file_is_refused_even_with_the_token_past_the_scan_limit(repo, conn):
    _write_memory(repo, "x" * (commit.MAX_SCAN_BYTES + 1) + "\n" + TOKEN + "\n")
    head = _head(repo)
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.SKIPPED and res.reason == "unscannable_file"
    assert _head(repo) == head


def test_rejecting_hook_leaves_the_owners_index_exactly_as_it_was(repo, conn):
    _write_memory(repo)
    (repo / "owner.txt").write_text("owner\n")
    _git(repo, "add", "owner.txt")
    _hook(repo, "exit 1")
    head = _head(repo)
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.SKIPPED and res.reason == "commit_failed"
    assert _head(repo) == head
    assert _git(repo, "diff", "--cached", "--name-only").split() == ["owner.txt"]
    assert _git(repo, "ls-files").split() == ["README.md", "owner.txt"]
    (repo / ".git" / "hooks" / "pre-commit").unlink()
    _git(repo, "commit", "-q", "-m", "owner work")
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["owner.txt"]


def test_gitignored_codex_twin_neither_blocks_nor_leaks(repo, conn):
    (repo / ".gitignore").write_text(".codex/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore")
    _write_memory(repo)
    (repo / ".codex" / "agents").mkdir(parents=True)
    (repo / ".codex" / "agents" / f"{SLUG}.toml").write_text("x = 1\n")
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.COMMITTED
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == [f".claude/agent-memory/{SLUG}/MEMORY.md"]


def test_timeout_leaves_no_index_lock_and_no_marks(repo, conn, monkeypatch):
    _write_memory(repo)
    _hook(repo, "sleep 30")
    monkeypatch.setattr(commit, "COMMIT_TIMEOUT_S", 1)
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.SKIPPED and res.reason == "git_timeout"
    assert not list((repo / ".git").glob("*.lock")) and not list((repo / ".git").glob("next-index*"))
    assert _git(repo, "ls-files").split() == ["README.md"]


def test_origin_read_failure_fails_closed(repo, conn, monkeypatch):
    _write_memory(repo)

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(visibility, "run_git", boom)
    res = commit.commit_memory(conn, _agent(repo), fetch=_stub("private"))
    assert res.status == commit.PENDING_APPROVAL and res.detail == "unknown"


def test_non_origin_remote_is_checked_with_the_parsed_owner_and_repo(repo, conn):
    _git(repo, "remote", "add", "upstream", "git@github.com:own/rep.git")
    _write_memory(repo)
    calls: list = []
    res = commit.commit_memory(conn, _agent(repo), fetch=_stub("public", calls))
    assert res.status == commit.PENDING_APPROVAL and calls == [("own", "rep")]


def test_private_origin_with_a_public_push_url_needs_approval(repo, conn):
    _git(repo, "remote", "add", "origin", "https://github.com/o/priv")
    _git(repo, "remote", "set-url", "--push", "origin", "https://github.com/o/pub")
    _write_memory(repo)
    res = commit.commit_memory(conn, _agent(repo), fetch=lambda o, r: "public" if r == "pub" else "private")
    assert res.status == commit.PENDING_APPROVAL and res.detail == "public"


def test_local_is_not_permanent_and_a_changed_remote_set_voids_the_approval(repo, conn):
    _write_memory(repo)
    assert commit.commit_memory(conn, _agent(repo)).status == commit.COMMITTED
    assert store.get_visibility(conn, str(repo))["visibility"] == "local"
    _git(repo, "remote", "add", "origin", "https://github.com/o/r")
    (repo / ".claude" / "agent-memory" / SLUG / "MEMORY.md").write_text("more\n")
    res = commit.commit_memory(conn, _agent(repo), fetch=_stub("public"))
    assert res.status == commit.PENDING_APPROVAL
    assert visibility.approve(conn, str(repo), res.fingerprint)
    assert commit.commit_memory(conn, _agent(repo), fetch=_stub("public")).status == commit.COMMITTED
    _git(repo, "remote", "add", "mirror", "https://github.com/o/mirror")
    (repo / ".claude" / "agent-memory" / SLUG / "MEMORY.md").write_text("again\n")
    res = commit.commit_memory(conn, _agent(repo), fetch=_stub("public"))
    assert res.status == commit.PENDING_APPROVAL
    assert store.get_visibility(conn, str(repo))["approved_at"] is None


def test_hook_output_is_never_logged(repo, conn):
    _write_memory(repo)
    _hook(repo, f"echo leaked {TOKEN} >&2; exit 1")
    with structlog.testing.capture_logs() as logs:
        res = commit.commit_memory(conn, _agent(repo))
    assert res.reason == "commit_failed"
    assert TOKEN not in repr(logs) and any(e.get("returncode") == 1 for e in logs)


def test_detached_hook_child_holding_the_pipe_does_not_hide_a_landed_commit(repo, conn, monkeypatch):
    _write_memory(repo)
    _hook(repo, "python3 -c 'import os,time; os.setsid(); time.sleep(30)' &\nexit 0")
    monkeypatch.setattr(commit, "COMMIT_TIMEOUT_S", 2)
    start = time.monotonic()
    res = commit.commit_memory(conn, _agent(repo))
    assert res.status == commit.COMMITTED
    assert time.monotonic() - start < 2 + 5
    assert not list((repo / ".git").glob("*.lock"))


def test_approval_applies_only_to_the_remote_set_the_card_showed(repo, conn):
    _git(repo, "remote", "add", "origin", "https://github.com/o/r")
    _write_memory(repo)
    res = commit.commit_memory(conn, _agent(repo), fetch=_stub("public"))
    assert res.status == commit.PENDING_APPROVAL and res.fingerprint
    _git(repo, "remote", "add", "mirror", "https://github.com/o/mirror")
    assert not visibility.approve(conn, str(repo), res.fingerprint)
    assert store.get_visibility(conn, str(repo))["approved_at"] is None
    _git(repo, "remote", "remove", "mirror")
    assert not visibility.approve(conn, str(repo), "0" * 64)
    assert store.get_visibility(conn, str(repo))["approved_at"] is None
    assert visibility.approve(conn, str(repo), res.fingerprint)


def test_a_hook_flooding_stderr_is_never_read_back(repo, conn):
    _write_memory(repo)
    _hook(repo, "head -c 50000000 /dev/zero >&2; exit 1")
    tracemalloc.start()
    try:
        res = commit.commit_memory(conn, _agent(repo))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert res.status == commit.SKIPPED and res.reason == "commit_failed"
    assert peak < 10_000_000


def test_git_stdout_over_the_cap_is_a_failure_not_a_truncation(repo, monkeypatch):
    from src.core.swarm import gitrun
    monkeypatch.setattr(gitrun, "MAX_OUT", 4)
    out = gitrun.run_git(repo, "log", "--format=%H", timeout=10)
    assert out.returncode == -1 and out.stdout == ""
