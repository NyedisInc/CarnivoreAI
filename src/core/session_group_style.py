
from __future__ import annotations

import hashlib
import random
import re
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional

from src.core import icon_registry
from src.core.db import column_exists
from src.core.session_group_errors import SessionGroupError
from src.core.session_group_icon_ddl import ICON_COLUMN
from src.core.session_group_style_ddl import SESSION_GROUP_STYLES_TABLE
from src.core.trail_entry import utc_now

COLOURS = ("cyan", "violet", "yellow", "green", "coral", "orange", "teal", "rose", "gold")

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def valid_colour(colour: object) -> bool:
    return isinstance(colour, str) and (colour in COLOURS or _HEX.match(colour) is not None)


def canonical_colour(colour: str) -> str:
    return colour.lower() if colour.startswith("#") else colour


AUTO_COLOURS = ("green", "coral", "orange", "teal", "rose", "gold")

GRADIENTS = ("ember", "tide", "dusk", "neon")

ANIMATIONS = ("none", "shimmer", "pulse")

SOURCE_STORED = "stored"
SOURCE_DERIVED = "derived"


class GroupStyleInvalid(SessionGroupError):
    pass


class GroupIconUnknown(SessionGroupError):

    code = "unknown_icon"


@dataclass(frozen=True)
class GroupStyle:

    colour: str
    gradient: Optional[str]
    animation: str
    source: str
    icon: Optional[str] = None


def derived_colour(group_uuid: str) -> str:
    digest = hashlib.sha256(group_uuid.encode("utf-8")).digest()
    return AUTO_COLOURS[digest[0] % len(AUTO_COLOURS)]


def random_colour(rng: Optional[random.Random] = None) -> str:
    return (rng or random).choice(AUTO_COLOURS)


def validate(colour: str, gradient: Optional[str], animation: str) -> None:
    if not valid_colour(colour):
        raise GroupStyleInvalid(f"colour must be one of {', '.join(COLOURS)} or a #rrggbb hex")
    if gradient is not None and gradient not in GRADIENTS:
        raise GroupStyleInvalid(f"gradient must be one of {', '.join(GRADIENTS)} or null")
    if animation not in ANIMATIONS:
        raise GroupStyleInvalid(f"animation must be one of {', '.join(ANIMATIONS)}")


def write(
    conn: sqlite3.Connection,
    group_id: int,
    colour: str,
    gradient: Optional[str] = None,
    animation: str = "none",
    *,
    now: Optional[str] = None,
) -> None:
    validate(colour, gradient, animation)
    conn.execute(
        "INSERT INTO session_group_styles (group_id, colour, gradient, animation, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(group_id) DO UPDATE SET "
        "colour = excluded.colour, gradient = excluded.gradient, "
        "animation = excluded.animation, updated_at = excluded.updated_at",
        (group_id, canonical_colour(colour), gradient, animation, now or utc_now()),
    )


def styles_by_group(conn: sqlite3.Connection) -> Dict[int, GroupStyle]:
    try:
        has_icon = column_exists(conn, SESSION_GROUP_STYLES_TABLE, ICON_COLUMN)
        rows = conn.execute(
            "SELECT group_id, colour, gradient, animation, "
            + (ICON_COLUMN if has_icon else "NULL")
            + f" FROM {SESSION_GROUP_STYLES_TABLE}"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: Dict[int, GroupStyle] = {}
    for gid, colour, gradient, animation, icon in rows:
        if not valid_colour(colour):
            continue
        out[int(gid)] = GroupStyle(
            colour=str(colour),
            gradient=gradient if gradient in GRADIENTS else None,
            animation=animation if animation in ANIMATIONS else "none",
            source=SOURCE_STORED,
            icon=icon if isinstance(icon, str) and icon else None,
        )
    return out


def validate_icon(icon: Optional[str]) -> None:
    """Refuse an icon id the picker does not offer.

    Description: None is "no icon" and always allowed. Anything else must
      be a current or retired id of ``client/js/icons/icon-registry.js``,
      read through ``src/core/icon_registry.py``.
    Inputs: icon (str|None).
    Output: None.
    Raises: GroupIconUnknown - naming the id. IconRegistryUnavailable -
      the registry could not be read, so nothing can be judged.
    Example: validate_icon("flask")  # passes
    """
    if icon is None:
        return
    if not icon_registry.known_ids().accepts(icon):
        raise GroupIconUnknown(
            f"unknown icon id {icon!r}: not in client/js/icons/icon-registry.js"
        )


def write_icon(
    conn: sqlite3.Connection,
    group_id: int,
    group_uuid: str,
    icon: Optional[str],
    *,
    now: Optional[str] = None,
) -> None:
    conn.execute(
        f"INSERT INTO {SESSION_GROUP_STYLES_TABLE} "
        f"(group_id, colour, gradient, animation, updated_at, {ICON_COLUMN}) "
        "VALUES (?, ?, NULL, 'none', ?, ?) ON CONFLICT(group_id) DO UPDATE SET "
        f"{ICON_COLUMN} = excluded.{ICON_COLUMN}, updated_at = excluded.updated_at",
        (group_id, derived_colour(group_uuid), now or utc_now(), icon),
    )


def resolve(stored: Optional[GroupStyle], group_uuid: str) -> GroupStyle:
    if stored is not None:
        return stored
    return GroupStyle(
        colour=derived_colour(group_uuid), gradient=None, animation="none",
        source=SOURCE_DERIVED,
    )
