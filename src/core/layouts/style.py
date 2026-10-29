
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional

from src.core.layouts.ddl import LAYOUTS_TABLE
from src.core.layouts.style_ddl import LAYOUT_STYLES_TABLE
from src.core.session_group_style import (
    ANIMATIONS,
    AUTO_COLOURS,
    COLOURS,
    GRADIENTS,
    GroupStyleInvalid,
    canonical_colour,
    random_colour,
    valid_colour,
)
from src.core.session_group_style import validate as _validate_palette
from src.core.trail_entry import utc_now

DEFAULT_COLOUR = "indigo"

SOURCE_STORED = "stored"
SOURCE_DERIVED = "derived"


class LayoutStyleInvalid(Exception):
    pass


@dataclass(frozen=True)
class LayoutStyle:

    colour: str
    gradient: Optional[str]
    animation: str
    source: str


def validate(colour: str, gradient: Optional[str], animation: str) -> None:
    try:
        _validate_palette(colour, gradient, animation)
    except GroupStyleInvalid as exc:
        raise LayoutStyleInvalid(str(exc)) from exc


def write(
    conn: sqlite3.Connection,
    layout_uuid: str,
    colour: str,
    gradient: Optional[str] = None,
    animation: str = "none",
    *,
    now: Optional[str] = None,
) -> None:
    validate(colour, gradient, animation)
    conn.execute(
        "INSERT INTO layout_styles (layout_uuid, colour, gradient, animation, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(layout_uuid) DO UPDATE SET "
        "colour = excluded.colour, gradient = excluded.gradient, "
        "animation = excluded.animation, updated_at = excluded.updated_at",
        (layout_uuid, canonical_colour(colour), gradient, animation, now or utc_now()),
    )


def styles_by_layout(conn: sqlite3.Connection) -> Dict[str, LayoutStyle]:
    try:
        rows = conn.execute(
            "SELECT layout_uuid, colour, gradient, animation FROM layout_styles"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: Dict[str, LayoutStyle] = {}
    for layout_uuid, colour, gradient, animation in rows:
        if not valid_colour(colour):
            continue
        out[str(layout_uuid)] = LayoutStyle(
            colour=str(colour),
            gradient=gradient if gradient in GRADIENTS else None,
            animation=animation if animation in ANIMATIONS else "none",
            source=SOURCE_STORED,
        )
    return out


def resolve(stored: Optional[LayoutStyle]) -> LayoutStyle:
    if stored is not None:
        return stored
    return LayoutStyle(colour=DEFAULT_COLOUR, gradient=None, animation="none", source=SOURCE_DERIVED)


__all__ = [
    "ANIMATIONS",
    "AUTO_COLOURS",
    "COLOURS",
    "DEFAULT_COLOUR",
    "GRADIENTS",
    "LAYOUT_STYLES_TABLE",
    "LAYOUTS_TABLE",
    "LayoutStyle",
    "LayoutStyleInvalid",
    "SOURCE_DERIVED",
    "SOURCE_STORED",
    "random_colour",
    "resolve",
    "styles_by_layout",
    "validate",
    "write",
]
