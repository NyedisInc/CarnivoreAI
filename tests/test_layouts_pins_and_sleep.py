
from __future__ import annotations

from contextlib import closing

import pytest
from pydantic import ValidationError

from tests.layouts_helpers import grid, row
from tests.test_auto_sleep_sleeper import _add, _config, _run, world  # noqa: F401, F811

# ruff: noqa: E402
from src.core.layouts import lease as layouts_lease
from src.core.layouts import store as store
from src.core.db import connect, db_path_for
from src.core.layouts.lease import LeaseBook
from src.core.ui_preferences import DrawerArrangement

PIN = "layout:0f6c1d2e-3a4b-4c5d-8e9f-001122334455"


def test_pinned_accepts_layout_pins_beside_session_uuids():
    value = DrawerArrangement.model_validate(
        {"pinned": ["row-uuid-1", PIN, PIN], "collapsed": ["layouts", "pinned"]})
    assert value.pinned == ["row-uuid-1", PIN]
    assert value.collapsed == ["layouts", "pinned"]
    for bad in ({"order": [PIN]}, {"bands": {"rogue": [PIN]}}, {"bands": {"layouts": []}},
                {"pinned": ["layout:"]}, {"pinned": ["layout:has space"]},
                {"pinned": ["browser:abc"]}, {"collapsed": ["layout"]}):
        with pytest.raises(ValidationError):
            DrawerArrangement.model_validate(bad)


def _layout_of(w, *row_ids, name="pair"):
    with closing(connect(db_path_for(w.state), create=False)) as conn:
        return store.create_layout(conn, name, grid(*[row(r) for r in row_ids])).layout.layout_uuid


def _row_id(w, sid):
    return w.manager.infos[sid].session_row_id


def test_a_pinned_layout_does_not_keep_its_members_awake(world):
    s1, u1 = _add(world, 1)
    s2, _ = _add(world, 2, idle_minutes=1)
    uuid = _layout_of(world, _row_id(world, s1), _row_id(world, s2))
    _config(world, ui_preferences={"revision": 1, "values": {
        "drawer_arrangement": {"v": 1, "pinned": [f"layout:{uuid}"]}}})
    assert _run(world) == [u1]


def test_an_active_layout_keeps_its_members_awake_until_the_lease_expires(world, monkeypatch):
    now = [1000.0]
    book = LeaseBook(clock=lambda: now[0])
    monkeypatch.setattr(layouts_lease, "LEASES", book)
    s1, u1 = _add(world, 1)
    s2, _ = _add(world, 2, idle_minutes=1)
    uuid = _layout_of(world, _row_id(world, s1), _row_id(world, s2))
    book.renew(uuid)
    now[0] += 179
    assert _run(world) == []
    now[0] += 2
    assert _run(world) == [u1]


def test_a_lease_on_another_layout_protects_nothing_here(world, monkeypatch):
    book = LeaseBook()
    monkeypatch.setattr(layouts_lease, "LEASES", book)
    s1, u1 = _add(world, 1)
    s2, _ = _add(world, 2, idle_minutes=1)
    s3, _ = _add(world, 3, idle_minutes=1)
    _layout_of(world, _row_id(world, s1), _row_id(world, s2))
    other = _layout_of(world, _row_id(world, s2), _row_id(world, s3), name="other")
    book.renew(other)
    assert _run(world) == [u1]


def test_the_lease_book_is_bounded_and_releases():
    book = LeaseBook()
    for i in range(layouts_lease.MAX_LEASES + 5):
        book.renew(f"u{i}")
    active = book.active()
    assert len(active) == layouts_lease.MAX_LEASES and "u0" not in active
    book.release(f"u{layouts_lease.MAX_LEASES + 4}")
    assert f"u{layouts_lease.MAX_LEASES + 4}" not in book.active()
