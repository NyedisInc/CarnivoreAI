
from __future__ import annotations

from typing import Dict, Mapping, Optional

from src.cplugs.huddle.rules import TaskManagerInvalid


MARKERS = ("diamond", "square", "triangle", "circle", "hexagon", "pentagon", "star", "cross")

LEGACY: Mapping[str, str] = {"purple": "star", "pink": "cross", "teal": "hexagon", "lime": "circle"}

COLUMN = "flag_color"
LEGACY_REASON_COLUMN = "flag_reason"

FIELD = "marker"

CLEAR: Mapping[str, None] = {COLUMN: None, LEGACY_REASON_COLUMN: None}


def canonical(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    name = LEGACY.get(name, name)
    return name if name in MARKERS else None


def from_args(marker: Optional[object], legacy_color: Optional[object] = None) -> Optional[object]:
    return marker if marker is not None else legacy_color


def clean_fields(marker: Optional[object]) -> Dict[str, Optional[str]]:
    if marker is None:
        return {}
    if not isinstance(marker, str):
        raise TaskManagerInvalid("marker is a marker name (text)")
    if not marker.strip():
        return dict(CLEAR)
    name = canonical(marker)
    if name is None:
        raise TaskManagerInvalid(f"unknown marker {marker.strip().lower()}; use one of: {', '.join(MARKERS)} (an empty string clears the marker)")
    return {COLUMN: name, LEGACY_REASON_COLUMN: None}


def wire(row: Mapping[str, object]) -> Dict[str, str]:
    name = canonical(row[COLUMN])
    return {FIELD: name} if name else {}
