
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.core.pack.jobs import collect, gitio, land

JOB = "job1"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class World:

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.caller = tmp / "my repo"
        self.caller.mkdir()
        _git(self.caller, "init", "-q")
        (self.caller / ".gitignore").write_text("node_modules/\n*.report\n")
        for name, body in (("keep.txt", "keep\n"), ("mod.txt", "old\n"), ("gone.txt", "bye\n")):
            (self.caller / name).write_text(body)
        _git(self.caller, "add", "-A")
        _git(self.caller, "commit", "-qm", "c1")
        self.snap = _git(self.caller, "rev-parse", "HEAD")
        self.snapshot_at = time.time()
        self.side = str(tmp / "side dir.git")
        subprocess.run(["git", "init", "--bare", "-q", self.side], check=True)
        alt = Path(self.side) / "objects" / "info" / "alternates"
        alt.parent.mkdir(parents=True, exist_ok=True)
        alt.write_text(str(self.caller / ".git" / "objects") + "\n")
        gitio.run(["update-ref", "refs/heads/job-x", self.snap], git_dir=self.side)
        self.replica = tmp / "replica dir"
        subprocess.run(["git", "clone", "-q", str(self.caller), str(self.replica)], check=True)
        _git(self.replica, "checkout", "-q", "--detach", self.snap)

    def run_job(self, **kw) -> "collect.Collected":
        got = collect.collect(str(self.replica), self.snap, kw.get("outputs", ()), JOB, self.tmp / "out dir", exclude=kw.get("exclude", ()))
        if got.bundle_path:
            gitio.run(["fetch", "--no-tags", got.bundle_path, f"+refs/carnivore/jobs/{JOB}/result:refs/heads/result-{JOB}"], git_dir=self.side)
        return got

    def land(self, got, **kw):
        return land.land(str(self.caller), self.side, self.snap, got.result_commit, JOB, snapshot_at=self.snapshot_at, **kw)


@pytest.fixture()
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def test_apply_modified_new_deleted_and_index_untouched(w: World) -> None:
    (w.replica / "mod.txt").write_text("new\n")
    (w.replica / "sub dir").mkdir()
    (w.replica / "sub dir" / "n.txt").write_text("fresh\n")
    (w.replica / "gone.txt").unlink()
    got = w.run_job()
    assert got.changed == 3 and Path(got.bundle_path).exists()
    index = w.caller / ".git" / "index"
    before = index.read_bytes()
    res = w.land(got)
    assert res.clashes == [] and sorted(res.applied) == ["mod.txt", "sub dir/n.txt"] and res.deleted == ["gone.txt"]
    assert (w.caller / "mod.txt").read_text() == "new\n" and (w.caller / "sub dir" / "n.txt").read_text() == "fresh\n"
    assert not (w.caller / "gone.txt").exists()
    assert index.read_bytes() == before
    assert not [p for p in w.caller.rglob("*carn-land*")]
    again = w.land(got)
    assert again.clashes == [] and again.ref is None


def test_output_glob_brings_back_ignored_file(w: World) -> None:
    (w.replica / "a.report").write_text("r\n")
    got = w.run_job(outputs=["*.report"])
    res = w.land(got, outputs=["*.report"])
    assert res.applied == ["a.report"] and (w.caller / "a.report").read_text() == "r\n"


def test_dependency_folder_not_collected(w: World) -> None:
    (w.replica / "web").mkdir()
    (w.replica / "web" / "node_modules" / "p").mkdir(parents=True)
    (w.replica / "web" / "node_modules" / "p" / "i.js").write_text("x\n")
    (w.replica / "venv").mkdir()
    (w.replica / "venv" / "f").write_text("x\n")
    assert w.run_job().changed == 0


def test_gitignored_dependency_folder_does_not_fail_collect(w: World) -> None:
    with (w.replica / ".gitignore").open("a") as f:
        f.write("venv/\n")
    (w.replica / "venv").mkdir()
    (w.replica / "venv" / "f").write_text("x\n")
    (w.replica / "mod.txt").write_text("new\n")
    got = w.run_job(exclude=["venv", "web/node_modules"])
    names = _git(w.replica, "diff-tree", "-r", "--name-only", w.snap, got.result_commit).splitlines()
    assert got.changed == len(names) and "mod.txt" in names and not any(n.startswith("venv") for n in names)


def test_no_change(w: World) -> None:
    got = w.run_job()
    assert (got.changed, got.bundle_path, got.result_commit) == (0, "", w.snap)


def test_clash_changes_nothing_and_parks_ref(w: World) -> None:
    (w.replica / "mod.txt").write_text("job\n")
    (w.replica / "other.txt").write_text("o\n")
    got = w.run_job()
    (w.caller / "mod.txt").write_text("caller edit\n")
    res = w.land(got)
    assert res.clashes == ["mod.txt"] and res.ref == f"refs/carnivore/jobs/{JOB}" and not res.applied
    assert (w.caller / "mod.txt").read_text() == "caller edit\n" and not (w.caller / "other.txt").exists()
    assert _git(w.caller, "rev-parse", res.ref) == got.result_commit
    collect.drop_refs(str(w.caller), JOB)
    assert _git(w.caller, "for-each-ref", f"refs/carnivore/jobs/{JOB}/") == ""


def test_stale_ignored_output_overwritten_fresh_clashes(w: World) -> None:
    (w.replica / "a.report").write_text("job\n")
    got = w.run_job(outputs=["*.report"])
    stale = w.caller / "a.report"
    stale.write_text("old run\n")
    old = w.snapshot_at - 1000
    os.utime(stale, (old, old))
    res = w.land(got, outputs=["*.report"])
    assert res.clashes == [] and stale.read_text() == "job\n"
    stale.write_text("fresh edit\n")
    res = w.land(got, outputs=["*.report"])
    assert res.clashes == ["a.report"] and stale.read_text() == "fresh edit\n"


def test_unsafe_path_refused(w: World) -> None:
    from src.core.pack.jobs.types import JobError
    with pytest.raises(JobError):
        land._safe(".git/hooks/x", str(w.caller))


def test_case_only_rename_keeps_the_new_file(w: World) -> None:
    (w.caller / "a.txt").write_text("same\n")
    _git(w.caller, "add", "a.txt")
    _git(w.caller, "commit", "-qm", "c2")
    w.snap = _git(w.caller, "rev-parse", "HEAD")
    _git(w.replica, "fetch", "-q", str(w.caller), "HEAD")
    _git(w.replica, "checkout", "-q", "--detach", w.snap)
    gitio.run(["update-ref", "refs/heads/job-x", w.snap], git_dir=w.side)
    _git(w.replica, "mv", "a.txt", "A.txt")
    got = w.run_job()
    res = w.land(got)
    assert res.clashes == [] and sorted(os.listdir(w.caller)).count("A.txt") == 1 and "a.txt" not in os.listdir(w.caller)
    assert (w.caller / "A.txt").read_text() == "same\n"


def test_a_path_that_became_a_file_is_a_clash_not_a_crash(w: World) -> None:
    (w.caller / "d").mkdir()
    (w.caller / "d" / "x").write_text("x\n")
    _git(w.caller, "add", "d/x")
    _git(w.caller, "commit", "-qm", "c2")
    w.snap = _git(w.caller, "rev-parse", "HEAD")
    _git(w.replica, "fetch", "-q", str(w.caller), "HEAD")
    _git(w.replica, "checkout", "-q", "--detach", w.snap)
    gitio.run(["update-ref", "refs/heads/job-x", w.snap], git_dir=w.side)
    (w.replica / "d" / "x").write_text("job\n")
    got = w.run_job()
    shutil.rmtree(w.caller / "d")
    (w.caller / "d").write_text("now a file\n")
    assert w.land(got).clashes == ["d/x"]


def test_interrupted_land_is_repaired_by_the_next_one(w: World) -> None:
    (w.replica / "mod.txt").write_text("new\n")
    got = w.run_job()
    (w.caller / "mod.txt").rename(w.caller / ".mod.txt.carn-land-bak")
    (w.caller / ".mod.txt.carn-land-tmp").write_text("half\n")
    res = w.land(got)
    assert res.clashes == [] and (w.caller / "mod.txt").read_text() == "new\n"
    assert not (w.caller / ".mod.txt.carn-land-bak").exists() and not (w.caller / ".mod.txt.carn-land-tmp").exists()


def test_a_result_under_a_dependency_folder_is_refused_in_any_case(w: World) -> None:
    from src.core.pack.jobs.types import JobError

    (w.replica / ".VENV" / "lib").mkdir(parents=True)
    (w.replica / ".VENV" / "lib" / "evil.pth").write_text("import os\n")
    got = w.run_job()
    with pytest.raises(JobError) as exc:
        w.land(got)
    assert exc.value.code == "unsafe_path" and not (w.caller / ".VENV").exists()


def test_an_oversize_result_is_parked_and_never_written(w: World, monkeypatch) -> None:
    from src.core.pack.jobs import guards
    from src.core.pack.jobs.types import JobError

    (w.replica / "big.bin").write_bytes(b"\0" * 4096)
    (w.replica / "mod.txt").write_bytes(b"\0" * 4096)
    monkeypatch.setattr(guards, "MAX_UNTRACKED_BYTES", 1000)
    with pytest.raises(JobError) as exc:
        w.run_job()
    assert exc.value.code == "result_too_large"
    monkeypatch.undo()
    got = w.run_job()
    monkeypatch.setattr(guards, "MAX_UNTRACKED_BYTES", 1000)
    res = w.land(got)
    assert res.ref and res.applied == [] and "big.bin" in res.clashes[0]
    assert not (w.caller / "big.bin").exists() and (w.caller / "mod.txt").read_text() == "old\n"
    monkeypatch.undo()
    monkeypatch.setattr(guards, "MAX_SNAPSHOT_BYTES", 5000)
    assert w.land(got).clashes
