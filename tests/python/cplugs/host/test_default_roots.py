
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.plugins.host import default_roots, state as owner_state
from src.plugins.registry import CPLUGS
from tests.python.cplugs.folder_plugin_fixture import definition

DEFINITION = definition()
MANIFEST = DEFINITION.manifest
FILLED = DEFINITION.filled_roots


def test_a_blank_setting_gets_the_default_path_and_still_resolves_as_the_default(tmp_path: Path) -> None:
    owner_state.update(tmp_path, MANIFEST, None, lambda st: replace(st, enabled=True))
    assert default_roots.fill(tmp_path, MANIFEST, FILLED) == {"boardsRoot": str(tmp_path / "review-boards")}
    assert owner_state.get(tmp_path, MANIFEST).settings["boardsRoot"] == str(tmp_path / "review-boards")
    assert default_roots.fill(tmp_path, MANIFEST, FILLED) == {}, "once"


def test_an_explicit_value_is_never_overwritten(tmp_path: Path) -> None:
    owner_state.update(tmp_path, MANIFEST, None, lambda st: replace(st, enabled=True, settings={"boardsRoot": "/Users/x/boards"}))
    assert default_roots.fill(tmp_path, MANIFEST, FILLED) == {}
    assert owner_state.get(tmp_path, MANIFEST).settings["boardsRoot"] == "/Users/x/boards"


def test_a_store_the_plugin_does_not_list_is_not_filled(tmp_path: Path) -> None:
    owner_state.update(tmp_path, MANIFEST, None, lambda st: replace(st, enabled=True))
    assert default_roots.fill(tmp_path, MANIFEST) == {}


def test_other_plugins_are_left_alone(tmp_path: Path) -> None:
    save = next(d.manifest for d in CPLUGS if d.id == "save")
    assert default_roots.blank_defaults(tmp_path, save, {}) == {}

