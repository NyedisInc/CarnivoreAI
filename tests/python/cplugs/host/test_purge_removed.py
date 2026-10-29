
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.host import purge_owned, purge_removed
from src.cplugs.sdk.data_decl import DataDecl, DataPolicy


def _decl(store_id: str, purge: str, **where: str) -> DataDecl:
    return DataDecl(id=store_id, kind="folder", scope_by="install", policy=DataPolicy(own="excluded", share="excluded", reason="test", purge=purge), **where)


def _seed(root: Path) -> Path:
    (root / "sub").mkdir(parents=True)
    f = root / "sub" / "x.db"
    f.write_text("data")
    return f


def test_a_removed_state_path_store_is_deleted_and_a_kept_one_stays(tmp_path: Path) -> None:
    gone, kept = _seed(tmp_path / "gone-store"), _seed(tmp_path / "kept-store")
    decls = [_decl("a", "removed", state_path="gone-store"), _decl("b", "kept", state_path="kept-store")]
    roots = purge_removed.resolve_roots(tmp_path, "p", decls, {})
    assert roots == [(tmp_path / "gone-store").resolve()]
    assert purge_owned.plan_paths(roots).delete == [gone.resolve()]
    purge_owned.purge_paths(roots)
    assert not gone.exists() and not (tmp_path / "gone-store").exists()
    assert kept.exists()


def test_a_removed_root_setting_store_outside_the_state_folder_is_deleted(tmp_path: Path) -> None:
    state, chosen = tmp_path / "state", tmp_path / "owner" / "boards"
    state.mkdir()
    f = _seed(chosen)
    roots = purge_removed.resolve_roots(state, "p", [_decl("a", "removed", root_setting="boardsRoot")], {"boardsRoot": str(chosen)})
    purge_owned.purge_paths(roots)
    assert not f.exists()


def test_a_removed_store_overlapping_a_kept_store_is_skipped(tmp_path: Path) -> None:
    kept = _seed(tmp_path / "shared")
    decls = [_decl("a", "removed", state_path="shared"), _decl("b", "kept", state_path="shared/sub")]
    assert purge_removed.resolve_roots(tmp_path, "p", decls, {}) == []
    assert kept.exists()


@pytest.mark.parametrize("where", [{"state_path": "../outside"}, {"state_path": "../../etc"}])
def test_a_state_path_outside_the_state_folder_is_refused(tmp_path: Path, where: dict) -> None:
    state = tmp_path / "state"
    state.mkdir()
    with pytest.raises(purge_owned.PurgePathRefused):
        purge_removed.resolve_roots(state, "p", [_decl("a", "removed", **where)], {})


@pytest.mark.parametrize("chosen", ["/", "~", "STATE", "PARENT"])
def test_a_too_broad_chosen_root_is_refused(tmp_path: Path, chosen: str) -> None:
    state = tmp_path / "state"
    state.mkdir()
    value = {"STATE": str(state), "PARENT": str(tmp_path)}.get(chosen, chosen)
    with pytest.raises(purge_owned.PurgePathRefused):
        purge_removed.resolve_roots(state, "p", [_decl("a", "removed", root_setting="r")], {"r": value})


def test_a_symlink_root_is_refused_and_a_symlink_inside_is_not_followed(tmp_path: Path) -> None:
    outside = _seed(tmp_path / "outside")
    state = tmp_path / "state"
    (state / "store").mkdir(parents=True)
    (state / "store" / "link").symlink_to(tmp_path / "outside")
    roots = purge_removed.resolve_roots(state, "p", [_decl("a", "removed", state_path="store")], {})
    purge_owned.purge_paths(roots)
    assert outside.exists(), "a symlink inside the store was followed"
    (state / "lnk").symlink_to(tmp_path / "outside")
    with pytest.raises(purge_owned.PurgePathRefused):
        purge_removed.resolve_roots(state, "p", [_decl("a", "removed", state_path="lnk")], {})
