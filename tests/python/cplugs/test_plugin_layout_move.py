
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from src.core import plugin_layout
from src.cplugs.host import folder_watch, identity, install_folder, registry_boot, registry_files, registry_migration, sidecar_registry, sideload
from tests.python.cplugs import registry_world as W
from tests.python.cplugs.test_registry_migration_full_tuple import Alerts, boot


def tree(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_text() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_lookup_answers_the_old_place_until_only_the_old_place_exists_no_more(tmp_path):
    state = tmp_path
    assert plugin_layout.code_root(state, "clock") == state / "plugins" / "clock"
    (state / "cplug-code" / "clock").mkdir(parents=True)
    assert plugin_layout.code_root(state, "clock") == state / "cplug-code" / "clock"
    (state / "plugins" / "clock").mkdir(parents=True)
    assert plugin_layout.code_root(state, "clock") == state / "plugins" / "clock"
    key = W.UUID_CLOCK
    assert plugin_layout.data_root(state, key) == state / "plugin-data" / key
    (state / "cplugs" / key).mkdir(parents=True)
    assert plugin_layout.data_root(state, key) == state / "cplugs" / key
    (state / "plugin-data" / key).mkdir(parents=True)
    assert plugin_layout.data_root(state, key) == state / "plugin-data" / key
    assert plugin_layout.data_root(state, "huddle") == state / "cplugs" / "huddle"


def test_the_migration_moves_code_and_data_by_rename_and_nothing_is_copied(tmp_path):
    w = W.support(tmp_path)
    inodes = {p: p.stat().st_ino for p in [w.state / "cplug-code", *w.data.values()]}
    contents = {u: tree(f) for u, f in w.data.items()}
    code_tree = tree(w.state / "cplug-code")
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    assert not (w.state / "cplug-code").exists() and tree(w.state / "plugins") == code_tree
    assert (w.state / "plugins").stat().st_ino == inodes[w.state / "cplug-code"]
    for uuid, folder in w.data.items():
        moved = w.state / "plugin-data" / uuid
        assert not folder.exists() and tree(moved) == contents[uuid] and moved.stat().st_ino == inodes[folder]
    assert identity.data_dir(w.state, W.UUID_CLOCK) == w.state / "plugin-data" / W.UUID_CLOCK
    assert sideload.code_root_of(w.state, "clock") == w.state / "plugins" / "clock"


def test_a_feature_folder_and_the_host_files_stay_where_they_are(tmp_path):
    w = W.support(tmp_path)
    (w.state / "cplugs" / "huddle" / "files").mkdir(parents=True)
    (w.state / "cplugs" / "profiles").mkdir()
    boot(w.state, Alerts())
    assert (w.state / "cplugs" / "huddle" / "files").is_dir() and (w.state / "cplugs" / "profiles").is_dir()
    assert (registry_files.cplugs_dir(w.state) / "plugins.json").is_file()


def test_a_failed_move_undoes_every_rename_and_the_migration_refuses(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    before = {u: tree(f) for u, f in w.data.items()}
    real = os.rename
    calls: List[str] = []

    def flaky(src, dst):
        calls.append(str(dst))
        if len(calls) == 3:
            raise OSError("disk says no")
        real(src, dst)

    monkeypatch.setattr(plugin_layout.os, "rename", flaky)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_REFUSED and "layout_move_failed" in outcome.detail
    assert (w.state / "cplug-code" / "clock").is_dir() and not (w.state / "plugins").exists()
    assert {u: tree(f) for u, f in w.data.items()} == before and not any((w.state / "plugin-data" / u).exists() for u in w.data)
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0]) is False
    assert alerts.rows[0]["params"]["code"] == "layout_move_failed"
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    assert (w.state / "plugins" / "clock").is_dir() and (w.state / "plugin-data" / W.UUID_CLOCK).is_dir()


def test_a_registry_write_failure_after_the_moves_puts_the_folders_back(tmp_path, monkeypatch):
    w = W.support(tmp_path)

    def broken(path, document):
        raise OSError("no space")

    monkeypatch.setattr(registry_files, "write_registry", broken)
    outcome = registry_migration.migrate(w.state, retired=lambda: None)
    monkeypatch.undo()
    assert outcome.outcome == registry_migration.OUTCOME_REFUSED and outcome.refusal.code == "write_failed"
    assert (w.state / "cplug-code").is_dir() and not (w.state / "plugins").exists()
    assert all(f.is_dir() for f in w.data.values()) and not (w.state / "plugin-data" / W.UUID_CLOCK).exists()


def test_a_move_across_volumes_is_refused_before_anything_moves(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    monkeypatch.setattr(plugin_layout, "_same_volume", lambda moves: False)
    outcome = registry_migration.migrate(w.state, retired=lambda: None)
    monkeypatch.undo()
    assert outcome.refusal.code == "layout_move_failed" and "different volumes" in str(outcome.refusal)
    assert (w.state / "cplug-code").is_dir() and not (w.state / "plugins").exists()


def test_a_destination_that_already_exists_is_never_merged(tmp_path):
    w = W.support(tmp_path)
    (w.state / "plugin-data" / W.UUID_CLOCK).mkdir(parents=True)
    with pytest.raises(plugin_layout.LayoutMoveFailed):
        plugin_layout.plan_moves(w.state)
    outcome = registry_migration.migrate(w.state, retired=lambda: None)
    assert outcome.refusal.code == "layout_move_failed" and (w.data[W.UUID_CLOCK] / "files" / "note.txt").is_file()


def test_a_partly_moved_tree_finishes_on_the_next_boot(tmp_path):
    w = W.support(tmp_path)
    os.rename(w.state / "cplug-code", w.state / "plugins")
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    assert (w.state / "plugins" / "clock").is_dir() and all((w.state / "plugin-data" / u).is_dir() for u in w.data)


def test_the_deciding_folder_and_the_watch_follow_the_new_code_root(tmp_path):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    assert install_folder.deciding_folder(w.state, "acme/clock") == w.state / "plugins" / "clock"
    assert install_folder.deciding_folder(w.state, "local/myclock") == w.source
    live = SimpleNamespace(state_dir=w.state, installed_rows=lambda: [SimpleNamespace(kind="cplug", source_index_url="x", item_id="acme/clock")])
    assert folder_watch.FolderWatch(live)._wanted() == {w.state / "plugins"}


def test_the_sidecar_registry_reads_code_from_the_new_root(tmp_path):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    registry = sidecar_registry.SidecarRegistry(w.state, lambda: [])
    assert registry.code_root_of("clock") == w.state / "plugins" / "clock"
