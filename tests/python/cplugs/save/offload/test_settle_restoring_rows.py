
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.plugins.save.offload import constants as C
from src.plugins.save.offload import ledger as ledger_mod
from src.plugins.save.offload import offload_routes, reconcile
from src.plugins.save.offload.move import holding_root
from src.plugins.save.vault import restore
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, ledger_of
from tests.python.cplugs.save.vault_helpers import World

CONV = conv_id(1)


@pytest.fixture
def cut_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = build_fleet(tmp_path, monkeypatch, 1)
    offload_routes._run("S1", False)
    folder = holding_root(world.state) / CONV
    world.held_aside = world.state.parent / "held-aside"  # type: ignore[attr-defined]
    shutil.move(str(folder), str(world.held_aside))  # type: ignore[attr-defined]
    ledger_of(world).update(CONV, state=C.STATE_RESTORING, holding_dir="")
    return world


def settle(world: World) -> dict:
    return reconcile.reconcile(world.vault, ledger_of(world), offload_routes.claude_homes(world.sources.claude_roots))


def put_back(world: World, count: int) -> None:
    point = world.vault.manifests.read(CONV, ledger_of(world).get(CONV).point_id)  # type: ignore[union-attr]
    destination = restore.homes_destination(offload_routes.claude_homes(world.sources.claude_roots))
    for file in point.files[:count]:
        dest = destination(file)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(world.held_aside / file.home / file.rel, dest)  # type: ignore[attr-defined]


def test_a_cut_off_restore_with_nothing_on_disk_stays_offloaded(cut_off: World) -> None:
    assert settle(cut_off) == {CONV: reconcile.OUTCOME_OFFLOADED}
    assert ledger_of(cut_off).get(CONV).state == C.STATE_OFFLOADED  # type: ignore[union-attr]


def test_a_cut_off_restore_with_some_files_back_stays_offloaded(cut_off: World) -> None:
    put_back(cut_off, 1)
    assert settle(cut_off) == {CONV: reconcile.OUTCOME_OFFLOADED}


def test_a_cut_off_restore_with_every_file_back_is_dropped(cut_off: World) -> None:
    put_back(cut_off, len(cut_off.vault.manifests.read(CONV, ledger_of(cut_off).get(CONV).point_id).files))  # type: ignore[union-attr]
    assert settle(cut_off) == {CONV: reconcile.OUTCOME_DROPPED} and ledger_of(cut_off).read() == {}


def test_the_ledger_refuses_a_field_an_entry_does_not_have(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    offload_routes._run("S1", False)
    led = ledger_of(world)
    before = led.path.read_bytes()
    with pytest.raises(ValueError) as caught:
        led.update(CONV, sate=C.STATE_FAILED)
    assert isinstance(caught.value, ledger_mod.UnknownField) and "sate" in str(caught.value)
    assert led.path.read_bytes() == before
    assert led.update(CONV, error="kept").error == "kept"


def test_a_cut_off_restore_with_a_different_file_in_place_stays_offloaded(cut_off: World) -> None:
    point = cut_off.vault.manifests.read(CONV, ledger_of(cut_off).get(CONV).point_id)  # type: ignore[union-attr]
    put_back(cut_off, len(point.files))
    other = restore.homes_destination(offload_routes.claude_homes(cut_off.sources.claude_roots))(point.main())  # type: ignore[arg-type]
    other.write_bytes(b'{"another":"conversation"}\n')
    assert settle(cut_off) == {CONV: reconcile.OUTCOME_OFFLOADED}
    assert ledger_of(cut_off).get(CONV).state == C.STATE_OFFLOADED  # type: ignore[union-attr]
