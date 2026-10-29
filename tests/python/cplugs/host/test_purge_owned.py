
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.host import purge_owned


def _tree(state: Path) -> None:
    (state / "time-machine" / "proj").mkdir(parents=True)
    (state / "time-machine" / "limits.json").write_text("{}")
    (state / "time-machine" / "proj" / "a.bin").write_bytes(b"a" * 4)
    (state / "keep.txt").write_text("core")


def test_plan_counts_and_purge_deletes_the_declared_tree_and_its_folders(tmp_path: Path) -> None:
    _tree(tmp_path)
    assert len(purge_owned.plan(tmp_path, ["time-machine"]).delete) == 2
    carried = purge_owned.purge(tmp_path, ["time-machine"])
    assert len(carried.delete) == 2 and not (tmp_path / "time-machine").exists()
    assert (tmp_path / "keep.txt").read_text() == "core"


def test_a_declared_path_that_is_absent_is_nothing_to_do(tmp_path: Path) -> None:
    assert purge_owned.purge(tmp_path, ["time-machine"]).delete == []


def test_a_symlink_is_unlinked_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("mine")
    state = tmp_path / "state"
    (state / "time-machine").mkdir(parents=True)
    (state / "time-machine" / "link").symlink_to(outside)
    purge_owned.purge(state, ["time-machine"])
    assert (outside / "precious.txt").read_text() == "mine" and not (state / "time-machine").exists()


def test_a_declared_path_that_resolves_outside_the_state_dir_is_refused_before_any_delete(tmp_path: Path) -> None:
    state = tmp_path / "state"
    outside = tmp_path / "outside"
    state.mkdir()
    outside.mkdir()
    (outside / "f").write_text("x")
    (state / "ok").mkdir()
    (state / "ok" / "g").write_text("y")
    (state / "hop").symlink_to(outside)
    with pytest.raises(purge_owned.PurgePathRefused):
        purge_owned.purge(state, ["ok", "hop/f"])
    assert (state / "ok" / "g").exists() and (outside / "f").exists()
