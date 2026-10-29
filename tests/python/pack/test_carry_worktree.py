
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from test_carry_tree import git, make_world  # noqa: F401
from test_session_move import world  # noqa: F401

from src.core.pack.carry import scan, send, worktree
from src.core.pack.migrate import apply
from src.core.pack.migrate.plan import MigrateError
from src.core.pack.move import moved_note


def add_worktree(root_a: Path, home_a: Path) -> Path:
    repo = root_a / "PillPanic"
    wt = home_a / "dev-worktrees" / "PillPanic-art"
    git(repo, "worktree", "add", "-q", "-b", "art", str(wt))
    (wt / "a.txt").write_text("art staged\n")
    git(wt, "add", "a.txt")
    (wt / "b.txt").write_text("art unstaged\n")
    (wt / "new.bin").write_bytes(bytes(range(256)))
    return wt


def carry(request, uid, root_a, tmp_path, op="op-wt-1"):
    found = scan.scan_project(str(root_a))
    return found, asyncio.run(send.send_units(apply.guarded(request), found, project_uid=uid, op_id=op, outbox=str(tmp_path / "outbox"), air_gap=False, label="studio"))


@pytest.fixture
def homes(tmp_path, monkeypatch):
    home_a, home_b = tmp_path / "home_a", tmp_path / "home_b"
    home_a.mkdir()
    home_b.mkdir()
    monkeypatch.setenv("HOME", str(home_a))
    monkeypatch.setattr(worktree, "home_dir", lambda: str(home_b))
    monkeypatch.setattr("src.api.federation_pack_carry_routes.settings.auth_config_file", tmp_path / "no-config.json", raising=False)
    return home_a, home_b


def test_an_outside_worktree_lands_at_the_same_home_relative_path_with_its_work(world, tmp_path, homes) -> None:
    home_a, home_b = homes
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    wt = add_worktree(root_a, home_a)
    found, rows = carry(request, uid, root_a, tmp_path)
    assert found.worktrees == [str(wt)] and found.worktree_repos == {str(wt): "PillPanic"}
    landed = home_b / "dev-worktrees" / "PillPanic-art"
    listed = git(root_b / "PillPanic", "worktree", "list", "--porcelain")
    assert f"worktree {os.path.realpath(landed)}" in listed and "branch refs/heads/art" in listed
    for name in ("a.txt", "b.txt", "new.bin"):
        assert (landed / name).read_bytes() == (wt / name).read_bytes(), name
    assert git(landed, "status", "--porcelain") == git(wt, "status", "--porcelain") and git(landed, "diff", "--cached") == git(wt, "diff", "--cached")
    row = next(r for r in rows if r.get("kind") == "worktree")
    assert row["paths"] == {str(wt): str(landed)} and row["restored"] is True
    again = carry(request, uid, root_a, tmp_path, op="op-wt-2")[1]
    assert next(r for r in again if r.get("kind") == "worktree")["paths"] == row["paths"]
    note = moved_note.note_text("studio", str(root_a), str(root_b), [], {str(wt): str(landed)})
    assert f"{wt} is now {landed}" in note and f"{wt} is now {landed}" in moved_note.paste_text("studio", str(root_a), str(root_b), [], {str(wt): str(landed)})
    assert "refs/carnivore-wip" not in git(root_b / "PillPanic", "for-each-ref") + git(root_a / "PillPanic", "for-each-ref")


def test_a_cloud_sync_home_path_falls_back_to_the_worktree_root_and_a_refusal_leaves_nothing(world, tmp_path, homes, monkeypatch) -> None:
    home_a, home_b = homes
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    monkeypatch.setattr("src.core.pack.carry.worktree.project_worktree.read_root", lambda _p: str(home_b / "wtroot"))
    wt = home_a / "Dropbox" / "PillPanic-art"
    wt.parent.mkdir()
    git(root_a / "PillPanic", "worktree", "add", "-q", "-b", "art", str(wt))
    (wt / "a.txt").write_text("dirty\n")
    rows = carry(request, uid, root_a, tmp_path)[1]
    landed = home_b / "wtroot" / "PillPanic" / "PillPanic-art"
    assert next(r for r in rows if r.get("kind") == "worktree")["paths"] == {str(wt): str(landed)} and (landed / "a.txt").read_text() == "dirty\n"
    assert not (home_b / "Dropbox").exists()
    git(root_b / "PillPanic", "worktree", "remove", "--force", str(landed))
    git(root_b / "PillPanic", "branch", "-D", "art")
    git(root_b / "PillPanic", "branch", "art", "HEAD~0")
    (wt / "x.txt").write_text("x\n")
    git(wt, "add", "x.txt")
    git(wt, "commit", "-q", "-m", "art moves on")
    import shutil
    shutil.rmtree(home_b / "wtroot")
    with pytest.raises(MigrateError) as refused:
        carry(request, uid, root_a, tmp_path, op="op-wt-3")
    assert refused.value.code in ("target_has_own_changes", "carry_failed") and not (home_b / "wtroot").exists()
