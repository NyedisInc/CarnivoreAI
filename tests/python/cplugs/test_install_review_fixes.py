
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from src.api import catalog_cplug_gates
from src.plugins.host import identity, sideload, sideload_git, sideload_routes
from src.plugins.host.sidecar_registry import SidecarRegistry
from tests.python.cplugs.test_cplug_sidecar_identity import _install_code

TORN = b'{"clock": {"url": '
KEY_A, KEY_B = "5F52A0A0A0A0A0A0", "9C11B1B1B1B1B1B1"


def _request(state: Path) -> Any:
    reader = SimpleNamespace(state_dir=lambda: state)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(settings_reader=reader))))


def test_sync_folder_refuses_a_source_whose_realpath_leaves_its_root(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    source = checkout / "sub"
    source.symlink_to(elsewhere, target_is_directory=True)
    live = SimpleNamespace(state_dir=tmp_path / "state")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(sideload_routes.sync_folder(live, source, None, root=checkout))
    assert caught.value.detail["code"] == "source_outside_root"


def test_contained_accepts_a_path_inside_and_refuses_a_link_out(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    assert sideload.contained(root / "a", root) == Path(os.path.realpath(root / "a"))
    (tmp_path / "out").mkdir()
    (root / "hop").symlink_to(tmp_path / "out", target_is_directory=True)
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload.contained(root / "hop", root)
    assert caught.value.code == "source_outside_root"


def test_registry_skips_a_code_folder_that_resolves_outside_cplug_code(tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "plugins").mkdir(parents=True)
    identity.register_install(state, "clock", "acme/clock", frozenset())
    row = SimpleNamespace(item_id="acme/clock", kind="cplug", source_index_url="x", publisher_key_id="", install_id="i")
    real = _install_code(tmp_path / "elsewhere")
    registry = SidecarRegistry(state, lambda: [row])
    (state / "plugins" / "clock").symlink_to(real, target_is_directory=True)
    assert registry._load_one(row) is None
    (state / "plugins" / "clock").unlink()
    _install_code(state)
    assert registry._load_one(row) is not None


def test_failed_install_after_a_key_mismatch_swap_restores_the_old_row(tmp_path: Path) -> None:
    item = SimpleNamespace(id="acme/clock")
    old = identity.register_install(tmp_path, "clock", item.id, frozenset(), publisher_key_id=KEY_A)
    request = _request(tmp_path)
    reservation = catalog_cplug_gates.reserve_install(request, item, KEY_B)
    assert identity.lookup(tmp_path, "clock").uuid != old.uuid
    catalog_cplug_gates.release_reservation(request, item, reservation)
    assert identity.lookup(tmp_path, "clock") == old


def test_failed_first_install_still_frees_the_name(tmp_path: Path) -> None:
    item = SimpleNamespace(id="acme/clock")
    request = _request(tmp_path)
    reservation = catalog_cplug_gates.reserve_install(request, item, KEY_A)
    catalog_cplug_gates.release_reservation(request, item, reservation)
    assert identity.lookup(tmp_path, "clock") is None


def test_failed_reinstall_with_the_same_key_leaves_the_row(tmp_path: Path) -> None:
    item = SimpleNamespace(id="acme/clock")
    old = identity.register_install(tmp_path, "clock", item.id, frozenset(), publisher_key_id=KEY_A)
    request = _request(tmp_path)
    reservation = catalog_cplug_gates.reserve_install(request, item, KEY_A)
    catalog_cplug_gates.release_reservation(request, item, reservation)
    assert identity.lookup(tmp_path, "clock") == old


@pytest.mark.parametrize("writer", ["record", "forget"])
def test_git_sideload_record_is_never_written_over_an_unreadable_file(tmp_path: Path, writer: str) -> None:
    path = tmp_path / "cplugs" / sideload_git.RECORD_FILE
    path.parent.mkdir(parents=True)
    path.write_bytes(TORN)
    with pytest.raises(sideload.SideloadRefused) as caught:
        if writer == "record":
            sideload_git.record(tmp_path, "other", "https://h/x", None, (), "abc")
        else:
            sideload_git.forget(tmp_path, "clock")
    assert caught.value.code == "sideload_unreadable"
    assert path.read_bytes() == TORN


def test_git_sideload_records_reader_still_defaults(tmp_path: Path) -> None:
    path = tmp_path / "cplugs" / sideload_git.RECORD_FILE
    path.parent.mkdir(parents=True)
    path.write_bytes(TORN)
    assert sideload_git.records(tmp_path) == {}
