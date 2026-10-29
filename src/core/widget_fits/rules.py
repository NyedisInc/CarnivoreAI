
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from src.core.layouts.tree_v7 import leaves_of

WIDGETS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "widgets.json"

INSTANCE_KINDS: Tuple[str, ...] = ("terminal", "browser", "analytics")

PLUGIN_SLOT_RE = re.compile(r"^([a-z][a-z0-9-]*\.[a-z][a-z0-9-]*):")

RETIRED_KEYS: Mapping[str, str] = {
    "zones": "every widget goes everywhere",
    "suggested": "declare sizes, by name",
    "tested": "renamed sizes: sizes are called out by name",
    "allowed": "declare sizes, by name",
    "max": "declare sizes, by name",
}

GRID_SIZE_NAMES: Tuple[str, ...] = ("small", "wide", "tall", "medium", "large", "full")


class FitsCatalogError(ValueError):
    pass


class Fit:

    __slots__ = ("sizes", "any_size", "max_per_surface")

    def __init__(self, sizes: Tuple[str, ...], any_size: bool = False, max_per_surface: Optional[int] = None) -> None:
        self.sizes = sizes
        self.any_size = any_size
        self.max_per_surface = max_per_surface


FITS_KEYS: FrozenSet[str] = frozenset({"sizes", "anySize", "max_per_surface"})

MAX_PER_SURFACE_CEILING = 12


def _max_per_surface(raw: Any, widget_id: str, instancing: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= MAX_PER_SURFACE_CEILING:
        raise FitsCatalogError(f"{widget_id} fits.max_per_surface must be a whole number from 1 to {MAX_PER_SURFACE_CEILING}")
    if instancing == "singleton" and raw != 1:
        raise FitsCatalogError(f"{widget_id} is a singleton, so fits.max_per_surface can only be 1")
    return raw


def _sizes(raw: Any, widget_id: str) -> Tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise FitsCatalogError(f"{widget_id} fits.sizes is not a list of size names")
    for index, name in enumerate(raw):
        if name not in GRID_SIZE_NAMES:
            raise FitsCatalogError(f"{widget_id} fits.sizes[{index}] is not a size name: {name!r}")
    if len(set(raw)) != len(raw):
        raise FitsCatalogError(f"{widget_id} fits.sizes repeats a name")
    return tuple(raw)


def parse_fits(document: Any) -> Dict[str, Fit]:
    rows = document.get("widgets") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise FitsCatalogError("the widget list has no widgets list")
    out: Dict[str, Fit] = {}
    for row in rows:
        widget_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(widget_id, str):
            raise FitsCatalogError(f"widget row {row!r} has no id")
        fits = row.get("fits")
        if fits is None:
            raise FitsCatalogError(f"widget {widget_id} declares no fits: call out its sizes by name")
        if not isinstance(fits, dict):
            raise FitsCatalogError(f"widget {widget_id} fits is not an object")
        for key in fits:
            if key in RETIRED_KEYS:
                raise FitsCatalogError(f"widget {widget_id} fits.{key} is retired: {RETIRED_KEYS[key]}")
            if key not in FITS_KEYS:
                raise FitsCatalogError(f"widget {widget_id} fits carries unknown key {key}")
        any_size = fits.get("anySize", False)
        if not isinstance(any_size, bool):
            raise FitsCatalogError(f"widget {widget_id} fits.anySize is not true or false")
        limit = _max_per_surface(fits.get("max_per_surface"), widget_id, row.get("instancing"))
        out[widget_id] = Fit(_sizes(fits.get("sizes"), widget_id), any_size, limit)
    return out


@lru_cache(maxsize=1)
def load_fits(path: Path = WIDGETS_PATH) -> Dict[str, Fit]:
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    if path == WIDGETS_PATH:
        from src.core.widget_fits.plugin_rows import plugin_widget_rows  # noqa: PLC0415

        document = {**document, "widgets": [*document.get("widgets", []), *plugin_widget_rows()]}
    return parse_fits(document)


def widget_for_slot(slot: str) -> str:
    plugin = PLUGIN_SLOT_RE.match(slot)
    if plugin:
        return plugin.group(1)
    for kind in INSTANCE_KINDS:
        if slot.startswith(f"{kind}:"):
            return f"core.{kind}"
    return f"core.{slot}"


def _v6_placements(layout: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for row in layout.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for slot in row.get("slots") or []:
            if isinstance(slot, dict) and isinstance(slot.get("id"), str):
                out.append(slot["id"])
    return out


def _v7_placements(layout: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for variant in (layout.get("variants") or {}).values():
        root = variant.get("root") if isinstance(variant, dict) else None
        if isinstance(root, dict):
            out.extend(leaves_of(root))
    return out


def placements(layout: Any) -> List[str]:
    if not isinstance(layout, Mapping):
        return []
    return _v7_placements(layout) if layout.get("v") == 7 else _v6_placements(layout)
