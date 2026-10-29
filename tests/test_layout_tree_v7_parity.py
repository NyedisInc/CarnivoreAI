
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.layouts import tree_v7 as tree
from src.core.layouts import shape as rules

FIXTURE = Path(__file__).parent / "fixtures" / "layout_v7_parity.json"
CASES: List[Dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
IDS = [case["name"] for case in CASES]


def _v6_slots(layout: Optional[Dict[str, Any]]) -> List[str]:
    if not layout:
        return []
    return [s["id"] for r in layout["rows"] for s in r.get("slots") or []]


def _v7_slots(layout: Optional[Dict[str, Any]]) -> List[str]:
    if not layout:
        return []
    return tree.leaves_of(layout["variants"]["wide"]["root"])


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= 1e-12
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def test_the_fixture_is_not_empty_and_carries_spans():
    assert len(CASES) >= 60
    spanning = [c for c in CASES if any(s.get("span", 1) >= 2 for r in c["v6"]["rows"] for s in r["slots"])]
    assert len(spanning) >= 10
    assert sum(len(c["drops"]) for c in CASES) >= 200


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_emitted_tree_passes_the_server_check(case):
    tree.check_layout(case["v7"])
    assert rules.validate({"layout": case["v7"], "groups": {}})["layout"] == case["v7"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_walk_matches_the_browser_and_v6_membership(case):
    v6, v7 = case["v6"], case["v7"]
    assert rules._grid_terminal_slots(v7) == case["terminalSlots"]
    assert set(rules._grid_terminal_slots(v6)) == set(rules._grid_terminal_slots(v7))
    assert set(_v6_slots(v6)) == set(_v7_slots(v7))
    if not any(s.get("span", 1) >= 2 for r in v6["rows"] for s in r["slots"]):
        assert rules._grid_terminal_slots(v6) == rules._grid_terminal_slots(v7)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_dropping_a_slot_matches_the_browser_and_v6(case):
    v6, v7 = case["v6"], case["v7"]
    for drop in case["drops"]:
        slot = drop["slot"]
        before = copy.deepcopy(v7)
        mine = rules._drop_slot(copy.deepcopy(v7), slot)
        assert v7 == before
        assert _same(mine, drop["v7"]), (case["name"], slot)
        if mine is not None:
            tree.check_layout(mine)
        old = rules._drop_slot(copy.deepcopy(v6), slot)
        assert (old is None) == (mine is None), (case["name"], slot)
        assert set(_v6_slots(old)) == set(_v7_slots(mine)) == set(_v6_slots(v6)) - {slot}


def test_membership_and_member_removal_read_a_v7_grid():
    two = {"t": "split", "id": "s1", "dir": "h", "unit": "fr", "sizes": [0.5, 0.5],
           "children": [{"t": "leaf", "id": "terminal:row:4"}, {"t": "leaf", "id": "terminal:row:7"}]}
    layout = {"v": 7, "variants": {"wide": {"root": two}}, "hidden": [], "collapsed": [],
              "heroCollapsed": False}
    shape = rules.validate({"layout": layout, "groups": {"terminal:row:7": {"tabs": ["terminal:row:7", "terminal:row:9"]}}})
    assert rules.member_row_ids(shape) == [4, 7, 9]
    out, was = rules.with_member_removed(shape, 4)
    assert was is True
    assert out["layout"]["variants"]["wide"]["root"] == {"t": "leaf", "id": "terminal:row:7"}
    assert rules.member_row_ids(out) == [7, 9]
    added = rules.with_member_added(out, 12)
    assert added["groups"]["terminal:row:7"]["tabs"] == ["terminal:row:7", "terminal:row:9", "terminal:row:12"]
    alone = {"layout": dict(layout, variants={"wide": {"root": {"t": "leaf", "id": "terminal:row:4"}}}),
             "groups": {}}
    gone, _ = rules.with_member_removed(rules.validate(alone), 4)
    assert gone["layout"] is None


LEAF = {"t": "leaf", "id": "terminal:row:1"}


def _doc(root: Any, **extra: Any) -> Dict[str, Any]:
    return {"v": 7, "variants": {"wide": {"root": root}}, "hidden": [], "collapsed": [],
            "heroCollapsed": False, **extra}


def _split(children: List[Any], **extra: Any) -> Dict[str, Any]:
    n = len(children)
    return {"t": "split", "id": "s1", "dir": "h", "unit": "fr", "sizes": [1 / n] * n,
            "children": children, **extra}


B = {"t": "leaf", "id": "terminal:row:2"}

REFUSALS = [
    ("malformed", []),
    ("version", {"v": 8}),
    ("unknown-field", _doc(LEAF, extra=1)),
    ("variants", dict(_doc(LEAF), variants={"wide": {"root": LEAF}, "narrow": {"root": LEAF}})),
    ("node", _doc({"t": "box"})),
    ("leaf-id", _doc({"t": "leaf", "id": "bad id!"})),
    ("duplicate-leaf", _doc(_split([LEAF, dict(LEAF)]))),
    ("split-id", _doc(_split([LEAF, B], id="x1"))),
    ("dir", _doc(_split([LEAF, B], dir="d"))),
    ("unit", _doc(dict(_split([LEAF, B]), unit="px", sizes=[100, 100]))),
    ("sizes", _doc(dict(_split([LEAF, B]), sizes=[0.5, 0.6]))),
    ("sizes", _doc(dict(_split([LEAF, B]), sizes=[1.0, 0]))),
    ("sizes", _doc(dict(_split([LEAF, B]), sizes=[1.0]))),
    ("single-child", _doc(_split([LEAF]))),
    ("same-dir", _doc(_split([LEAF, dict(_split([B, {"t": "leaf", "id": "terminal:row:3"}]), id="s2")]))),
    ("hidden", _doc(LEAF, hidden=["terminal:row:1"])),
    ("collapsed", _doc(LEAF, collapsed="terminal:row:1")),
    ("hero-collapsed", _doc(LEAF, heroCollapsed=None)),
    ("header-off", _doc(LEAF, headerOff="terminal:row:1")),
]


def test_the_header_tick_is_optional_and_carried():
    tree.check_layout(_doc(LEAF))
    two = _doc(_split([LEAF, B]), headerOff=["terminal:row:2"])
    tree.check_layout(two)
    assert tree.without_slot(two, "terminal:row:2")["headerOff"] == []
    assert tree.without_slot(two, "terminal:row:1")["headerOff"] == ["terminal:row:2"]


@pytest.mark.parametrize("refusal,layout", REFUSALS, ids=[r for r, _ in REFUSALS])
def test_each_structural_rule_refuses_by_name(refusal, layout):
    with pytest.raises(tree.TreeInvalid) as caught:
        tree.check_layout(layout)
    assert caught.value.refusal == refusal


def test_depth_and_node_bounds():
    node: Dict[str, Any] = {"t": "leaf", "id": "terminal:row:0"}
    for depth in range(tree.MAX_TREE_DEPTH):
        node = {"t": "split", "id": f"s{depth + 1}", "dir": "hv"[depth % 2], "unit": "fr",
                "sizes": [0.5, 0.5], "children": [node, {"t": "leaf", "id": f"terminal:row:{depth + 1}"}]}
    with pytest.raises(tree.TreeInvalid) as caught:
        tree.check_layout(_doc(node))
    assert caught.value.refusal == "depth"


def test_a_v7_grid_is_refused_by_the_shape_check_when_malformed():
    with pytest.raises(rules.ShapeInvalid):
        rules.validate({"layout": _doc(_split([LEAF])), "groups": {}})
    with pytest.raises(rules.ShapeInvalid):
        rules.validate({"layout": {"v": 7, "rows": [{"id": "r1"}]}, "groups": {}})
