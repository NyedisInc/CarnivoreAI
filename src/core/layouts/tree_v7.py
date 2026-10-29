
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set

SCHEMA_VERSION_V7 = 7

SIZE_CLASSES = ("wide",)

TERMINAL_PREFIX = "terminal:"

MAX_TREE_DEPTH = 16
MAX_TREE_NODES = 256
MAX_SPLIT_CHILDREN = 64

FR_TOLERANCE = 1e-6

SPLIT_ID_RE = re.compile(r"^s[1-9][0-9]*$")

LEAF_ID_RE = re.compile(r"^(?:[a-z][a-z0-9-]{0,39}|(?:terminal|browser):[A-Za-z0-9@._: -]{1,120}|[a-z][a-z0-9-]{0,31}\.[a-z][a-z0-9-]{0,31}:[A-Za-z0-9@._: -]{1,120}|analytics:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")

_LAYOUT_FIELDS = frozenset({"v", "variants", "hidden", "collapsed", "heroCollapsed", "headerOff"})
_VARIANT_FIELDS = frozenset({"root"})
_SPLIT_FIELDS = frozenset({"t", "id", "dir", "sizes", "unit", "children"})
_LEAF_FIELDS = frozenset({"t", "id"})


class TreeInvalid(ValueError):

    def __init__(self, refusal: str, detail: str) -> None:
        super().__init__(detail)
        self.refusal = refusal


def is_v7(layout: Any) -> bool:
    return isinstance(layout, dict) and layout.get("v") == SCHEMA_VERSION_V7


def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _only(node: Dict[str, Any], known: frozenset, what: str) -> None:
    for key in node:
        if key not in known:
            raise TreeInvalid("unknown-field", f"{what} carries an unknown field {key!r}")


def _check_tree(root: Any, seen_leaves: Set[str]) -> None:
    seen_splits: Set[str] = set()
    count = 0

    def visit(value: Any, depth: int, parent_dir: Optional[str]) -> None:
        nonlocal count
        count += 1
        if count > MAX_TREE_NODES:
            raise TreeInvalid("nodes", f"the tree holds more than {MAX_TREE_NODES} nodes")
        if depth > MAX_TREE_DEPTH:
            raise TreeInvalid("depth", f"the tree is deeper than {MAX_TREE_DEPTH}")
        if not isinstance(value, dict):
            raise TreeInvalid("node", "a node is not an object")
        kind = value.get("t")
        if kind == "leaf":
            _only(value, _LEAF_FIELDS, "a leaf")
            leaf = value.get("id")
            if not isinstance(leaf, str) or not LEAF_ID_RE.match(leaf):
                raise TreeInvalid("leaf-id", f"leaf id {leaf!r} is not a slot id")
            if leaf in seen_leaves:
                raise TreeInvalid("duplicate-leaf", f"slot {leaf!r} appears twice")
            seen_leaves.add(leaf)
            return
        if kind != "split":
            raise TreeInvalid("node", f"node type {kind!r} is neither leaf nor split")
        _only(value, _SPLIT_FIELDS, "a split")
        sid = value.get("id")
        if not isinstance(sid, str) or not SPLIT_ID_RE.match(sid) or sid in seen_splits:
            raise TreeInvalid("split-id", f"split id {sid!r} is not a unique s<number>")
        seen_splits.add(sid)
        direction = value.get("dir")
        if direction not in ("h", "v"):
            raise TreeInvalid("dir", f"split {sid!r} has direction {direction!r}")
        if value.get("unit") != "fr":
            raise TreeInvalid("unit", f"split {sid!r} is not fr, the only unit a terminal page uses")
        if direction == parent_dir:
            raise TreeInvalid("same-dir", f"split {sid!r} splits the same way as its parent")
        children = value.get("children")
        if not isinstance(children, list):
            raise TreeInvalid("children", f"split {sid!r} has no children list")
        if len(children) < 2:
            raise TreeInvalid("single-child" if len(children) == 1 else "children",
                              f"split {sid!r} holds {len(children)} children")
        if len(children) > MAX_SPLIT_CHILDREN:
            raise TreeInvalid("children", f"split {sid!r} holds more than {MAX_SPLIT_CHILDREN}")
        sizes = value.get("sizes")
        if not isinstance(sizes, list) or len(sizes) != len(children):
            raise TreeInvalid("sizes", f"split {sid!r} needs one size per child")
        if not all(_positive(one) for one in sizes):
            raise TreeInvalid("sizes", f"split {sid!r} has a size that is not a positive number")
        if abs(sum(float(one) for one in sizes) - 1) > FR_TOLERANCE:
            raise TreeInvalid("sizes", f"split {sid!r} fr sizes do not sum to 1")
        for child in children:
            visit(child, depth + 1, direction)

    visit(root, 1, None)


def _slot_list(raw: Any, refusal: str) -> List[str]:
    if not isinstance(raw, list):
        raise TreeInvalid(refusal, f"{refusal} is not a list")
    seen: Set[str] = set()
    for one in raw:
        if not isinstance(one, str) or not LEAF_ID_RE.match(one) or one in seen:
            raise TreeInvalid(refusal, f"{refusal} holds {one!r} badly or twice")
        seen.add(one)
    return list(raw)


def check_layout(layout: Any) -> None:
    if not isinstance(layout, dict):
        raise TreeInvalid("malformed", "the layout is not an object")
    if layout.get("v") != SCHEMA_VERSION_V7:
        raise TreeInvalid("version", "the layout is not version 7")
    _only(layout, _LAYOUT_FIELDS, "the layout")
    variants = layout.get("variants")
    if not isinstance(variants, dict) or set(variants) != set(SIZE_CLASSES):
        raise TreeInvalid("variants", f"variants must be exactly {list(SIZE_CLASSES)}")
    on_surface: Set[str] = set()
    for size in SIZE_CLASSES:
        variant = variants[size]
        if not isinstance(variant, dict):
            raise TreeInvalid("variants", f"variant {size!r} is not an object")
        _only(variant, _VARIANT_FIELDS, f"variant {size!r}")
        seen: Set[str] = set()
        _check_tree(variant.get("root"), seen)
        on_surface |= seen
    hidden = _slot_list(layout.get("hidden"), "hidden")
    placed = next((one for one in hidden if one in on_surface), None)
    if placed is not None:
        raise TreeInvalid("hidden", f"{placed!r} is both hidden and on the surface")
    _slot_list(layout.get("collapsed"), "collapsed")
    if not isinstance(layout.get("heroCollapsed"), bool):
        raise TreeInvalid("hero-collapsed", "heroCollapsed is not a boolean")
    if "headerOff" in layout:
        _slot_list(layout.get("headerOff"), "header-off")


def leaves_of(root: Dict[str, Any]) -> List[str]:
    if root.get("t") == "leaf":
        return [root["id"]]
    out: List[str] = []
    for child in root.get("children") or []:
        out.extend(leaves_of(child))
    return out


def normalize_shares(sizes: List[float]) -> List[float]:
    total = 0.0
    for one in sizes:
        if _positive(one):
            total += one
    if total <= 0:
        return [1 / len(sizes) for _ in sizes]
    return [(one / total if _positive(one) else 0) for one in sizes]


def canonicalize(root: Dict[str, Any]) -> Dict[str, Any]:
    if root.get("t") == "leaf":
        return root
    children: List[Dict[str, Any]] = []
    sizes: List[float] = []
    changed = False
    own = root.get("sizes") or []
    for at, child in enumerate(root.get("children") or []):
        made = canonicalize(child)
        if made is not child:
            changed = True
        size = own[at] if at < len(own) else 0
        if made.get("t") == "split" and made.get("dir") == root.get("dir"):
            changed = True
            inner = normalize_shares(list(made["sizes"]))
            for j, grand in enumerate(made["children"]):
                children.append(grand)
                sizes.append(inner[j] * size)
            continue
        children.append(made)
        sizes.append(size)
    if len(children) == 1:
        return children[0]
    scaled = normalize_shares(sizes)
    if not changed and all(
        at < len(own) and abs(one - own[at]) < 1e-12 for at, one in enumerate(scaled)
    ):
        return root
    return dict(root, children=children, sizes=scaled)


def remove_leaf(root: Dict[str, Any], slot: str) -> Optional[Dict[str, Any]]:
    found = False

    def visit(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        nonlocal found
        if node.get("t") == "leaf":
            if node.get("id") != slot:
                return node
            found = True
            return None
        children: List[Dict[str, Any]] = []
        sizes: List[float] = []
        own = node.get("sizes") or []
        for at, child in enumerate(node.get("children") or []):
            kept = visit(child)
            if kept is None:
                continue
            children.append(kept)
            sizes.append(own[at] if at < len(own) else 0)
        if not children:
            return None
        return dict(node, children=children, sizes=normalize_shares(sizes))

    out = visit(root)
    if not found:
        return root
    return canonicalize(out) if out is not None else None


def terminal_slots_of(layout: Dict[str, Any]) -> List[str]:
    root = ((layout.get("variants") or {}).get("wide") or {}).get("root")
    if not isinstance(root, dict):
        return []
    out: List[str] = []
    for leaf in leaves_of(root):
        if isinstance(leaf, str) and leaf.startswith(TERMINAL_PREFIX) and leaf not in out:
            out.append(leaf)
    return out


def without_slot(layout: Dict[str, Any], slot: str) -> Optional[Dict[str, Any]]:
    variants = dict(layout.get("variants") or {})
    for size in SIZE_CLASSES:
        root = remove_leaf(variants[size]["root"], slot)
        if root is None:
            return None
        variants[size] = {"root": root}
    out = dict(
        layout,
        variants=variants,
        hidden=[one for one in layout.get("hidden") or [] if one != slot],
        collapsed=[one for one in layout.get("collapsed") or [] if one != slot],
    )
    if "headerOff" in layout:
        out["headerOff"] = [one for one in layout.get("headerOff") or [] if one != slot]
    return out
