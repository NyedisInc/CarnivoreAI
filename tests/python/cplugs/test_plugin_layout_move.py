
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from src.core.plugin_registry import plugin_layout
from src.plugins.host import folder_watch, install_folder, registry_boot, registry_store, sidecar_registry

UUID_CLOCK = "0123456789abcdef0123456789abcdef"


def tree(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_text() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_lookup_answers_the_old_place_until_only_the_old_place_exists_no_more(tmp_path):
    state = tmp_path
    assert plugin_layout.code_root(state, "clock") == state / "plugins" / "clock"
    (state / "cplug-code" / "clock").mkdir(parents=True)
    assert plugin_layout.code_root(state, "clock") == state / "cplug-code" / "clock"
    (state / "plugins" / "clock").mkdir(parents=True)
    assert plugin_layout.code_root(state, "clock") == state / "plugins" / "clock"
    key = UUID_CLOCK
    assert plugin_layout.data_root(state, key) == state / "plugin-data" / key
    (state / "cplugs" / key).mkdir(parents=True)
    assert plugin_layout.data_root(state, key) == state / "cplugs" / key
    (state / "plugin-data" / key).mkdir(parents=True)
    assert plugin_layout.data_root(state, key) == state / "plugin-data" / key
    assert plugin_layout.data_root(state, "huddle") == state / "cplugs" / "huddle"


def test_apply_moves_renames_code_and_data_and_failed_move_undoes_every_rename(tmp_path, monkeypatch):
    state = tmp_path / "support"
    (state / "cplug-code" / "clock").mkdir(parents=True)
    (state / "cplug-code" / "clock" / "main.py").write_text("print(1)\n")
    data_clock = state / "cplugs" / UUID_CLOCK
    (data_clock / "files").mkdir(parents=True)
    (data_clock / "files" / "note.txt").write_text("kept")
    other_uuid = "fedcba9876543210fedcba9876543210"
    data_other = state / "cplugs" / other_uuid
    (data_other / "files").mkdir(parents=True)
    (data_other / "files" / "note.txt").write_text("other")

    real = os.rename
    calls: List[str] = []

    def flaky(src, dst):
        calls.append(str(dst))
        if len(calls) == 3:
            raise OSError("disk says no")
        real(src, dst)

    moves = plugin_layout.plan_moves(state)
    monkeypatch.setattr(plugin_layout.os, "rename", flaky)
    with pytest.raises(plugin_layout.LayoutMoveFailed):
        plugin_layout.apply_moves(moves, state / "journal.json")
    monkeypatch.undo()
    assert (state / "cplug-code" / "clock" / "main.py").is_file()
    assert (data_clock / "files" / "note.txt").read_text() == "kept"
    assert not (state / "plugins").exists()

    plugin_layout.apply_moves(plugin_layout.plan_moves(state), state / "journal.json")
    assert (state / "plugins" / "clock" / "main.py").is_file()
    assert (state / "plugin-data" / UUID_CLOCK / "files" / "note.txt").read_text() == "kept"


def test_the_deciding_folder_and_the_watch_follow_the_new_code_root(tmp_path):
    state = tmp_path / "support"
    state.mkdir()
    registry_boot.run(state, retired=lambda: None)
    (state / "plugins" / "clock").mkdir(parents=True)
    assert install_folder.deciding_folder(state, "acme/clock") == state / "plugins" / "clock"
    live = SimpleNamespace(state_dir=state, installed_rows=lambda: [SimpleNamespace(kind="cplug", source_index_url="x", item_id="acme/clock")])
    assert folder_watch.FolderWatch(live)._wanted() == {state / "plugins"}
    assert registry_store.plugins_dir(state) == state / "plugins"


def test_the_sidecar_registry_reads_code_from_the_new_root(tmp_path):
    state = tmp_path / "support"
    state.mkdir()
    registry_boot.run(state, retired=lambda: None)
    registry = sidecar_registry.SidecarRegistry(state, lambda: [])
    assert registry.code_root_of("clock") == state / "plugins" / "clock"
