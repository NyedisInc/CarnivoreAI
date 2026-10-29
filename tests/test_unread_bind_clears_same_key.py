
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import unread_identity
from src.core.unread_store import UnreadStore




class FakeListing:

    def __init__(self, rows, ok: bool = True) -> None:
        self.ok = ok
        self.sessions = rows


def listing_of(*pairs, ok: bool = True) -> FakeListing:
    return FakeListing(
        [{"name": n, "created_at_epoch": e} for n, e in pairs], ok=ok
    )


@pytest.fixture()
def store(tmp_path: Path) -> UnreadStore:
    return UnreadStore(tmp_path / "unread_state.json")


NAME = "cloude_Fantasy_Hockey_2026"
OTHER = "cloude_Hirschfeld"
EPOCH = 1788444912
OTHER_EPOCH = 1788463221




def test_manual_mark_then_bind_then_list_reads_read(store: UnreadStore) -> None:
    cache: dict[str, int] = {}
    probe = lambda: listing_of((NAME, EPOCH), (OTHER, OTHER_EPOCH))

    store.set_flag(
        NAME, "manual", True,
        epoch=unread_identity.resolve_epoch(cache, NAME, probe),
    )
    assert store.is_unread(NAME, unread_identity.resolve_epoch(cache, NAME, probe))

    store.clear(NAME, unread_identity.resolve_epoch(cache, NAME, probe))

    assert store.is_unread(NAME, unread_identity.resolve_epoch(cache, NAME, probe)) is False


def test_stop_sets_it_again_and_a_second_bind_clears_it(store: UnreadStore) -> None:
    cache: dict[str, int] = {}
    probe = lambda: listing_of((NAME, EPOCH))
    epoch = lambda: unread_identity.resolve_epoch(cache, NAME, probe)

    store.set_flag(NAME, "auto", True, epoch=epoch())
    assert store.is_unread(NAME, epoch()) is True

    store.clear(NAME, epoch())
    assert store.is_unread(NAME, epoch()) is False

    store.clear(NAME, epoch())
    store.clear(NAME, epoch())
    assert store.is_unread(NAME, epoch()) is False


def test_a_bind_clears_both_sub_flags_not_just_one(store: UnreadStore) -> None:
    cache: dict[str, int] = {}
    probe = lambda: listing_of((NAME, EPOCH))
    epoch = unread_identity.resolve_epoch(cache, NAME, probe)

    store.set_flag(NAME, "auto", True, epoch=epoch)
    store.set_flag(NAME, "manual", True, epoch=epoch)
    entry = store.raw[UnreadStore.compose_key(NAME, EPOCH)]
    assert entry == {"auto": True, "manual": True}

    store.clear(NAME, epoch)
    assert store.is_unread(NAME, epoch) is False
    assert UnreadStore.compose_key(NAME, EPOCH) not in store.raw




def test_set_and_clear_agree_with_an_empty_cache_after_a_restart() -> None:
    probe_calls = []

    def probe():
        probe_calls.append(1)
        return listing_of((NAME, EPOCH))

    cold: dict[str, int] = {}
    set_epoch = unread_identity.resolve_epoch(cold, NAME, probe)
    clear_epoch = unread_identity.resolve_epoch(cold, NAME, probe)

    assert set_epoch == clear_epoch == EPOCH
    assert UnreadStore.compose_key(NAME, set_epoch) == f"{NAME}@{EPOCH}"
    assert len(probe_calls) == 1


def test_the_row_epoch_and_the_resolver_compose_one_key() -> None:
    write_cache: dict[str, int] = {}
    written = unread_identity.resolve_epoch(
        write_cache, NAME, lambda: listing_of((NAME, EPOCH))
    )

    read_cache: dict[str, int] = {}
    row = {"name": NAME, "created_at_epoch": EPOCH}
    read = unread_identity.remember(
        read_cache, NAME, unread_identity.epoch_of_row(row)
    ) or unread_identity.resolve_epoch(read_cache, NAME)

    assert UnreadStore.compose_key(NAME, written) == UnreadStore.compose_key(NAME, read)


def test_an_unmeasurable_epoch_degrades_to_the_legacy_bare_name() -> None:
    cache: dict[str, int] = {}
    assert unread_identity.resolve_epoch(cache, NAME, lambda: listing_of(ok=False)) is None
    assert UnreadStore.compose_key(NAME, None) == NAME


def test_a_failed_probe_does_not_wipe_the_memo() -> None:
    cache = {NAME: EPOCH}
    unread_identity.remember_listing(cache, listing_of(ok=False))
    assert cache == {NAME: EPOCH}


def test_a_reused_tmux_name_is_re_measured_by_the_next_listing() -> None:
    cache: dict[str, int] = {}
    unread_identity.remember_listing(cache, listing_of((NAME, EPOCH)))
    assert cache[NAME] == EPOCH
    unread_identity.remember_listing(cache, listing_of((NAME, EPOCH + 9999)))
    assert cache[NAME] == EPOCH + 9999


def test_epoch_of_row_coerces_text_and_refuses_junk() -> None:
    assert unread_identity.epoch_of_row({"created_at_epoch": "17"}) == 17
    assert unread_identity.epoch_of_row({"created_at_epoch": None}) is None
    assert unread_identity.epoch_of_row({"created_at_epoch": "not-a-number"}) is None
    assert unread_identity.epoch_of_row({}) is None
    assert unread_identity.epoch_of_row(None) is None




def test_a_bind_for_a_different_session_leaves_this_flag_alone(
    store: UnreadStore,
) -> None:
    cache: dict[str, int] = {}
    probe = lambda: listing_of((NAME, EPOCH), (OTHER, OTHER_EPOCH))

    store.set_flag(NAME, "manual", True, epoch=unread_identity.resolve_epoch(cache, NAME, probe))
    store.set_flag(OTHER, "auto", True, epoch=unread_identity.resolve_epoch(cache, OTHER, probe))

    store.clear(OTHER, unread_identity.resolve_epoch(cache, OTHER, probe))

    assert store.is_unread(OTHER, unread_identity.resolve_epoch(cache, OTHER, probe)) is False
    assert store.is_unread(NAME, unread_identity.resolve_epoch(cache, NAME, probe)) is True


def test_a_bind_on_a_different_INSTANCE_of_the_same_name_does_not_clear(
    store: UnreadStore,
) -> None:
    store.set_flag(NAME, "manual", True, epoch=EPOCH)
    store.clear(NAME, EPOCH + 5000)
    assert store.is_unread(NAME, EPOCH) is True


def test_the_clear_writes_only_this_instances_keys(tmp_path: Path) -> None:
    path = tmp_path / "unread_state.json"
    store = UnreadStore(path)
    store.set_flag(NAME, "manual", True, epoch=EPOCH)
    store.set_flag(OTHER, "auto", True, epoch=OTHER_EPOCH)
    store.set_flag("cloude_daily-briefing", "auto", True, epoch=None)

    store.clear(NAME, EPOCH)

    on_disk = json.loads(path.read_text())
    assert set(on_disk) == {
        UnreadStore.compose_key(OTHER, OTHER_EPOCH),
        "cloude_daily-briefing",
    }
