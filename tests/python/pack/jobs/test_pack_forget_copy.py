
from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import subprocess
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_copies_routes as copies_routes  # noqa: E402
from src.api import federation_pack_replica_routes as replica_routes  # noqa: E402
from src.api import peer_auth, project_replica_routes  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants  # noqa: E402
from src.core.pack.identity import replicas  # noqa: E402
from src.core.pack.jobs import copies, trash  # noqa: E402
from src.core.pack.jobs.store import JobStore  # noqa: E402
from src.core.pack.jobs.types import HostJob, HostState  # noqa: E402
from src.core.project_move.plan import PaneListing  # noqa: E402

HOME_ID = "iid-home-a"
UID = "c0f1" * 8
NOW = datetime(2026, 11, 16, 9, 5, 1)
NO_PANES = PaneListing(ok=True, panes=())


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.invalid"}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


class World:

    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp, self.home, self.state, self.jobs = tmp, tmp / "home", tmp / "state", tmp / "jobs"
        self.work = tmp / "work"
        for folder in (self.home / ".Trash", self.state, self.jobs, self.work):
            folder.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("CARNIVORE_JOBS_ROOT", str(self.jobs))
        monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: self.state, raising=True)
        assert ensure_db_migrated(self.state).status == "ok"
        self.store = JobStore(self.state)
        self.panes = NO_PANES
        self.fake_bin = tmp / "fake-trash"
        self.fake_dir = tmp / "fake-trash-dir"
        self.fake_dir.mkdir()
        self.fake_bin.write_text(f'#!/bin/sh\nmv "$1" "{self.fake_dir}/"\n')
        self.fake_bin.chmod(0o755)

    def conn(self):
        return connect(db_path_for(self.state), create=False)

    def home_repo(self) -> Path:
        repo = self.tmp / f"home-repo-{uuid.uuid4().hex[:6]}"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("one\n")
        git(repo, "add", "a.txt")
        git(repo, "commit", "-q", "-m", "one")
        return repo

    def make_copy(self, name: str = "proj", *, uid: str = UID, made: bool = True, auto: bool = True, commits: bool = True) -> Dict[str, Any]:
        root = self.work / name
        if not made:
            root.mkdir()
        with closing(self.conn()) as conn:
            answer = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid=uid, name=name, root=str(root))
        assert answer["folder_made"] is made
        home_repo = self.home_repo()
        if commits:
            subprocess.run(["git", "clone", "-q", str(home_repo), str(root)], check=True, capture_output=True) if not list(root.iterdir()) else None
            if not (root / ".git").exists():
                git(root, "init", "-q", "-b", "main")
                git(root, "fetch", "-q", str(home_repo), "main")
                git(root, "checkout", "-q", "-B", "main", "FETCH_HEAD")
        else:
            git(root, "init", "-q", "-b", "main")
        copies.record_made(self.store, root=answer["root"], project_uid=uid, home_install_id=HOME_ID, auto=auto, folder_made=answer["folder_made"])
        return {"root": Path(answer["root"]), "uid": uid, "tips": [git(home_repo, "rev-parse", "HEAD")] if commits else [], "home_repo": home_repo}

    def kw(self) -> Dict[str, Any]:
        return {"store": self.store, "open_db": self.conn, "read_panes": lambda: self.panes, "state_dir": self.state, "jobs_root": self.jobs}

    def check(self, copy: Dict[str, Any], *, caller: str = HOME_ID, tips: Any = None) -> copies.CopyVerdict:
        return copies.check(copy["uid"], caller, copy["tips"] if tips is None else tips, **self.kw())

    def trasher(self, tool: str = ""):
        return lambda p: trash.move(p, now=NOW, home=self.home, tool=tool or str(self.fake_bin), state_dir=self.state, platform="darwin")

    def forget(self, copy: Dict[str, Any], **extra: Any) -> copies.CopyVerdict:
        return copies.forget(copy["uid"], HOME_ID, copy["tips"], trasher=extra.pop("trasher", self.trasher()), **self.kw(), **extra)

    def snapshot(self) -> Dict[str, Any]:
        names = sorted(str(Path(d, f).relative_to(self.tmp)) for base in (self.work, self.jobs) for d, ds, fs in os.walk(base) for f in ds + fs)
        with closing(self.conn()) as conn:
            rows = [list(map(tuple, conn.execute(f"SELECT * FROM {t}").fetchall())) for t in ("projects", "project_replicas")]
        with closing(self.store._connect()) as c2:
            rows += [list(map(tuple, c2.execute(f"SELECT * FROM {t}").fetchall())) for t in ("made_copies", "slots", "host_jobs", "jobs")]
        return {"names": names, "rows": rows}


@pytest.fixture
def world(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def kept(verdict: copies.CopyVerdict, code: str) -> None:
    assert (verdict.verdict, verdict.code) == ("kept", code)




def test_a_clean_made_copy_is_deletable_and_forget_trashes_it_and_archives_the_row(world) -> None:
    copy = world.make_copy()
    assert world.check(copy).verdict == "deletable"
    (copy["root"] / "node_modules").mkdir()
    (copy["root"] / ".gitignore").write_text("node_modules/\n.env\n")
    git(copy["root"], "add", ".gitignore")
    git(copy["root"], "commit", "-q", "-m", "ignore")
    (copy["root"] / ".env").write_text("x=1\n")
    copy["tips"] = [*copy["tips"], git(copy["root"], "rev-parse", "HEAD")]
    (copy["root"] / "node_modules" / "a").write_text("x")
    verdict = world.check(copy)
    assert verdict.verdict == "deletable" and verdict.ignored == (".env",) and verdict.ignored_more == 0
    done = world.forget(copy)
    assert (done.verdict, done.code) == ("deleted", "") and done.ignored == (".env",)
    assert not copy["root"].exists() and (world.fake_dir / "proj").is_dir()
    with closing(world.conn()) as conn:
        row = dict(conn.execute("SELECT * FROM projects WHERE root = ?", (str(copy["root"]),)).fetchone())
    assert row["archived_at"] and row["pack_state"] == "home" and row["uid"] != UID
    assert world.store.made_copy_get(os.path.realpath(copy["root"])) is None
    kept(world.check(copy), "not_a_copy")


def test_not_a_copy_guards(world, tmp_path) -> None:
    copy = world.make_copy()
    kept(world.check(copy, caller="iid-someone-else"), "not_a_copy")
    world.store.made_copy_put(os.path.realpath(copy["root"]), home_install_id="iid-other")
    kept(world.check(copy), "not_a_copy")
    world.store.made_copy_put(os.path.realpath(copy["root"]), home_install_id=HOME_ID)
    kept(copies.check("f" * 32, HOME_ID, [], **world.kw()), "not_a_copy")
    with closing(world.conn()) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'plain', 'user', 't', 't')",
                     (str(world.work / "plain"), str(world.work / "plain")))
        conn.commit()
        plain_uid = conn.execute("SELECT uid FROM projects WHERE display_name = 'plain'").fetchone()[0]
    kept(copies.check(plain_uid, HOME_ID, [], **world.kw()), "not_a_copy")
    kept(copies.check(UID, "../evil", [], **world.kw()), "not_a_copy")
    world.store.made_copy_put(os.path.realpath(copy["root"]), project_uid="b" * 32)
    kept(world.check(copy), "not_a_copy")


def test_root_guards_a_git_file_a_link_and_a_shallow_or_home_folder(world, tmp_path) -> None:
    copy = world.make_copy()
    real_git = copy["root"] / ".git"
    moved = copy["root"] / ".git-real"
    real_git.rename(moved)
    real_git.write_text("gitdir: " + str(moved) + "\n")
    kept(world.check(copy), "not_a_copy")
    real_git.unlink()
    moved.rename(real_git)
    assert world.check(copy).verdict == "deletable"
    link = world.work / "link"
    link.symlink_to(copy["root"])
    with closing(world.conn()) as conn:
        conn.execute("UPDATE projects SET root = ? WHERE uid = ?", (str(link), UID))
        conn.commit()
    kept(world.check(copy), "not_a_copy")
    with closing(world.conn()) as conn:
        conn.execute("UPDATE projects SET root = ? WHERE uid = ?", (str(world.home), UID))
        conn.commit()
    world.store.made_copy_put(os.path.realpath(world.home), project_uid=UID, home_install_id=HOME_ID, auto=1, folder_made=1)
    git(world.home, "init", "-q")
    kept(world.check(copy), "not_a_copy")


def test_no_record_when_there_is_none_or_the_mark_did_not_make_the_folder(world) -> None:
    no_row = world.make_copy("norecord")
    world.store.made_copy_delete(os.path.realpath(no_row["root"]))
    kept(world.check(no_row), "no_record")
    by_hand = world.make_copy("byhand", uid="d" * 32, auto=False)
    kept(world.check(by_hand), "no_record")
    existed = world.make_copy("existed", uid="e" * 32, made=False)
    kept(world.check(existed), "no_record")


def test_too_many_refs_and_a_bad_tip(world) -> None:
    copy = world.make_copy()
    kept(world.check(copy, tips=["a" * 40] * (copies.MAX_TIPS + 1)), "too_many_refs")
    kept(world.check(copy, tips=["--upload-pack=x"]), "git_failed")


def test_job_running_for_each_way_a_job_holds_the_copy(world) -> None:
    copy = world.make_copy()
    world.store.host_put(HostJob(job_id="job_000000000001", project_uid=UID, state=HostState.RUNNING))
    kept(world.check(copy), "job_running")
    world.store.host_set("job_000000000001", state=HostState.EXITED)
    assert world.check(copy).verdict == "deletable"
    world.store.host_set("job_000000000001", keep_until=4102444800.0)
    kept(world.check(copy), "job_running")
    world.store.host_delete("job_000000000001")
    claim = world.store.slot_claim(UID, str(copy["root"]), lambda n: str(world.jobs / "folders" / f"proj-c0f1c0f1" / f"slot{n}"), "job_000000000002")
    assert claim is not None
    kept(world.check(copy), "job_running")


def test_session_live_by_a_pane_a_row_and_an_unreadable_listing(world) -> None:
    copy = world.make_copy()
    world.panes = PaneListing(ok=True, panes=(("cloude_x", None, str(copy["root"] / "sub")),))
    kept(world.check(copy), "session_live")
    world.panes = PaneListing(ok=False, reason="tmux did not answer")
    kept(world.check(copy), "session_live")
    world.panes = NO_PANES
    assert world.check(copy).verdict == "deletable"
    with closing(world.conn()) as conn:
        cols = "(session_uuid, working_dir, lifecycle, tmux_name, host_key, origin, created_at, updated_at)"
        try:
            conn.execute(f"INSERT INTO sessions {cols} VALUES ('s1', ?, 'running', 'cloude_y', 'local', 'created', 't', 't')", (str(copy["root"]),))
        except Exception as exc:
            raise AssertionError(exc)
        conn.commit()
    kept(world.check(copy), "session_live")


def test_git_failed_when_git_cannot_answer(world) -> None:
    copy = world.make_copy("empty", commits=False)
    kept(world.check(copy), "git_failed")


def test_dirty_stash_unseen_commits_and_worktrees(world) -> None:
    copy = world.make_copy()
    root = copy["root"]
    (root / "new.txt").write_text("x")
    kept(world.check(copy), "dirty")
    (root / "new.txt").unlink()
    (root / "a.txt").write_text("changed\n")
    git(root, "stash", "-q")
    kept(world.check(copy), "stash")
    git(root, "stash", "drop", "-q")
    (root / "a.txt").write_text("two\n")
    git(root, "commit", "-q", "-am", "two")
    kept(world.check(copy), "unseen_commits")
    kept(world.check(copy, tips=[*copy["tips"], "a" * 40]), "unseen_commits")
    assert world.check(copy, tips=[*copy["tips"], git(root, "rev-parse", "HEAD")]).verdict == "deletable"
    elsewhere = world.tmp / "other-worktree"
    git(root, "worktree", "add", "-q", "--detach", str(elsewhere))
    kept(world.check(copy, tips=[git(root, "rev-parse", "HEAD")]), "worktrees")


def test_a_carnivore_ref_from_the_home_counts_as_seen(world) -> None:
    copy = world.make_copy()
    root = copy["root"]
    (root / "a.txt").write_text("two\n")
    git(root, "commit", "-q", "-am", "two")
    kept(world.check(copy), "unseen_commits")
    git(root, "update-ref", f"refs/carnivore/{HOME_ID}/main", "HEAD")
    assert world.check(copy).verdict == "deletable"




def idle_slot(world, copy) -> Path:
    path = world.jobs / "folders" / "proj-c0f1c0f1" / "slot1"
    claim = world.store.slot_claim(UID, str(copy["root"]), lambda n: str(path), "job_00000000000a")
    assert claim is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    git(copy["root"], "worktree", "add", "-q", "--detach", str(path))
    world.store.slot_free(str(path))
    return path


def test_an_idle_job_folder_goes_with_forget_but_a_dry_run_changes_nothing(world) -> None:
    copy = world.make_copy()
    slot = idle_slot(world, copy)
    before = world.snapshot()
    assert world.check(copy).verdict == "deletable"
    assert world.snapshot() == before
    assert slot.is_dir() and world.store.slot_rows(UID)
    done = world.forget(copy)
    assert done.verdict == "deleted"
    assert not slot.exists() and world.store.slot_rows(UID) == [] and not copy["root"].exists()


def test_a_claimed_or_kept_job_folder_keeps_the_copy(world) -> None:
    copy = world.make_copy()
    slot = idle_slot(world, copy)
    world.store.slot_claim(UID, str(copy["root"]), lambda n: str(slot), "job_00000000000b")
    kept(world.forget(copy), "job_running")
    assert slot.is_dir() and copy["root"].is_dir()
    world.store.slot_free(str(slot), keep_until=4102444800.0)
    kept(world.forget(copy), "job_running")
    assert slot.is_dir() and copy["root"].is_dir()


def test_a_slot_row_outside_the_jobs_root_is_an_unknown_worktree(world) -> None:
    copy = world.make_copy()
    outside = world.tmp / "not-the-jobs-root"
    git(copy["root"], "worktree", "add", "-q", "--detach", str(outside))
    world.store.slot_claim(UID, str(copy["root"]), lambda n: str(outside), "job_00000000000c")
    world.store.slot_free(str(outside))
    kept(world.forget(copy), "worktrees")
    assert outside.is_dir() and copy["root"].is_dir()


def test_a_dry_run_and_a_kept_forget_write_nothing(world) -> None:
    copy = world.make_copy()
    (copy["root"] / "dirty.txt").write_text("x")
    before = world.snapshot()
    kept(world.check(copy), "dirty")
    kept(world.forget(copy), "dirty")
    assert world.snapshot() == before and copy["root"].is_dir()




def test_trash_rungs_rename_carnivore_fallback_linux_and_refusals(tmp_path, monkeypatch) -> None:
    home, state = tmp_path / "home", tmp_path / "state"
    (home / ".Trash").mkdir(parents=True)
    state.mkdir()
    kw: Dict[str, Any] = {"now": NOW, "home": home, "state_dir": state}

    def folder(name: str) -> Path:
        path = tmp_path / "work" / name
        (path / "sub").mkdir(parents=True)
        (path / "sub" / "f").write_text("x")
        return path

    one = folder("one")
    got = trash.move(one, tool=str(tmp_path / "no-such-tool"), platform="darwin", **kw)
    assert got.kind == "platform" and not one.exists() and (home / ".Trash" / "one-20261116T090501" / "sub" / "f").read_text() == "x"
    two = folder("two")
    (tmp_path / "home2").mkdir()
    (tmp_path / "home2" / ".Trash").write_text("not a folder")
    got = trash.move(two, tool=str(tmp_path / "no-such-tool"), platform="darwin", **{**kw, "home": tmp_path / "home2"})
    assert got.kind == "carnivore" and not two.exists() and (state / "pack-trash" / "two-20261116T090501" / "sub" / "f").exists()
    three = folder("three")
    got = trash.move(three, platform="linux", **kw)
    info = home / ".local" / "share" / "Trash" / "info" / "three-20261116T090501.trashinfo"
    assert not three.exists() and got.kind == "platform" and "Path=" in info.read_text() and (home / ".local/share/Trash/files/three-20261116T090501").is_dir()
    four = folder("four")
    real_rename = os.rename

    def exdev(src, dst, *a, **k):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(os, "rename", exdev)
    with pytest.raises(trash.TrashRefused) as refused:
        trash.move(four, platform="linux", **kw)
    assert refused.value.code == "other_volume" and four.is_dir()
    assert not (home / ".local/share/Trash/info/four-20261116T090501.trashinfo").exists()
    monkeypatch.setattr(os, "rename", real_rename)
    with pytest.raises(trash.TrashRefused) as other:
        trash.move(four, platform="win32", **kw)
    assert other.value.code == "no_trash" and four.is_dir()
    link = tmp_path / "work" / "link"
    link.symlink_to(four)
    with pytest.raises(trash.TrashRefused):
        trash.move(link, platform="linux", **kw)
    from src.core.test_write_guard import OutsideTempWriteError

    with pytest.raises(OutsideTempWriteError):
        trash.move(Path("/Users/nobody-real/proj"), platform="linux", **kw)


def test_forget_keeps_the_copy_when_the_trash_refuses(world) -> None:
    copy = world.make_copy()

    def refuse(path: Path) -> trash.TrashResult:
        raise trash.TrashRefused("other_volume")

    got = world.forget(copy, trasher=refuse)
    kept(got, "other_volume")
    assert copy["root"].is_dir()
    with closing(world.conn()) as conn:
        assert conn.execute("SELECT archived_at, pack_state FROM projects WHERE uid = ?", (UID,)).fetchone()[1] == "replica"




def test_a_later_accept_never_raises_folder_made_or_auto(world) -> None:
    world.work.joinpath("byhand").mkdir()
    with closing(world.conn()) as conn:
        first = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid=UID, name="byhand", root=str(world.work / "byhand"))
    assert first["folder_made"] is False and first["created"] is True
    copies.record_made(world.store, root=first["root"], project_uid=UID, home_install_id=HOME_ID, auto=False, folder_made=False)
    with closing(world.conn()) as conn:
        again = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid=UID, name="byhand", root=str(world.work / "byhand"))
    assert again["created"] is False and again["folder_made"] is False
    assert copies.record_made(world.store, root=first["root"], project_uid=UID, home_install_id=HOME_ID, auto=True, folder_made=True) is False
    record = world.store.made_copy_get(os.path.realpath(first["root"]))
    assert (record["auto"], record["folder_made"]) == (0, 0)


def grant(world, install: str):
    with closing(world.conn()) as conn:
        key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))
        grants.create_grant(conn, peer_install_id=install, public_key=key, label="a", scopes=("replica",))
        return [g for g in grants.list_grants(conn) if g.peer_install_id == install][0]


def test_the_peer_routes_register_a_made_copy_and_answer_the_far_side(world, monkeypatch) -> None:
    monkeypatch.setattr("src.api.project_move_routes.read_live_panes", lambda: NO_PANES)
    app = FastAPI()
    app.include_router(replica_routes.router, prefix="/api/v1")
    app.include_router(copies_routes.router, prefix="/api/v1")
    current = {"g": grant(world, HOME_ID)}
    app.dependency_overrides[replica_routes._require_replica] = lambda: peer_auth.Principal("peer", current["g"])
    app.dependency_overrides[copies_routes._require_replica] = lambda: peer_auth.Principal("peer", current["g"])
    client = TestClient(app)
    base = {"project_uid": UID, "name": "viaroute", "root": str(world.work / "viaroute")}
    made = client.post("/api/v1/federation/pack/replica", json={**base, "auto": True})
    assert made.status_code == 200 and made.json()["folder_made"] is True
    record = world.store.made_copy_get(os.path.realpath(world.work / "viaroute"))
    assert (record["auto"], record["folder_made"], record["home_install_id"]) == (1, 1, HOME_ID)
    assert client.post("/api/v1/federation/pack/replica", json={**base, "auto": False}).json()["created"] is False
    assert world.store.made_copy_get(os.path.realpath(world.work / "viaroute"))["auto"] == 1
    assert client.post("/api/v1/federation/pack/replica", json={**base, "project_uid": "9" * 32, "name": "o", "root": str(world.work / "o")}).status_code == 200
    assert world.store.made_copy_get(os.path.realpath(world.work / "o"))["auto"] == 0

    url = "/api/v1/federation/pack/jobs/forget-copy"
    git(world.work / "viaroute", "init", "-q", "-b", "main")
    ask = client.post(url, json={"project_uid": UID, "tips": ["a" * 40]})
    assert ask.status_code == 200 and ask.json()["verdict"] == "kept" and ask.json()["code"] == "git_failed"
    assert set(ask.json()) == {"verdict", "code", "root", "ignored", "ignored_more"}
    current["g"] = grant(world, "iid-stranger")
    stranger = client.post(url, json={"project_uid": UID, "tips": [], "dry_run": False})
    assert stranger.json()["code"] == "not_a_copy" and (world.work / "viaroute").is_dir()
    assert client.post(url, json={"project_uid": UID, "tips": ["--x"]}).status_code == 422
    assert client.post(url, json={"project_uid": UID, "tips": [], "path": "/"}).status_code == 422
    app.dependency_overrides[copies_routes._require_replica] = lambda: peer_auth.OWNER
    assert client.post(url, json={"project_uid": UID, "tips": []}).status_code == 403
    assert "pack.jobs.forget_copy" in __import__("src.core.pack.machines.capabilities", fromlist=["x"]).names()


class _Links:

    def __init__(self, caps: List[str]) -> None:
        self._caps = caps

    def capabilities(self, install_id: str) -> List[str]:
        return self._caps

    def client(self, install_id: str) -> None:
        return None


def test_the_body_sent_to_a_computer_without_the_capability_is_todays_body(world, monkeypatch) -> None:
    from src.core.federation import peer_links

    with closing(world.conn()) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'trader', 'user', 't', 't')",
                     (str(world.work / "trader"), str(world.work / "trader")))
        conn.commit()
    sent: List[Dict[str, Any]] = []

    async def fake_call(peer, method, path, body=None, **_k):
        sent.append(body)
        return {"root": body["root"]}

    peer = type("Peer", (), {"peer_install_id": "iid-b", "label": "b", "key": "b"})()
    monkeypatch.setattr(project_replica_routes, "call_peer", fake_call)
    monkeypatch.setattr(project_replica_routes, "find_peer", lambda machine, **_k: peer)
    monkeypatch.setattr(project_replica_routes.direction, "contained", lambda iid: False)
    monkeypatch.setattr(project_replica_routes, "_sync_proxy_scope", lambda iid: None)
    monkeypatch.setattr(project_replica_routes.bundles, "is_repo", lambda root: False)
    today = {"project_uid": None, "name": "trader", "root": None, "company_uid": None, "company_name": None, "transport": "carried"}

    def run(auto: bool, caps: List[str]) -> Dict[str, Any]:
        monkeypatch.setattr(peer_links, "LINKS", _Links(caps))
        sent.clear()
        asyncio.run(project_replica_routes.add_project_replica("trader", project_replica_routes.AddReplicaRequest(machine="b", transport="carried", auto=auto)))
        return dict(sent[0])

    plain = run(False, [])
    today["project_uid"] = plain["project_uid"]
    assert json.dumps(plain, sort_keys=True) == json.dumps(today, sort_keys=True)
    assert json.dumps(run(True, []), sort_keys=True) == json.dumps(today, sort_keys=True)
    assert json.dumps(run(True, ["pack.replica"]), sort_keys=True) == json.dumps(today, sort_keys=True)
    assert run(True, ["pack.jobs.forget_copy"]) == {**today, "auto": True}
    assert run(False, ["pack.jobs.forget_copy"]) == today


def test_the_marks_copy_run_is_the_only_caller_that_asks_for_auto(monkeypatch, tmp_path) -> None:
    from src.core.pack.jobs import replicas as jobs_replicas

    asked: List[Any] = []

    async def fake_add(name, body):
        asked.append(body)

    store = JobStore(tmp_path)
    assert asyncio.run(jobs_replicas.ensure("trader", "p1x23456", "iid-b", store=store, add=fake_add, has=lambda u, i: False)) is True
    assert asked[0].auto is True and asked[0].transport == "carried"
    assert project_replica_routes.AddReplicaRequest(machine="b").auto is False




def test_a_submodule_set_to_ignore_never_hides_the_owners_edit(world) -> None:
    copy = world.make_copy()
    root = copy["root"]
    lib = world.tmp / "lib-repo"
    lib.mkdir()
    git(lib, "init", "-q", "-b", "main")
    (lib / "a.txt").write_text("x\n")
    git(lib, "add", "a.txt")
    git(lib, "commit", "-q", "-m", "lib")
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "lib")
    git(root, "config", "-f", ".gitmodules", "submodule.lib.ignore", "all")
    git(root, "add", ".gitmodules", "lib")
    git(root, "commit", "-q", "-m", "sub")
    (root / "lib" / "a.txt").write_text("owner edit\n")
    kept(world.check(copy), "dirty")


def test_a_detached_copy_loses_its_record_and_a_forgotten_one_can_come_back(world, monkeypatch) -> None:
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self_: world.work, raising=True)
    copy = world.make_copy("proj")
    root = os.path.realpath(copy["root"])
    done = world.forget(copy)
    assert done.verdict == "deleted" and world.store.made_copy_get(root) is None
    with closing(world.conn()) as conn:
        back = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid=UID, name="proj", root=None)
        row = conn.execute("SELECT archived_at, pack_state FROM projects WHERE uid = ?", (UID,)).fetchone()
    assert back["revived"] is True and back["folder_made"] is True and (row[0], row[1]) == (None, "replica")
    with closing(world.conn()) as conn:
        copy2 = replicas.detach_replica(conn, home_install_id=HOME_ID, project_uid=UID)
        conn.execute("UPDATE projects SET archived_at = '2026-01-01T00:00:00Z' WHERE root = ?", (back["root"],))
        conn.commit()
        shutil.rmtree(back["root"])
        again2 = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid=UID, name="proj", root=back["root"])
    assert copy2 and again2["revived"] is True and again2["adopted"] is False and again2["folder_made"] is True
    other = world.make_copy("other", uid="d" * 32)
    with closing(world.conn()) as conn:
        replicas.detach_replica(conn, home_install_id=HOME_ID, project_uid="d" * 32)
        again = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid="e" * 32, name="other", root=str(other["root"]))
    assert again["adopted"] is True and again["created"] is False


def test_the_detach_route_drops_the_record(world, monkeypatch) -> None:
    app = FastAPI()
    app.include_router(replica_routes.router, prefix="/api/v1")
    g = grant(world, HOME_ID)
    app.dependency_overrides[replica_routes._require_replica] = lambda: peer_auth.Principal("peer", g)
    client = TestClient(app)
    base = {"project_uid": UID, "name": "viaroute", "root": str(world.work / "viaroute"), "auto": True}
    assert client.post("/api/v1/federation/pack/replica", json=base).status_code == 200
    root = os.path.realpath(world.work / "viaroute")
    assert world.store.made_copy_get(root) is not None
    assert client.delete(f"/api/v1/federation/pack/replica/{UID}").json() == {"detached": True}
    assert world.store.made_copy_get(root) is None
    adopt = client.post("/api/v1/federation/pack/replica", json={**base, "project_uid": "f" * 32, "auto": False})
    assert adopt.json()["adopted"] is True and world.store.made_copy_get(root) is None


def test_a_trash_tool_that_moves_the_folder_but_exits_non_zero_is_a_move(world) -> None:
    copy = world.make_copy()
    world.fake_bin.write_text(f'#!/bin/sh\nmv "$1" "{world.fake_dir}/"\nexit 1\n')
    done = world.forget(copy)
    assert done.verdict == "deleted" and not copy["root"].exists() and (world.fake_dir / "proj").is_dir()


def test_the_real_trash_tool_is_never_run_by_a_test(world, monkeypatch) -> None:
    called: List[Any] = []
    monkeypatch.setattr(trash.subprocess, "run", lambda *a, **k: called.append(a))
    victim = world.work / "victim"
    victim.mkdir()
    trash.move(victim, now=NOW, home=world.home, state_dir=world.state, platform="darwin")
    assert called == [] and not victim.exists()


def test_a_slot_claimed_after_the_check_is_not_removed(world) -> None:
    copy = world.make_copy()
    path = str(world.jobs / "folders" / "x")
    with world.store._tx() as c:
        c.execute("INSERT INTO slots (path, project_uid, slot, repo_root, job_id, last_used) VALUES (?,?,?,?,?,?)", (path, UID, 1, "r", "job1", 1.0))
    assert world.store.slot_drop_idle(path, 5.0) is False and world.store.slot_rows(UID)
    world.store.slot_free(path)
    assert world.store.slot_drop_idle(path, 5.0) is True and not world.store.slot_rows(UID)


def test_a_session_under_the_symlinked_spelling_of_the_root_keeps_the_copy(world) -> None:
    link = world.tmp / "linkwork"
    link.symlink_to(world.work)
    root = link / "proj"
    with closing(world.conn()) as conn:
        answer = replicas.accept_replica(conn, home_install_id=HOME_ID, project_uid=UID, name="proj", root=str(root))
    git(Path(answer["root"]), "init", "-q", "-b", "main")
    copies.record_made(world.store, root=answer["root"], project_uid=UID, home_install_id=HOME_ID, auto=True, folder_made=True)
    with closing(world.conn()) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, working_dir, lifecycle, tmux_name, host_key, origin, created_at, updated_at) VALUES ('s9', ?, 'running', 'cloude_z', 'local', 'created', 't', 't')", (str(root),))
        conn.commit()
    got = copies.check(UID, HOME_ID, [], **world.kw())
    assert got.code in {"session_live"}, got
