
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from src.core.checkpoints import capture as cap
from src.core.checkpoints import cleanup
from src.core.checkpoints.store import CheckpointStore

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=ENV, check=True, capture_output=True, text=True).stdout


def files_in(directory: Path) -> dict:
    out = {}
    for root, _, names in os.walk(directory):
        for name in names:
            p = Path(root) / name
            st = p.lstat()
            out[str(p)] = (p.read_bytes() if p.is_file() else b"", st.st_mtime_ns)
    return out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "pkg" / "deep").mkdir(parents=True)
    (r / "a.txt").write_text("a\n")
    (r / "pkg" / "deep" / "b.txt").write_text("b\n")
    (r / ".gitignore").write_text("node_modules/\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    (r / ".git" / "info").mkdir(exist_ok=True)
    (r / ".git" / "info" / "exclude").write_text("local-only.txt\n")
    (r / "a.txt").write_text("a staged\n")
    git(r, "add", "a.txt")
    return r


def test_capture_never_writes_the_repo_and_leaves_out_secrets(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state"
    store = CheckpointStore(state / "bookmarks.db")
    (repo / "a.txt").write_text("a edited in the turn\n")
    (repo / "pkg" / "deep" / "new.py").write_text("print(1)\n")
    (repo / "pkg" / "deep" / "b.txt").unlink()
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.js").write_text("ignored\n")
    (repo / "local-only.txt").write_text("excluded by info/exclude\n")
    (repo / ".env.local").write_text("TOKEN=not-for-git\n")
    (repo / "aws_credentials.json").write_text("{}\n")
    with open(repo / "huge.bin", "wb") as fh:
        fh.truncate(cap.MAX_FILE_BYTES + 1)
    head_before, branch_before = git(repo, "rev-parse", "HEAD"), git(repo, "symbolic-ref", "HEAD")
    git_before = files_in(repo / ".git")

    started = time.monotonic()
    result = cap.capture(repo / "pkg", session_uuid="sess-1", conversation="conv", prompt_uuid="p-1",
                         store=store, state_root=state)
    elapsed = time.monotonic() - started

    assert result.skipped is None and result.checkpoint is not None
    assert elapsed < 3.0, f"fast path over budget: {elapsed:.2f}s"
    after = files_in(repo / ".git")
    assert set(after) == set(git_before), "no file is added to or removed from the repo's .git"
    assert {p: v[0] for p, v in after.items()} == {p: v[0] for p, v in git_before.items()}, "no byte changes"
    index = str(repo / ".git" / "index")
    assert after[index] == git_before[index], "the real index keeps its bytes AND its mtime"
    assert git(repo, "rev-parse", "HEAD") == head_before and git(repo, "symbolic-ref", "HEAD") == branch_before
    assert git(repo, "diff", "--cached", "--name-only").split() == ["a.txt"], "the owner's staged state is untouched"

    shadow = Path(result.checkpoint.shadow)
    listed = subprocess.run(["git", f"--git-dir={shadow}", "ls-tree", "-r", "--name-only", result.checkpoint.commit_sha],
                            check=True, capture_output=True, text=True).stdout.split()
    assert "pkg/deep/new.py" in listed and "a.txt" in listed
    assert "pkg/deep/b.txt" not in listed, "a deletion in the turn is in the snapshot"
    for absent in ("node_modules/x.js", "local-only.txt", ".env.local", "aws_credentials.json", "huge.bin"):
        assert absent not in listed, absent
    assert {".env.local", "aws_credentials.json", "huge.bin"} <= set(result.left_out)
    content = subprocess.run(["git", f"--git-dir={shadow}", "show", f"{result.checkpoint.commit_sha}:a.txt"],
                             check=True, capture_output=True, text=True).stdout
    assert content == "a edited in the turn\n"
    assert not any((shadow.parent / cap.SCRATCH_DIRNAME).iterdir()), "no scratch index left behind"
    assert result.checkpoint.head_sha == head_before.strip()


def test_non_git_folder_is_skipped(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "state" / "bookmarks.db")
    (tmp_path / "plain").mkdir()
    assert cap.capture(tmp_path / "plain", session_uuid="s", conversation="", prompt_uuid="p", store=store,
                       state_root=tmp_path / "state").skipped == "not_git"


def test_cleanup_keeps_newest_twenty_young_and_pinned(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state"
    store = CheckpointStore(state / "bookmarks.db")
    for i in range(23):
        (repo / "a.txt").write_text(f"turn {i}\n")
        assert cap.capture(repo, session_uuid="s", conversation="c", prompt_uuid=f"p{i:02d}", store=store,
                           state_root=state).checkpoint is not None
    with sqlite3.connect(state / "bookmarks.db") as conn:
        conn.execute("CREATE TABLE bookmarks (session_uuid TEXT, entry_uuid TEXT)")
        conn.execute("INSERT INTO bookmarks VALUES ('s', 'p00')")
        conn.execute("UPDATE turn_checkpoints SET created_at = created_at - 8 * 86400 WHERE prompt_uuid IN ('p05', 'p00')")
    removed = cleanup.prune_session(store, "s")
    kept = {c.prompt_uuid for c in store.for_session("s")}
    assert "p00" in kept, "a bookmarked snapshot is kept past age and count"
    assert "p05" not in kept, "an unpinned snapshot older than 7 days goes"
    assert "p01" not in kept and "p02" in kept, "only the newest 20 unpinned stay"
    assert removed == 2 and len(kept) == 21
    shadow = Path(store.for_session("s")[0].shadow)
    refs = subprocess.run(["git", f"--git-dir={shadow}", "for-each-ref", "--format=%(refname)"], check=True,
                          capture_output=True, text=True).stdout.split()
    assert len(refs) == 21 and not any(r.endswith("/p01") for r in refs)
    store.delete([c.id for c in store.for_session("s")[:3]])
    assert cleanup.at_start(store, state) == 3, "engine start drops the refs no row names"
    assert cleanup.purge_session(store, "s") == 18 and store.for_session("s") == []


def test_a_turn_lists_its_own_changes_and_diffs(repo: Path, tmp_path: Path) -> None:
    from src.core.checkpoints import read

    state = tmp_path / "state"
    store = CheckpointStore(state / "bookmarks.db")
    first = cap.capture(repo, session_uuid="s", conversation="c", prompt_uuid="p1", store=store, state_root=state)
    (repo / "pkg" / "deep" / "b.txt").write_text("b changed by a bash sed\n")
    (repo / "fresh.txt").write_text("new\n")
    (repo / ".env.prod").write_text("SECRET=1\n")
    second = cap.capture(repo, session_uuid="s", conversation="c", prompt_uuid="p2", store=store, state_root=state)
    got = {f.path: f.kind for f in read.changes(store, second.checkpoint)}
    assert got == {"pkg/deep/b.txt": "modified", "fresh.txt": "added"}, "only this turn's edits, never the secret"
    first_changes = {f.path for f in read.changes(store, first.checkpoint)}
    assert first_changes == {"a.txt"}, "the first turn compares against the HEAD it was taken on"
    entry = next(f for f in read.changes(store, second.checkpoint) if f.path == "pkg/deep/b.txt")
    diff = read.file_diff(store, second.checkpoint, entry)
    assert diff.state == "ok" and "+b changed by a bash sed" in diff.text
    usage = read.usage(store)
    assert usage[0]["checkpoints"] == 2 and usage[0]["bytes"] > 0
