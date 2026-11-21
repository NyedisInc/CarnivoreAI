
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, TypedDict

from src.core.keymap.catalog_text import catalog_text
from src.core.keymap.scopes import FIELD, GLOBAL, OVERLAY_PREFIX, scopes_overlap

REGISTRY_PATH = Path(__file__).resolve().with_name("registry.json")
STANDARD_CATEGORY = "standard"
CLASH_MESSAGE_KEY = "keymap.refuse.clash"

Overrides = Mapping[str, Mapping[str, Sequence[str]]]


class RegistryEntry(TypedDict):

    id: str
    labelKey: str
    category: str
    scope: str
    mayShare: bool
    rebindable: bool
    keys: Dict[str, List[str]]


class KeymapClashError(ValueError):

    def __init__(self, chord: str, action_id: str, other_id: str) -> None:
        super().__init__(catalog_text(CLASH_MESSAGE_KEY, action=label_of(action_id), other=label_of(other_id), chord=chord))
        self.chord, self.action_id, self.other_id = chord, action_id, other_id


class Clash(NamedTuple):

    chord: str
    a: str
    b: str


@lru_cache(maxsize=1)
def registry() -> List[RegistryEntry]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def label_of(action_id: str) -> str:
    entry = next((a for a in registry() if a["id"] == action_id), None)
    if entry is None:
        return action_id
    key = entry["labelKey"]
    text = catalog_text(key)
    return action_id if text == key else text


def chords_of(action: RegistryEntry, family: str, overrides: Overrides) -> List[str]:
    own = overrides.get(family, {}).get(action["id"]) if action["rebindable"] else None
    return list(own) if isinstance(own, list) else list(action["keys"].get(family, []))


def _overlay_over(top: RegistryEntry, under: RegistryEntry) -> bool:
    return top["mayShare"] and top["scope"].startswith(OVERLAY_PREFIX) and under["scope"] in (GLOBAL, FIELD)


def _shares_on_purpose(a: RegistryEntry, b: RegistryEntry) -> bool:
    return (a["mayShare"] and b["mayShare"]) or _overlay_over(a, b) or _overlay_over(b, a)


def find_clashes(family: str, overrides: Overrides) -> List[Clash]:
    by_chord: Dict[str, List[RegistryEntry]] = {}
    for action in registry():
        if action["category"] != STANDARD_CATEGORY:
            for chord in chords_of(action, family, overrides):
                by_chord.setdefault(chord, []).append(action)
    found: List[Clash] = []
    for chord, holders in by_chord.items():
        has_cmd = "cmd" in chord.split("+")
        for i, a in enumerate(holders):
            for b in holders[i + 1:]:
                if not _shares_on_purpose(a, b) and scopes_overlap(a["scope"], b["scope"], has_cmd):
                    found.append(Clash(chord, a["id"], b["id"]))
    return found


def check_no_new_clash(stored: Optional[Overrides], new: Overrides) -> None:
    for family in ("mac", "other"):
        if family not in new:
            continue
        already = {frozenset((c.chord, c.a, c.b)) for c in find_clashes(family, stored or {})}
        for clash in find_clashes(family, new):
            if frozenset((clash.chord, clash.a, clash.b)) not in already:
                raise KeymapClashError(clash.chord, clash.a, clash.b)
