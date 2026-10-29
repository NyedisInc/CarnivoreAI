
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

UNCHANGED = "unchanged"

UPDATED_DEFAULT = "updated_default"

KEPT_CUSTOM = "kept_custom"

ADDED = "added"

CONFLICT = "conflict"

REMOVED_UPSTREAM = "removed_upstream"

CANNOT_DETERMINE = "cannot_determine"

NEEDS_ATTENTION = frozenset({CONFLICT, REMOVED_UPSTREAM, CANNOT_DETERMINE})

APPLIED_CHANGES = frozenset({UPDATED_DEFAULT, ADDED})

MISSING = object()

_STAYS_ABSENT = object()


@dataclass
class Decision:

    path: str
    outcome: str
    mine: Any = None
    theirs: Any = None
    base: Any = None
    chosen: Any = None
    note: str = ""


@dataclass
class MergeResult:

    merged: dict
    decisions: list[Decision] = field(default_factory=list)
    had_base: bool = True
    importable: dict[str, list] = field(default_factory=dict)

    def needing_attention(self) -> list[Decision]:
        return [d for d in self.decisions if d.outcome in NEEDS_ATTENTION]

    def changes(self) -> list[Decision]:
        return [d for d in self.decisions if d.outcome in APPLIED_CHANGES]


def _is_comment_key(key: str) -> bool:
    return key.startswith("_comment")


def _classify(
    path: str,
    base: Any,
    mine: Any,
    theirs: Any,
    had_base: bool,
    removal_provable: bool = True,
) -> Decision:
    mine_present = mine is not MISSING
    theirs_present = theirs is not MISSING

    if not theirs_present:
        if not removal_provable:
            return Decision(
                path=path,
                outcome=CANNOT_DETERMINE,
                mine=mine,
                theirs=None,
                base=None if base is MISSING else base,
                chosen=mine,
                note=(
                    "This setting is not listed in the shipped defaults, but "
                    "the defaults file is not a complete list of what this "
                    "version supports, so it cannot be determined whether the "
                    "setting was removed or was simply never listed. Your "
                    "value was kept."
                ),
            )
        return Decision(
            path=path,
            outcome=REMOVED_UPSTREAM,
            mine=mine,
            theirs=None,
            base=None if base is MISSING else base,
            chosen=mine,
            note=(
                "This setting is no longer in the shipped defaults. Your value "
                "was kept; nothing was deleted on your behalf."
            ),
        )

    if not mine_present and had_base and base is not MISSING:
        deleted_changed = theirs != base
        return Decision(
            path=path,
            outcome=CONFLICT if deleted_changed else KEPT_CUSTOM,
            mine=None,
            theirs=theirs,
            base=base,
            chosen=None,
            note=(
                "You removed this setting and the shipped default changed since. "
                "It stays removed; decide whether you want it back."
                if deleted_changed else
                "You removed this setting. It stays removed."
            ),
        )

    if not mine_present:
        return Decision(
            path=path,
            outcome=ADDED,
            mine=None,
            theirs=theirs,
            base=None if base is MISSING else base,
            chosen=theirs,
            note="New setting in this version.",
        )

    if mine == theirs:
        return Decision(
            path=path,
            outcome=UNCHANGED,
            mine=mine,
            theirs=theirs,
            base=None if base is MISSING else base,
            chosen=theirs,
        )

    if not had_base or base is MISSING:
        return Decision(
            path=path,
            outcome=CANNOT_DETERMINE,
            mine=mine,
            theirs=theirs,
            base=None,
            chosen=mine,
            note=(
                "Your value differs from the new default, and no record of the "
                "previous default exists, so it cannot be determined whether "
                "you changed this or the default did. Your value was kept."
            ),
        )

    user_changed = mine != base
    default_changed = theirs != base

    if not user_changed and default_changed:
        return Decision(
            path=path,
            outcome=UPDATED_DEFAULT,
            mine=mine,
            theirs=theirs,
            base=base,
            chosen=theirs,
            note="You had the old default, so the new default was adopted.",
        )

    if user_changed and not default_changed:
        return Decision(
            path=path,
            outcome=KEPT_CUSTOM,
            mine=mine,
            theirs=theirs,
            base=base,
            chosen=mine,
        )

    return Decision(
        path=path,
        outcome=CONFLICT,
        mine=mine,
        theirs=theirs,
        base=base,
        chosen=mine,
        note=(
            "You changed this AND the shipped default changed. Your value was "
            "kept and nothing was merged automatically. Decide which you want."
        ),
    )


def _removal_provable(
    path: str,
    supported_keys: Optional[frozenset],
    stale_roots: frozenset,
) -> bool:
    if supported_keys is None:
        return True
    root = path.split(".", 1)[0]
    if root in stale_roots:
        return False
    if root not in supported_keys:
        return True
    return True


def _walk(
    base: Any,
    mine: Any,
    theirs: Any,
    had_base: bool,
    prefix: str,
    decisions: list[Decision],
    importable: dict[str, list],
    supported_keys: Optional[frozenset] = None,
    stale_roots: frozenset = frozenset(),
) -> Any:
    both_maps = isinstance(mine, dict) and isinstance(theirs, dict)
    if not both_maps:
        decision = _classify(
            prefix,
            base,
            mine,
            theirs,
            had_base,
            removal_provable=_removal_provable(prefix, supported_keys, stale_roots),
        )
        decisions.append(decision)

        if isinstance(mine, list) and isinstance(theirs, list) and mine != theirs:
            new_items = [item for item in theirs if item not in mine]
            if new_items:
                importable[prefix] = new_items

        if mine is MISSING and decision.outcome in (KEPT_CUSTOM, CONFLICT):
            return _STAYS_ABSENT
        return decision.chosen

    merged: dict = {}
    keys: list[str] = list(theirs.keys())
    for key in mine.keys():
        if key not in merged and key not in keys:
            keys.append(key)

    for key in keys:
        child_path = f"{prefix}.{key}" if prefix else key
        child_base = (base or {}).get(key, MISSING) if isinstance(base, dict) else MISSING
        child_mine = mine.get(key, MISSING)
        child_theirs = theirs.get(key, MISSING)

        if _is_comment_key(key):
            if child_theirs is not MISSING:
                merged[key] = child_theirs
            continue

        value = _walk(
            child_base,
            child_mine,
            child_theirs,
            had_base,
            child_path,
            decisions,
            importable,
            supported_keys,
            stale_roots,
        )
        if value is _STAYS_ABSENT:
            continue
        merged[key] = value

    return merged


def merge_config(
    mine: dict,
    theirs: dict,
    base: Optional[dict] = None,
    supported_keys: Optional[frozenset] = None,
    stale_roots: frozenset = frozenset(),
) -> MergeResult:
    decisions: list[Decision] = []
    importable: dict[str, list] = {}
    had_base = base is not None

    merged = _walk(
        copy.deepcopy(base) if had_base else MISSING,
        copy.deepcopy(mine),
        copy.deepcopy(theirs),
        had_base,
        "",
        decisions,
        importable,
        supported_keys,
        stale_roots,
    )

    return MergeResult(
        merged=merged,
        decisions=decisions,
        had_base=had_base,
        importable=importable,
    )


def load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def apply_import(merged: dict, dotted_path: str, items: list) -> dict:
    result = copy.deepcopy(merged)
    parts = dotted_path.split(".")
    cursor: Any = result
    for part in parts[:-1]:
        cursor = cursor[part]

    target = cursor.get(parts[-1])
    if not isinstance(target, list):
        raise KeyError(f"{dotted_path} is not a list in this configuration")

    for item in items:
        if item not in target:
            target.append(item)

    return result
