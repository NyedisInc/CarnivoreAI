
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.cplugs.host import default_roots, state as owner_state
from src.cplugs.registry import CPLUGS
from src.cplugs.reviewboard import root, wire
from src.cplugs.reviewboard.errors import NoRoot

import pytest

MANIFEST = next(d.manifest for d in CPLUGS if d.id == "reviewboard")


def test_a_blank_setting_gets_the_default_path_and_still_resolves_as_the_default(tmp_path: Path) -> None:
    owner_state.update(tmp_path, MANIFEST, None, lambda st: replace(st, enabled=True))
    assert default_roots.fill(tmp_path, MANIFEST) == {"boardsRoot": str(tmp_path / "review-boards")}
    assert owner_state.get(tmp_path, MANIFEST).settings["boardsRoot"] == str(tmp_path / "review-boards")
    assert default_roots.fill(tmp_path, MANIFEST) == {}, "once"
    path, is_default = root.resolve_root(str(tmp_path / "review-boards"), tmp_path)
    assert is_default and path == tmp_path / "review-boards"


def test_an_explicit_value_is_never_overwritten(tmp_path: Path) -> None:
    owner_state.update(tmp_path, MANIFEST, None, lambda st: replace(st, enabled=True, settings={"boardsRoot": "/Users/x/boards"}))
    assert default_roots.fill(tmp_path, MANIFEST) == {}
    assert owner_state.get(tmp_path, MANIFEST).settings["boardsRoot"] == "/Users/x/boards"


def test_other_plugins_are_left_alone(tmp_path: Path) -> None:
    save = next(d.manifest for d in CPLUGS if d.id == "save")
    assert default_roots.blank_defaults(tmp_path, save, {}) == {}


def test_the_filled_default_is_not_offered_as_the_task_manager_folder(tmp_path: Path) -> None:
    from types import SimpleNamespace

    ctx = SimpleNamespace(settings_now=lambda: {"boardsRoot": str(tmp_path / "review-boards")}, storage=SimpleNamespace(path=tmp_path / "cplugs" / "reviewboard"))
    with pytest.raises(NoRoot) as raised:
        wire.explicit_root(ctx)
    assert raised.value.reason == "unset"
