
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
    """The merged configuration plus a full account of how it was reached.

    Attributes:
        merged: The resulting configuration mapping.
        decisions: One Decision per field examined.
        had_base: Whether a recorded base was available. False means every
            differing field is CANNOT_DETERMINE rather than classified.
        importable: Mapping of dotted list path to the items present in the
            new defaults but absent from the user's list. Never applied
            automatically.
    """

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
    """Classify one leaf field into exactly one outcome.

    Args:
        path: Dotted path, used only for reporting.
        base: Old default, or MISSING.
        mine: User value, or MISSING.
        theirs: New default, or MISSING.
        had_base: Whether a base document was supplied at all.
        removal_provable: Whether "absent from the new defaults" is real
            evidence that upstream removed this setting. False when the
            defaults document is known to be an incomplete account of what
            upstream ships, in which case absence proves nothing and the
            honest answer is CANNOT_DETERMINE. See ``merge_config``.

    Returns:
        The Decision for this field, including the value to write.
    """
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
    """Whether absence from the new defaults is EVIDENCE of an upstream removal.

    Absence is only evidence when the defaults document is a complete account
    of what upstream ships. Two situations break that, and both must produce
    CANNOT_DETERMINE rather than a confident removal:

    * The caller told us which keys the running code actually supports
      (``supported_keys``) and this one is not among the settings whose
      subtree the defaults document is known to describe.
    * The top-level key's value had to be supplied from the model because the
      defaults document omitted it entirely (``stale_roots``). Nothing about
      that subtree can be concluded from a document that never mentioned it.

    Args:
        path: Dotted path being classified.
        supported_keys: Top-level keys the loader honours, or None when the
            caller asserts the defaults document is complete.
        stale_roots: Top-level keys the defaults document omitted.

    Returns:
        True when a REMOVED_UPSTREAM verdict is supported by evidence.

    Example:
        >>> _removal_provable("config_version", frozenset({"agents"}), frozenset())
        True
        >>> _removal_provable("agents.x", frozenset({"agents"}), frozenset({"agents"}))
        False
    """
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

        merged[key] = _walk(
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

    return merged


def merge_config(
    mine: dict,
    theirs: dict,
    base: Optional[dict] = None,
    supported_keys: Optional[frozenset] = None,
    stale_roots: frozenset = frozenset(),
) -> MergeResult:
    """Three-way merge the user's config against new shipped defaults.

    Args:
        mine: The user's live configuration.
        theirs: The defaults shipping with the new version.
        base: The defaults that shipped with the user's current version. None
            means no base was recorded, which makes every differing field
            CANNOT_DETERMINE rather than a guess.
        supported_keys: Top-level keys the running code actually honours, when
            the caller knows them. Passing None asserts that ``theirs`` is a
            COMPLETE account of what upstream ships, which licenses a
            REMOVED_UPSTREAM verdict for anything missing from it. Callers
            merging against ``config.example.json`` must NOT assert that: the
            example is a hand-maintained sample and has repeatedly gone stale,
            which is how two live settings came to be reported as removed.
        stale_roots: Top-level keys ``theirs`` omitted entirely, so nothing
            about those subtrees can be concluded from it.

    Returns:
        A MergeResult holding the merged mapping, one Decision per field, and
        any additive list imports that were NOT applied.

    Example:
        >>> result = merge_config({"a": 1}, {"a": 2}, base={"a": 1})
        >>> result.merged["a"]
        2
    """
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
