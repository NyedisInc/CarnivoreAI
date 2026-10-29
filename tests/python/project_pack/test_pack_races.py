
from __future__ import annotations

import os
from contextlib import closing

from src.core.project_pack import constants as K
from src.core.project_pack import manifest, store, verify
from src.core.project_pack.trash import TrashError

from .pack_world import conn_of, run_pack_now, run_unpack_now
from .test_pack_core import storage_row, tree_digest


def test_an_edit_after_the_last_change_check_is_not_lost_to_the_trash(world, monkeypatch):
    real = manifest.write_readme

    def edit_after_proof(root, name):
        real(root, name)
        (world.root / "src" / "a.py").write_text("edited after the proof\n")

    monkeypatch.setattr(manifest, "write_readme", edit_after_proof)
    run_pack_now(world)
    row = storage_row(world)
    assert row["state"] == "unpacked" and "changed after the archive was proven" in row["last_error"]
    assert (world.root / "src" / "a.py").read_text() == "edited after the proof\n"
    assert not list(world.trash_dir.iterdir())


def test_unpack_stays_extracting_until_the_tree_is_verified(world, monkeypatch):
    run_pack_now(world)
    seen = []
    real = verify.verify_tree

    def spy(staging, entries, progress):
        with closing(conn_of(world)) as conn:
            seen.append(store.get(conn, world.ids["oldsite"])["state"])
        return real(staging, entries, progress)

    monkeypatch.setattr(verify, "verify_tree", spy)
    run_unpack_now(world)
    assert seen == [K.STATE_EXTRACTING]
    assert storage_row(world)["state"] == "unpacked"


def test_children_are_unpacked_with_the_parent_even_when_the_trash_step_fails(world):
    run_pack_now(world)
    assert storage_row(world, "kid")["state"] == "packed"

    def broken(paths):
        raise TrashError("no trash today")

    world.env.trash = broken
    run_unpack_now(world)
    assert storage_row(world)["state"] == "unpacked"
    assert storage_row(world, "kid")["state"] == "unpacked"
