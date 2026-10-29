
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.core.item_settings_schema import SettingsSchema, parse_schema

KIND_WIDGET = "widget"
KIND_PLUGIN = "plugin"

KINDS: Tuple[str, ...] = (KIND_WIDGET, KIND_PLUGIN)

WIDGETS_PATH = Path(__file__).resolve().parent.parent / "data" / "widgets.json"
"""The declared widget list. Under ``src/`` so the packaged app's resync
carries it with the server, as ``plugins.json`` is."""

WIDGETS_SCHEMA = 1
"""The only file shape this reader accepts."""

WIDGET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")

INSTANCINGS = ("singleton", "per-target")

GLANCE_HEIGHT_MIN_PX = 24
GLANCE_HEIGHT_MAX_PX = 160


class ItemCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ItemDecl:

    kind: str
    id: str
    switchable: bool
    schema: Optional[SettingsSchema]
    instancing: Optional[str] = None


def _check_glance(widget_id: str, glance: Any) -> None:
    height = glance.get("height") if isinstance(glance, dict) and set(glance) == {"height"} else None
    if (
        not isinstance(height, int)
        or isinstance(height, bool)
        or not GLANCE_HEIGHT_MIN_PX <= height <= GLANCE_HEIGHT_MAX_PX
    ):
        raise ItemCatalogError(
            f"widget {widget_id} glance must be {{height: {GLANCE_HEIGHT_MIN_PX}..{GLANCE_HEIGHT_MAX_PX} px}}"
        )


def _widget_from(raw: Any) -> ItemDecl:
    if not isinstance(raw, dict) or set(raw) - {"id", "instancing", "settings", "fits", "glance"}:
        raise ItemCatalogError("a widget row must be an object with id, instancing, settings, fits, glance")
    widget_id = raw.get("id")
    if not isinstance(widget_id, str) or not WIDGET_ID_RE.match(widget_id):
        raise ItemCatalogError(f"a widget row has no valid id: {widget_id!r}")
    instancing = raw.get("instancing")
    if instancing not in INSTANCINGS:
        raise ItemCatalogError(f"widget {widget_id} has no valid instancing")
    if "glance" in raw:
        _check_glance(widget_id, raw["glance"])
    schema = parse_schema(raw["settings"]) if "settings" in raw else None
    return ItemDecl(KIND_WIDGET, widget_id, instancing == "singleton", schema, instancing)


def parse_widgets(document: Any) -> Tuple[ItemDecl, ...]:
    if not isinstance(document, dict) or document.get("schema") != WIDGETS_SCHEMA:
        raise ItemCatalogError(f"the widget list must be schema {WIDGETS_SCHEMA}")
    rows = document.get("widgets")
    if not isinstance(rows, list):
        raise ItemCatalogError("the widget list has no widgets list")
    decls = tuple(_widget_from(raw) for raw in rows)
    ids = [decl.id for decl in decls]
    if len(set(ids)) != len(ids):
        raise ItemCatalogError("the widget list repeats an id")
    return decls


@lru_cache(maxsize=1)
def load_widgets(path: Path = WIDGETS_PATH) -> Tuple[ItemDecl, ...]:
    with open(path, "r", encoding="utf-8") as handle:
        decls = parse_widgets(json.load(handle))
    if path != WIDGETS_PATH:
        return decls
    from src.core.widget_fits.plugin_rows import plugin_widget_rows  # noqa: PLC0415

    return decls + parse_widgets({"schema": WIDGETS_SCHEMA, "widgets": plugin_widget_rows()})


def load_plugins() -> Tuple[ItemDecl, ...]:
    return ()


def items_of(kind: str) -> Tuple[ItemDecl, ...]:
    if kind == KIND_WIDGET:
        return load_widgets()
    if kind == KIND_PLUGIN:
        return load_plugins()
    raise KeyError(kind)


def find(kind: str, item_id: str) -> Optional[ItemDecl]:
    if kind not in KINDS:
        return None
    for decl in items_of(kind):
        if decl.id == item_id:
            return decl
    return None


def all_items() -> Dict[str, Tuple[ItemDecl, ...]]:
    return {kind: items_of(kind) for kind in KINDS}
