
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Dict, List

import pytest

from src.core.pack.jobs import bundle_io, gitio, guards, side_repo, snapshot
from src.core.pack.jobs.types import JobError

UID = "uid12345678"
JOB = "job_0123456789ab"
ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def g(cwd: Path, *args: str, env: Dict[str, str] | None = None) -> str:
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(env or {})
    return subprocess.run(["git", *ID, *args], cwd=cwd, env=e, check=True, capture_output=True, text=True).stdout.strip()


def fingerprint(repo: Path) -> Dict[str, object]:
    files = {}
    for root, _d, names in os.walk(repo / ".git"):
        for n in names:
            p = Path(root) / n
            st = p.stat()
            rel = str(p.relative_to(repo))
            files[rel] = (st.st_size, 0 if rel.startswith(".git/objects/") else st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return {"files": files, "refs": g(repo, "for-each-ref")}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "my repo"
    r.mkdir()
    g(r, "init", "-q", "-b", "main")
    (r / "sub").mkdir()
    (r / "a.txt").write_text("a\n")
    (r / "sub" / "s.txt").write_text("s\n")
    (r / ".gitignore").write_text("*.log\n")
    g(r, "add", "-A")
    g(r, "commit", "-qm", "init")
    return r


@pytest.fixture()
def jobs_root(tmp_path: Path) -> Path:
    return tmp_path / "jobs root"


def tree_files(snap, path: str = "") -> List[str]:
    return g(Path(snap.side_git_dir), "ls-tree", "-r", "--name-only", snap.commit).splitlines()


def test_staged_unstaged_untracked_land_ignored_do_not_and_project_untouched(repo, jobs_root):
    (repo / "staged.txt").write_text("st\n")
    g(repo, "add", "staged.txt")
    (repo / "a.txt").write_text("changed\n")
    (repo / "new file.txt").write_text("n\n")
    (repo / "x.log").write_text("ignored\n")
    (repo / "forced.log").write_text("carry me\n")
    before = fingerprint(repo)
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root, carry=["forced.log"])
    assert fingerprint(repo) == before
    names = tree_files(snap)
    assert {"staged.txt", "a.txt", "new file.txt", "forced.log", "sub/s.txt"} <= set(names)
    assert "x.log" not in names
    assert g(Path(snap.side_git_dir), "show", f"{snap.commit}:a.txt") == "changed"
    assert snap.head == g(repo, "rev-parse", "HEAD") and snap.scope == ""
    assert g(Path(snap.side_git_dir), "rev-parse", f"refs/heads/job-{JOB}") == snap.commit
    assert snap.new_bytes > 0


def test_negative_control_without_object_directory_the_fingerprint_changes(repo, jobs_root, tmp_path):
    (repo / "new.txt").write_text("brand new content\n")
    before = fingerprint(repo)
    idx = tmp_path / "idx"
    idx.write_bytes((repo / ".git" / "index").read_bytes())
    g(repo, "add", "new.txt", env={"GIT_INDEX_FILE": str(idx)})
    assert fingerprint(repo) != before


def test_dependency_folder_nested_repo_and_big_file_left_out_with_notes(repo, jobs_root):
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "f.js").write_text("1")
    (repo / "web" / "node_modules" / "y").mkdir(parents=True)
    (repo / "web" / "node_modules" / "y" / "f.js").write_text("1")
    (repo / "nested").mkdir()
    g(repo / "nested", "init", "-q")
    (repo / "nested" / "n.txt").write_text("n")
    with open(repo / "big.bin", "wb") as fh:
        fh.truncate(51 * 1024 * 1024)
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    names = tree_files(snap)
    assert not any(n.startswith(("node_modules", "web/node_modules", "nested/", "big.bin")) for n in names)
    text = "\n".join(snap.notes)
    assert "node_modules" in text and "web/node_modules" in text and "nested" in text and "big.bin" in text
    assert text.count("left out node_modules:") == 1


def test_linked_worktree_and_subfolder_scope(repo, jobs_root, tmp_path):
    wt = tmp_path / "linked tree"
    g(repo, "worktree", "add", "-q", "--detach", str(wt))
    (wt / "sub" / "s.txt").write_text("edited in sub\n")
    (wt / "a.txt").write_text("edited outside\n")
    (wt / "sub" / "fresh.txt").write_text("f\n")
    (wt / "top.txt").write_text("t\n")
    before = fingerprint(repo)
    snap = snapshot.take(str(wt / "sub"), UID, JOB, jobs_root=jobs_root)
    assert fingerprint(repo) == before
    assert snap.scope == "sub" and os.path.realpath(snap.toplevel) == os.path.realpath(wt)
    show = lambda p: g(Path(snap.side_git_dir), "show", f"{snap.commit}:{p}")
    assert show("sub/s.txt") == "edited in sub" and "sub/fresh.txt" in tree_files(snap)
    assert show("a.txt") == "a"
    assert "top.txt" not in tree_files(snap)


def test_bundle_roundtrip_garbage_tip_filtered_and_nothing_to_send(repo, jobs_root, tmp_path):
    clone = tmp_path / "clone dir"
    g(tmp_path, "clone", "-q", str(repo), str(clone))
    (repo / "a.txt").write_text("work\n")
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    out = str(tmp_path / "s.bundle")
    ref = f"refs/heads/job-{JOB}"
    size = bundle_io.make_bundle(snap.side_git_dir, ref, [snap.head, "0" * 40, "garbage"], out)
    assert size > 0 and bundle_io.verify(str(clone / ".git"), out)
    got = bundle_io.fetch_bundle(str(clone / ".git"), out, ref, "refs/carnivore/jobs/x/snapshot")
    assert got == snap.commit
    with pytest.raises(JobError) as e:
        bundle_io.make_bundle(snap.side_git_dir, ref, [snap.commit], str(tmp_path / "e.bundle"))
    assert e.value.code == "nothing_to_send"
    other = tmp_path / "other"
    g(tmp_path, "init", "-q", str(other))
    with pytest.raises(JobError) as e2:
        bundle_io.fetch_bundle(str(other / ".git"), out, ref, "refs/x/y")
    assert e2.value.code == "bundle_unverified"


def test_too_many_files_refused_before_any_add(repo, jobs_root, monkeypatch):
    monkeypatch.setattr(guards, "MAX_UNTRACKED_FILES", 2)
    for i in range(3):
        (repo / f"u{i}.txt").write_text("x")
    with pytest.raises(JobError) as e:
        snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    assert e.value.code == "snapshot_too_large"
    assert not (Path(jobs_root) / "repos" / f"{UID}.git" / "refs" / "heads" / f"job-{JOB}").exists()


def test_not_a_repo(tmp_path, jobs_root):
    d = tmp_path / "plain dir"
    d.mkdir()
    with pytest.raises(JobError) as e:
        snapshot.take(str(d), UID, JOB, jobs_root=jobs_root)
    assert e.value.code == "not_a_repo"


def test_dep_dirs_and_inheritance_from_project_root(repo, jobs_root, tmp_path):
    (repo / "package-lock.json").write_text("{}")
    (repo / "node_modules").mkdir()
    (repo / "requirements.txt").write_text("x==1\n")
    (repo / ".venv" / "bin").mkdir(parents=True)
    py = repo / ".venv" / "bin" / "python"
    py.write_text("#!/bin/sh\necho 3.12\n")
    py.chmod(0o755)
    g(repo, "add", "package-lock.json", "requirements.txt")
    g(repo, "commit", "-qm", "locks")
    wt = tmp_path / "wt dir"
    g(repo, "worktree", "add", "-q", "--detach", str(wt))
    own = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    by = {d.path: d for d in own.dep_dirs}
    assert by["node_modules"].kind == "npm" and by["node_modules"].locks["package-lock.json"] == hashlib.sha256(b"{}").hexdigest()
    assert by[".venv"].kind == "venv" and by[".venv"].python is not None
    inh = snapshot.take(str(wt), UID, JOB, jobs_root=jobs_root, project_root=str(repo))
    assert {d.path for d in inh.dep_dirs} == {"node_modules", ".venv"}
    assert {d.path for d in snapshot.take(str(wt), UID, JOB, jobs_root=jobs_root).dep_dirs} == set()


def test_outside_symlink_listed(repo, jobs_root, tmp_path):
    (tmp_path / "elsewhere").write_text("e")
    os.symlink(tmp_path / "elsewhere", repo / "link")
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    assert snap.outside_links == ["link"]


def test_custom_clean_filter_still_runs_but_project_git_dir_unchanged(repo, jobs_root, tmp_path):
    marker = tmp_path / "marker"
    g(repo, "config", "filter.mark.clean", f"sh -c 'echo ran >> \"{marker}\"; cat'")
    (repo / ".gitattributes").write_text("*.dat filter=mark\n")
    (repo / "f.dat").write_text("data\n")
    before = fingerprint(repo)
    snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    assert marker.exists()
    assert fingerprint(repo) == before


def test_prune_and_drop_ref(repo, jobs_root):
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    side = snap.side_git_dir
    assert side_repo.prune(side, older_than_s=10_000, keep=set(), now=snap.taken_at) == 0
    assert side_repo.prune(side, older_than_s=1, keep={f"refs/heads/job-{JOB}"}, now=snap.taken_at + 99999) == 0
    assert side_repo.prune(side, older_than_s=1, keep=set(), now=snap.taken_at + 99999) == 1
    assert gitio.run(["rev-parse", "--verify", "-q", f"refs/heads/job-{JOB}"], git_dir=side, check=False).returncode != 0
    side_repo.drop_ref(side, "refs/heads/nothing")


def test_commit_ref_snapshots_that_commits_tree_and_none_of_the_dirty_working_tree(repo, jobs_root):
    (repo / "a.txt").write_text("v2\n")
    g(repo, "commit", "-qam", "second")
    fixed = g(repo, "rev-parse", "HEAD")
    g(repo, "reset", "-q", "--hard", "HEAD~1")
    (repo / "a.txt").write_text("dirty\n")
    (repo / "untracked.txt").write_text("u\n")
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root, commit_ref=fixed)
    assert snap.tree == g(repo, "rev-parse", f"{fixed}^{{tree}}")
    assert "untracked.txt" not in tree_files(snap)
    assert g(Path(snap.side_git_dir), "show", f"{snap.commit}:a.txt") == "v2"
    with pytest.raises(JobError) as bad:
        snapshot.take(str(repo), UID, "job_0123456789ac", jobs_root=jobs_root, commit_ref="0" * 40)
    assert bad.value.code == "bad_request"
