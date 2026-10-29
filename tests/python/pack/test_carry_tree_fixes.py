
from __future__ import annotations

import asyncio
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from test_carry_tree import git, make_world, send_all  # noqa: F401
from test_session_move import world  # noqa: F401

from src.api import federation_pack_carry_routes as carry_routes
from src.core.pack.carry import land, scan, send
from src.core.pack.migrate import apply
from src.core.pack.migrate.plan import MigrateError
from src.core.pack.migrate.receive import MigrateRefused
from src.core.pack.machines import restrictions


def clean_clone(world, tmp_path):
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    src = root_a / "PillPanic"
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "all work")
    subprocess.run(["git", "clone", "-q", str(src), str(root_b / "PillPanic")], check=True, capture_output=True)
    return a, b, request, uid, root_a, root_b, outbox


def refused(request, uid, root_a, outbox, op_id):
    with pytest.raises(MigrateError) as err:
        send_all(request, uid, root_a, outbox, op_id=op_id)
    return err.value


def test_b2_an_ignored_local_file_is_never_overwritten_by_checkout_or_work(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = clean_clone(world, tmp_path)
    dst, src = root_b / "PillPanic", root_a / "PillPanic"
    (dst / ".git" / "info" / "exclude").write_text(".env\nlocal.cfg\n")
    (dst / ".env").write_text("local\n")
    (dst / "local.cfg").write_text("mine\n")
    (src / ".env").write_text("sender\n")
    git(src, "add", "-f", ".env")
    git(src, "commit", "-q", "-m", "track env")
    err = refused(request, uid, root_a, outbox, "op-b2a")
    assert err.code == "target_has_own_changes" and (dst / ".env").read_text() == "local\n"
    (dst / ".env").unlink()
    (dst / "local.cfg").write_text("mine\n")
    git(dst, "pull", "-q", str(src), "main")
    (src / "local.cfg").write_text("sender work\n")
    err = refused(request, uid, root_a, outbox, "op-b2b")
    assert err.code == "target_has_own_changes" and (dst / "local.cfg").read_text() == "mine\n"


def test_s1_a_refused_apply_leaves_no_new_git_and_no_new_repo_at_the_root(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    plain = root_b / "PillPanic"
    plain.mkdir()
    (plain / "a.txt").write_text("mine\n")
    assert refused(request, uid, root_a, outbox, "op-s1").code == "target_has_own_changes"
    assert not (plain / ".git").exists() and (plain / "a.txt").read_text() == "mine\n" and sorted(p.name for p in plain.iterdir()) == ["a.txt"]
    unit = {"rel": ".", "commits": True, "branch": "main", "head": "a" * 40}
    with pytest.raises(MigrateRefused):
        land.apply_repo(str(root_b), "iid-a", unit, str(tmp_path / "x"), "refs/carnivore-wip/o/x", air_gap=False)
    assert not (root_b / ".git").exists()


def test_s2_a_refused_apply_leaves_the_receivers_branch_where_it_was(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = clean_clone(world, tmp_path)
    dst, src = root_b / "PillPanic", root_a / "PillPanic"
    git(dst, "checkout", "-q", "-b", "feature")
    (dst / "own.txt").write_text("own\n")
    git(dst, "add", "own.txt")
    git(dst, "commit", "-q", "-m", "own")
    git(dst, "checkout", "-q", "main")
    git(src, "checkout", "-q", "-b", "feature")
    (src / "theirs.txt").write_text("theirs\n")
    git(src, "add", "theirs.txt")
    git(src, "commit", "-q", "-m", "theirs")
    assert refused(request, uid, root_a, outbox, "op-s2").code == "target_has_own_changes"
    assert git(dst, "symbolic-ref", "--short", "HEAD").strip() == "main"


def test_s7_a_refused_apply_keeps_the_receivers_own_untracked_file_of_the_same_name(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    (root_a / "PillPanic" / "new.txt").write_text("SENDER WIP\n")
    plain = root_b / "PillPanic"
    plain.mkdir()
    (plain / "new.txt").write_text("RECEIVER OWN\n")
    assert refused(request, uid, root_a, outbox, "op-s7").code == "target_has_own_changes"
    assert (plain / "new.txt").read_text() == "RECEIVER OWN\n" and not (plain / ".git").exists()


def test_s3_an_origin_url_with_a_credential_is_never_accepted() -> None:
    for bad in ("https://x-access-token:tok@github.com/o/r", "https://user@github.com/o/r", "https://@h/r", "ext::sh -c id", "http://github.com/o/r"):
        assert not land.REMOTE_RE.match(bad), bad
        with pytest.raises(ValueError):
            carry_routes.Unit(kind="repo", rel="x", blob_id="b", branch="main", head="a" * 40, remote=bad)
    for good in ("https://github.com/o/r.git", "git@github.com:o/r.git"):
        assert land.REMOTE_RE.match(good)


def test_s4_the_room_check_counts_what_the_checkout_writes(world, tmp_path, monkeypatch) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    (root_a / "PillPanic" / "zeros.bin").write_bytes(bytes(6_000_000))
    git(root_a / "PillPanic", "add", "zeros.bin")
    git(root_a / "PillPanic", "commit", "-q", "-m", "big")
    seen = []
    real = land._room
    monkeypatch.setattr(land, "_room", lambda root, size: (seen.append(size), real(root, size))[1])
    send_all(request, uid, root_a, outbox, op_id="op-s4")
    assert max(seen) >= 6_000_000, seen


def test_s5_a_retry_after_a_failed_send_is_not_refused_for_the_carrys_own_leftovers(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    send_all(request, uid, root_a, outbox, op_id="op-s5a")
    src, dst = root_a / "PillPanic", root_b / "PillPanic"
    (src / "b.txt").write_text("the agent kept working\n")
    (src / "u2.txt").write_text("new untracked\n")
    rows = send_all(request, uid, root_a, outbox, op_id="op-s5b")
    assert rows[0]["restored"] is True
    assert git(dst, "status", "--porcelain") == git(src, "status", "--porcelain") and (dst / "u2.txt").read_text() == "new untracked\n"
    (dst / "b.txt").write_text("the owner edited it here\n")
    (src / "b.txt").write_text("changed again\n")
    assert refused(request, uid, root_a, outbox, "op-s5c").code == "target_has_own_changes" and (dst / "b.txt").read_text() == "the owner edited it here\n"


def test_s6_the_company_allow_list_is_enforced_on_carry(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    with closing(b.conn()) as conn:
        conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Acme', 'company-acme-1', 't', 't')")
        conn.execute("UPDATE projects SET company_id = (SELECT id FROM companies WHERE uid = 'company-acme-1') WHERE uid = ?", (uid,))
        conn.commit()
    b.restrictions = restrictions.Restrictions(allowed_companies=["company-other-2"])
    with pytest.raises(MigrateError) as err:
        asyncio.run(send.call(apply.guarded(request), send.CHECK_PATH, {"project_uid": uid, "units": [], "which": []}, "check"))
    assert err.value.code == "pack_restricted"
    b.restrictions = restrictions.Restrictions(allowed_companies=["company-acme-1"])
    asyncio.run(send.call(apply.guarded(request), send.CHECK_PATH, {"project_uid": uid, "units": [], "which": []}, "check"))
