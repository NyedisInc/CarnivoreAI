
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.core.crate_import.env import StoreHome
from src.core.inventory import plugin_stores
from src.cplugs.host import identity, registry_boot
from src.cplugs.sdk.crate_import import plugin_homes_of
from tests.python.cplugs.crate.test_plugin_data import manifest_with
from tests.python.cplugs.test_registry_migration_full_tuple import Alerts
from tests.python.crate_import.test_import_boards import BOARDS, KEEP, MEMO, PLUGIN, export_rig
from tests.python.crate_import.test_import_same_path import run
from tests.python.crate_import.test_import_work_side import target_install
from tests.python.inventory.world import UUID_A


def installed_target(tmp_path: Path, crate):  # noqa: ANN001, ANN201
    install = target_install(tmp_path, crate)
    record = identity.register_install(install.state, PLUGIN, "acme/synth", frozenset())
    old = install.state / "cplugs" / record.uuid / "keep"
    old.mkdir(parents=True)
    (old / "already-here.txt").write_text("a local note\n")
    return install, record


def locations_for(install, crate):  # noqa: ANN001, ANN201
    return replace(crate.world.locations, state_dir=install.state, plugin_manifests=(manifest_with([BOARDS, MEMO, KEEP]),),
                   plugin_settings={PLUGIN: {}}, plugin_enabled={PLUGIN: True})


def homes_for(install, crate):  # noqa: ANN001, ANN201
    stores = {(s.plugin_id, s.decl.id): s for s in plugin_stores.declared_stores(locations_for(install, crate))}
    return lambda plugin, data: StoreHome(root=stores[(plugin, data)].location, purge="") if (plugin, data) in stores else None


def test_a_crate_exported_before_the_migration_imports_into_the_new_data_folder(tmp_path):
    crate = export_rig(tmp_path)
    install, record = installed_target(tmp_path, crate)
    assert homes_for(install, crate)(PLUGIN, "keep").root == install.state / "cplugs" / record.uuid / "keep"
    assert registry_boot.run(install.state, retired=lambda: None, alert=Alerts()).action == registry_boot.A_MIGRATED
    new = install.state / "plugin-data" / record.uuid / "keep"
    assert (new / "already-here.txt").read_text() == "a local note\n" and not (install.state / "cplugs" / record.uuid).exists()
    homes = homes_for(install, crate)
    assert homes(PLUGIN, "keep").root == new
    env = replace(install.env, plugin_homes=lambda plugin, data: homes(plugin, data) if data == "keep" else None)
    receipt = run(crate, replace(install, env=env))
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    assert (new / f"{UUID_A}.txt").read_text() == "the crate's note\n"
    assert plugin_homes_of(locations_for(install, crate))(PLUGIN, "keep") is None
    assert (new / "already-here.txt").read_text() == "a local note\n"
    assert not (install.state / "cplugs" / record.uuid).exists()


def test_a_feature_keeps_its_cplugs_folder_for_the_same_import(tmp_path):
    crate = export_rig(tmp_path)
    install = target_install(tmp_path, crate)
    assert homes_for(install, crate)(PLUGIN, "keep").root == install.state / "cplugs" / PLUGIN / "keep"
