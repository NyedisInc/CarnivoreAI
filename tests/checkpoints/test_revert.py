
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from src.api import checkpoint_revert_routes as routes
from src.core.checkpoints import capture as cap
from src.core.checkpoints import pins
from src.core.checkpoints import revert as rv
from src.core.checkpoints.store import KIND_SAFETY, CheckpointStore
from src.core.project_move.plan import PaneListing
from tests.checkpoints.test_capture import files_in, git


@pytest.fixture
def world(tmp_path: Path):
    r = tmp_path / "repo"
    (r / "pkg" / "deep").mkdir(parents=True)
    (r / "a.txt").write_text("a\n")
    (r / "pkg" / "deep" / "b.txt").write_text("b\n")
    (r / ".gitignore").write_text("node_modules/\ncache\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    (r / "a.txt").write_text("a staged\n")
    git(r, "add", "a.txt")
    state = tmp_path / "state"
    return r, state, CheckpointStore(state / "bookmarks.db")


def snap(repo: Path, state: Path, store: CheckpointStore, prompt: str):
    result = cap.capture(repo, session_uuid="s1", conversation="c", prompt_uuid=prompt, store=store, state_root=state)
    assert result.checkpoint is not None, result.skipped
    return result.checkpoint


def do_revert(store: CheckpointStore, cp, state: Path) -> rv.RevertResult:
    return rv.revert(store, cp, rv.preview(store, cp, state).fingerprint, state)


def test_files_come_back_and_index_branch_head_never_move(world) -> None:
    repo, state, store = world
    (repo / "a.txt").write_text("a in turn 1\n")
    cp = snap(repo, state, store, "p1")
    index_before = (repo / ".git" / "index").read_bytes()
    head, branch, staged = git(repo, "rev-parse", "HEAD"), git(repo, "symbolic-ref", "HEAD"), git(repo, "diff", "--cached")
    (repo / "a.txt").write_text("a later\n")
    (repo / "pkg" / "deep" / "b.txt").unlink()
    (repo / "pkg" / "new.py").write_text("x\n")
    plan = rv.preview(store, cp, state)
    assert (plan.change, plan.create, plan.delete) == (["a.txt"], ["pkg/deep/b.txt"], ["pkg/new.py"])
    rv.revert(store, cp, plan.fingerprint, state)
    assert (repo / "a.txt").read_text() == "a in turn 1\n"
    assert (repo / "pkg" / "deep" / "b.txt").read_text() == "b\n"
    assert not (repo / "pkg" / "new.py").exists()
    assert (repo / ".git" / "index").read_bytes() == index_before, "the real index is never written"
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "symbolic-ref", "HEAD") == branch
    assert git(repo, "diff", "--cached") == staged, "what was staged stays staged"


def test_left_out_and_ignored_files_never_change(world) -> None:
    repo, state, store = world
    cp = snap(repo, state, store, "p1")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.js").write_text("ignored\n")
    (repo / ".env.local").write_text("TOKEN=secret\n")
    (repo / "cache").write_text("an ignored file where nothing was\n")
    with open(repo / "huge.bin", "wb") as fh:
        fh.truncate(cap.MAX_FILE_BYTES + 1)
    before = {p: v[0] for p, v in files_in(repo).items() if "/.git/" not in p}
    done = do_revert(store, cp, state)
    after = {p: v[0] for p, v in files_in(repo).items() if "/.git/" not in p}
    assert after == before, "nothing outside the snapshot's own files moved"
    assert set(done.safety.left_out) >= {".env.local", "huge.bin"}


def test_a_tracked_file_in_the_way_of_an_ignored_folder_is_kept(world) -> None:
    repo, state, store = world
    (repo / "cache").write_text("tracked in turn 1\n")
    git(repo, "add", "-f", "cache")
    cp = snap(repo, state, store, "p1")
    git(repo, "rm", "-q", "--cached", "cache")
    (repo / "cache").unlink()
    (repo / "cache").mkdir()
    (repo / "cache" / "blob").write_text("ignored build output\n")
    done = do_revert(store, cp, state)
    assert (repo / "cache" / "blob").read_text() == "ignored build output\n"
    assert {"path": "cache", "reason": rv.KEPT_IN_THE_WAY} in done.kept


def test_the_safety_snapshot_is_taken_first_and_undoes_the_revert(world) -> None:
    repo, state, store = world
    cp = snap(repo, state, store, "p1")
    (repo / "a.txt").write_text("work worth keeping\n")
    (repo / "fresh.txt").write_text("new since\n")
    done = do_revert(store, cp, state)
    assert done.safety.kind == KIND_SAFETY and [c.kind for c in store.for_session("s1")].count(KIND_SAFETY) == 1
    assert not (repo / "fresh.txt").exists()
    do_revert(store, done.safety, state)
    assert (repo / "a.txt").read_text() == "work worth keeping\n"
    assert (repo / "fresh.txt").read_text() == "new since\n"


def test_an_unreadable_snapshot_refuses_before_any_file_changes(world) -> None:
    repo, state, store = world
    (repo / "only-in-turn.txt").write_text("this blob lives in the shadow alone\n")
    cp = snap(repo, state, store, "p1")
    blob = git(repo, "hash-object", "only-in-turn.txt").strip()
    plan = rv.preview(store, cp, state)
    (repo / "only-in-turn.txt").unlink()
    (repo / "a.txt").write_text("edited\n")
    (Path(cp.shadow) / "objects" / blob[:2] / blob[2:]).unlink()
    before = {p: v for p, v in files_in(repo).items() if "/.git/" not in p}
    with pytest.raises(rv.RevertRefused) as refused:
        rv.revert(store, cp, plan.fingerprint, state)
    assert refused.value.code == "checkpoint_unreadable"
    assert {p: v for p, v in files_in(repo).items() if "/.git/" not in p} == before, "not a byte or mtime moved"
    assert [c.kind for c in store.for_session("s1")] == ["turn"], "the unneeded safety snapshot is dropped"


def test_files_that_changed_since_the_preview_refuse(world) -> None:
    repo, state, store = world
    cp = snap(repo, state, store, "p1")
    (repo / "a.txt").write_text("one\n")
    plan = rv.preview(store, cp, state)
    (repo / "a.txt").write_text("two, after the preview\n")
    with pytest.raises(rv.RevertRefused) as refused:
        rv.revert(store, cp, plan.fingerprint, state)
    assert refused.value.code == "changed_since_preview"
    assert (repo / "a.txt").read_text() == "two, after the preview\n"


def test_a_symlinked_folder_is_never_followed_out_of_the_repo(world, tmp_path: Path) -> None:
    repo, state, store = world
    cp = snap(repo, state, store, "p1")
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deep" / "b.txt").write_text("not the repo's\n")
    (outside / "deep" / "other.txt").write_text("keep me\n")
    os.rename(repo / "pkg", tmp_path / "pkg-moved")
    os.symlink(outside, repo / "pkg")
    before = files_in(outside)
    do_revert(store, cp, state)
    assert files_in(outside) == before, "nothing outside the work tree is read through or written"
    assert not (repo / "pkg").is_symlink() and (repo / "pkg" / "deep" / "b.txt").read_text() == "b\n"


def test_a_pinned_snapshot_survives_the_repos_own_gc(world) -> None:
    repo, state, store = world
    (repo / "a.txt").write_text("one\n")
    git(repo, "commit", "-qam", "one")
    pinned = snap(repo, state, store, "p-pinned")
    (repo / "a.txt").write_text("two\n")
    git(repo, "commit", "-qam", "two")
    loose = snap(repo, state, store, "p-loose")
    with sqlite3.connect(store.path) as conn:
        conn.execute("CREATE TABLE bookmarks (session_uuid TEXT, entry_uuid TEXT)")
        conn.execute("INSERT INTO bookmarks VALUES ('s1', 'p-pinned')")
    assert pins.rebuild(store, pinned.shadow)
    git(repo, "checkout", "-q", "--orphan", "fresh")
    (repo / "a.txt").write_text("three\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fresh")
    git(repo, "branch", "-q", "-D", "main")
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "-q", "--prune=now")
    paths = rv.resolve_paths(pinned, state)
    assert rv.prove_readable(paths, pinned.commit_sha) > 0
    with pytest.raises(rv.RevertRefused):
        rv.prove_readable(paths, loose.commit_sha)
    (repo / "only-here.txt").write_text("shadow-only content\n")
    safety = cap.capture(repo, session_uuid="s1", conversation="c", prompt_uuid="sf", store=store, state_root=state,
                         kind=KIND_SAFETY).checkpoint
    with sqlite3.connect(store.path) as conn:
        conn.execute("INSERT INTO bookmarks VALUES ('s1', 'p-later')")
    store.put(session_uuid="s1", conversation="c", prompt_uuid="p-later", kind="turn", work_tree=safety.work_tree,
              shadow=safety.shadow, ref=safety.ref, commit_sha=safety.commit_sha, tree_sha=safety.tree_sha,
              head_sha=None, left_out=[], capture_ms=0)
    assert pins.rebuild(store, pinned.shadow)
    git(Path(pinned.shadow), "prune-packed")
    with sqlite3.connect(store.path) as conn:
        conn.execute("DELETE FROM bookmarks")
    assert pins.rebuild(store, pinned.shadow) is None
    assert rv.prove_readable(paths, safety.commit_sha) > 0, "unpinning never loses the shadow's only copy"


def test_isolation_refuses_another_live_session_in_the_folder_tree() -> None:
    panes = PaneListing(ok=True, panes=(("me", 1, "/r/pkg"), ("child", 2, "/r/sub"), ("parent", 3, "/"),
                                        ("elsewhere", 4, "/other")))
    reasons = routes.isolation_reasons(panes, "me", "/r", "idle")
    assert [r.split(" ")[1] for r in reasons] == ["child", "parent"]
    assert routes.isolation_reasons(PaneListing(ok=True, panes=(("me", 1, "/r"),)), "me", "/r", "idle") == []
    assert routes.isolation_reasons(PaneListing(ok=True), "me", "/r", "working") != []
    assert routes.isolation_reasons(PaneListing(ok=False, reason="x"), "me", "/r", "idle") != []


def test_revert_is_the_owners_alone() -> None:
    import asyncio

    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    class Req:
        scope: dict = {"path": "/api/v1/sessions/1/checkpoints/1/revert"}
        url = type("U", (), {"path": "/api/v1/sessions/1/checkpoints/1/revert"})()

    async def admitted(*_a, **_k) -> bool:
        return True

    original = routes.require_auth
    routes.require_auth = admitted
    try:
        with pytest.raises(HTTPException) as refused:
            asyncio.run(routes.require_owner(Req(), HTTPAuthorizationCredentials(scheme="Bearer", credentials="cak_x")))
        assert refused.value.status_code == 403
    finally:
        routes.require_auth = original
    mcp = Path(__file__).resolve().parents[2] / "src" / "core" / "mcp"
    assert not [p for p in mcp.rglob("*.py") if "checkpoints.revert" in p.read_text() or "revert_files" in p.read_text()]
