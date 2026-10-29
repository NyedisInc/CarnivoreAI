
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

import pytest

from src.core.session_git import reader
from src.core.session_git.reader import MAX_FILES, parse_status, read_session_git

_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def g(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "protocol.file.allow=always", "-C", str(cwd), *args], check=True, env=_ENV,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_repo(path: Path, *, commit: bool = True) -> Path:
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    if commit:
        (path / "a.txt").write_text("a\n")
        g(path, "add", "a.txt")
        g(path, "commit", "-q", "-m", "one")
    return path


def nul(*recs: str) -> str:
    return "\0".join(recs) + "\0"


def test_parse_headers_and_entries() -> None:
    oid = "a" * 40
    st = parse_status(nul(
        f"# branch.oid {oid}", "# branch.head main", "# branch.upstream origin/main", "# branch.ab +2 -3",
        "1 M. N... 100644 100644 100644 h h staged.txt",
        "1 .M N... 100644 100644 100644 h h work file.txt",
        "1 MM N... 100644 100644 100644 h h both.txt",
        "2 R. N... 100644 100644 100644 h h R100 new.txt", "old.txt",
        "u UU N... 100644 100644 100644 100644 h h h merge.txt",
        "1 .M S.M. 160000 160000 160000 h h sub",
        "? loose.txt"))
    assert (st.state, st.branch, st.head_short, st.upstream, st.ahead, st.behind) == ("ok", "main", "aaaaaaa", "origin/main", 2, 3)
    assert st.counts.model_dump() == {"staged": 3, "unstaged": 3, "untracked": 1, "conflicted": 1}
    by = {f.path: f for f in st.files}
    assert by["work file.txt"].kind == "modified" and by["both.txt"].index == "M" and by["both.txt"].worktree == "M"
    assert (by["new.txt"].kind, by["new.txt"].orig_path) == ("renamed", "old.txt")
    assert by["merge.txt"].kind == "conflicted" and by["loose.txt"].kind == "untracked"
    assert by["sub"].submodule and not by["staged.txt"].submodule
    assert st.truncated == 0


def test_parse_detached_unborn_no_upstream() -> None:
    d = parse_status(nul("# branch.oid " + "b" * 40, "# branch.head (detached)"))
    assert (d.detached, d.branch, d.head_short, d.ahead) == (True, None, "bbbbbbb", None)
    u = parse_status(nul("# branch.oid (initial)", "# branch.head main"))
    assert (u.unborn, u.branch, u.head_short) == (True, "main", None)


def test_parse_caps_files_but_counts_all() -> None:
    recs: List[str] = ["# branch.oid " + "c" * 40, "# branch.head main"] + [f"? f{i}" for i in range(MAX_FILES + 7)]
    st = parse_status(nul(*recs))
    assert len(st.files) == MAX_FILES and st.truncated == 7 and st.counts.untracked == MAX_FILES + 7


def test_clean_staged_unstaged_untracked_rename(tmp_path: Path) -> None:
    r = make_repo(tmp_path / "proj")
    st = read_session_git(r)
    assert (st.state, st.branch, st.repo_name, st.files, st.unborn) == ("ok", "main", "proj", [], False)
    assert st.repo_root == str(r.resolve()) or st.repo_root == str(r)
    (r / "b.txt").write_text("b\n")
    g(r, "add", "b.txt")
    (r / "a.txt").write_text("changed\n")
    (r / "u.txt").write_text("u\n")
    st = read_session_git(r)
    assert st.counts.model_dump() == {"staged": 1, "unstaged": 1, "untracked": 1, "conflicted": 0}
    assert {f.path: f.kind for f in st.files} == {"a.txt": "modified", "b.txt": "added", "u.txt": "untracked"}
    g(r, "mv", "a.txt", "renamed.txt")
    ren = [f for f in read_session_git(r).files if f.kind == "renamed"]
    assert [(f.path, f.orig_path) for f in ren] == [("renamed.txt", "a.txt")]


def test_subdirectory_reads_whole_repo(tmp_path: Path) -> None:
    r = make_repo(tmp_path / "proj")
    (r / "sub").mkdir()
    (r / "top.txt").write_text("x")
    st = read_session_git(r / "sub")
    assert st.state == "ok" and [f.path for f in st.files] == ["top.txt"]


def test_conflict(tmp_path: Path) -> None:
    r = make_repo(tmp_path / "proj")
    g(r, "checkout", "-q", "-b", "other")
    (r / "a.txt").write_text("other\n")
    g(r, "commit", "-q", "-am", "o")
    g(r, "checkout", "-q", "main")
    (r / "a.txt").write_text("main\n")
    g(r, "commit", "-q", "-am", "m")
    subprocess.run(["git", "-C", str(r), "merge", "other"], env=_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st = read_session_git(r)
    assert st.counts.conflicted == 1 and st.files[0].kind == "conflicted"


def test_submodule_is_one_flagged_row(tmp_path: Path) -> None:
    inner = make_repo(tmp_path / "inner")
    r = make_repo(tmp_path / "outer")
    g(r, "submodule", "add", "-q", str(inner), "mod")
    g(r, "commit", "-q", "-m", "sub")
    (r / "mod" / "dirty.txt").write_text("d")
    st = read_session_git(r)
    rows = [f for f in st.files if f.path == "mod"]
    assert len(rows) == 1 and rows[0].submodule and not [f for f in st.files if f.path.startswith("mod/")]


def test_detached_unborn_and_linked_worktree(tmp_path: Path) -> None:
    r = make_repo(tmp_path / "proj")
    wt = tmp_path / "wt"
    g(r, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / "only-here.txt").write_text("x")
    assert [f.path for f in read_session_git(wt).files] == ["only-here.txt"]
    assert read_session_git(wt).branch == "feat" and read_session_git(r).files == []
    g(r, "checkout", "-q", "--detach")
    st = read_session_git(r)
    assert st.detached and st.branch is None and st.head_short
    fresh = make_repo(tmp_path / "fresh", commit=False)
    st = read_session_git(fresh)
    assert st.state == "ok" and st.unborn and st.branch == "main" and st.head_short is None


def test_upstream_and_remote(tmp_path: Path) -> None:
    r = make_repo(tmp_path / "proj")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=_ENV)
    g(r, "remote", "add", "origin", str(bare))
    g(r, "push", "-q", "-u", "origin", "main")
    (r / "a.txt").write_text("2\n")
    g(r, "commit", "-q", "-am", "two")
    st = read_session_git(r)
    assert (st.upstream, st.remote, st.ahead, st.behind) == ("origin/main", "origin", 1, 0)


def test_not_a_repo_and_missing_dir(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert read_session_git(plain).state == "not_a_repo"
    assert read_session_git(tmp_path / "nope").state == "unknown"


def test_timeout_and_failure_are_unknown_never_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r = make_repo(tmp_path / "proj")

    def boom(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(reader, "run_git", boom)
    assert read_session_git(r).state == "unknown"

    def fail(repo: Path, *args: str, **k: object) -> "subprocess.CompletedProcess[str]":
        return subprocess.CompletedProcess(args, 128 if args[0] == "rev-parse" else 1, "", "")

    monkeypatch.setattr(reader, "run_git", fail)
    st = read_session_git(r)
    assert st.state == "unknown" and st.files == []
