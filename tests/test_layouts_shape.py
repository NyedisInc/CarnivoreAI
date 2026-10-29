
from __future__ import annotations

import pytest

from tests.layouts_helpers import grid, row

# ruff: noqa: E402
from src.core.layouts import shape as rules


def test_members_are_every_displayed_tab_in_reading_order():
    shape = rules.validate(grid(row(5), "browser:abc", row(2),
                                groups={row(5): [row(5), row(9)]}))
    assert rules.member_row_ids(shape) == [5, 9, 2]


def test_a_group_key_no_longer_among_its_tabs_is_not_a_member():
    shape = rules.validate(grid(row(5), row(2), groups={row(5): [row(9)]}))
    assert rules.member_row_ids(shape) == [9, 2]


def test_with_no_grid_every_group_counts():
    shape = rules.validate({"layout": None, "groups": {row(1): {"tabs": [row(1), row(3)]}}})
    assert rules.member_row_ids(shape) == [1, 3]


def test_the_primary_sentinel_is_refused_and_an_app_id_is_unresolved():
    with pytest.raises(rules.ShapeInvalid):
        rules.member_row_ids(rules.validate(grid("terminal:@primary", row(1))))
    with pytest.raises(rules.ShapeUnresolved) as caught:
        rules.member_row_ids(rules.validate(grid("terminal:ses_abc", row(1))))
    assert caught.value.slots == ["terminal:ses_abc"]


def test_the_primary_slot_may_hold_row_tabs():
    shape = rules.validate(grid("terminal:@primary", groups={"terminal:@primary": [row(1), row(2)]}))
    assert rules.member_row_ids(shape) == [1, 2]


def test_the_per_session_bounds_apply():
    with pytest.raises(rules.ShapeInvalid):
        rules.validate({"layout": {"v": 6, "rows": []}, "groups": {}})
    with pytest.raises(rules.ShapeInvalid):
        rules.validate({"layout": None, "groups": {"bad id": {"tabs": []}}})
    with pytest.raises(rules.ShapeInvalid):
        rules.validate({"layout": None, "groups": {}, "extra": 1})


def test_add_appends_a_tab_to_the_first_component_and_is_idempotent():
    shape = rules.validate(grid(row(1), row(2)))
    added = rules.with_member_added(shape, 7)
    assert added["groups"][row(1)] == {"tabs": [row(1), row(7)]}
    assert added["layout"] == shape["layout"]
    assert rules.member_row_ids(added) == [1, 7, 2]
    assert rules.with_member_added(added, 7) is added
    assert shape["groups"] == {}


def test_remove_a_tab_leaves_the_grid_alone():
    shape = rules.validate(grid(row(1), row(2), groups={row(1): [row(1), row(7)]}))
    out, was = rules.with_member_removed(shape, 1)
    assert was and out["groups"][row(1)] == {"tabs": [row(7)]}
    assert out["layout"] == shape["layout"]
    assert rules.member_row_ids(out) == [7, 2]


def test_remove_a_lone_cell_drops_it_and_rescales_the_row():
    shape = rules.validate(grid(row(1), row(2), row(3)))
    out, was = rules.with_member_removed(shape, 2)
    slots = out["layout"]["rows"][0]["slots"]
    assert was and [s["id"] for s in slots] == [row(1), row(3)]
    assert sum(s["fr"] for s in slots) == pytest.approx(1.0)
    assert rules.member_row_ids(rules.validate(out)) == [1, 3]


def test_remove_drops_an_emptied_row_and_its_span_reservations():
    shape = {
        "layout": {"v": 6, "hidden": [], "heroCollapsed": False, "collapsed": [row(2)],
                   "rows": [
                       {"id": "r1", "kind": "flex", "size": 0.5,
                        "slots": [{"id": row(1), "fr": 0.5}, {"id": row(2), "fr": 0.5, "span": 2}]},
                       {"id": "r2", "kind": "flex", "size": 0.25,
                        "slots": [{"id": row(3), "fr": 1}], "reserved": [{"of": row(2), "at": 1}]},
                       {"id": "r3", "kind": "flex", "size": 0.25, "slots": [{"id": row(4), "fr": 1}]},
                   ]},
        "groups": {},
    }
    out, _ = rules.with_member_removed(rules.validate(shape), 4)
    assert [r["id"] for r in out["layout"]["rows"]] == ["r1", "r2"]
    assert sum(r["size"] for r in out["layout"]["rows"]) == pytest.approx(1.0)
    out2, _ = rules.with_member_removed(rules.validate(shape), 2)
    assert "reserved" not in out2["layout"]["rows"][1]
    assert out2["layout"]["collapsed"] == []


def test_remove_a_non_member_reports_it():
    shape = rules.validate(grid(row(1), row(2)))
    out, was = rules.with_member_removed(shape, 9)
    assert not was and out is shape


def test_a_layout_carries_page_tabs_that_are_not_members():
    page = "page:0123456789abcdef"
    shape = rules.validate({"layout": None, "groups": {
        row(1): {"tabs": [row(1), page]}, "terminal:pg-0123456789abcdef": {"tabs": [page]}}})
    assert rules.member_row_ids(shape) == [1]
    assert rules.page_tab_ids(shape) == [page]
    assert rules.has_enough_members([1], shape)
    assert not rules.has_enough_members([1], rules.validate(grid(row(1))))
    assert not rules.has_enough_members([], shape)


def test_a_widget_tab_is_carried_but_is_not_a_member_nor_a_page():
    widget = "widget:core.tasks"
    shape = rules.validate({"layout": None, "groups": {row(1): {"tabs": [row(1), widget]}}})
    assert rules.member_row_ids(shape) == [1]
    assert rules.displayed_terminals(shape) == [row(1)]
    assert rules.page_tab_ids(shape) == []
    assert shape["groups"][row(1)]["tabs"] == [row(1), widget]
    assert not rules.has_enough_members([1], shape)
