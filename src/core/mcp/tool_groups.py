
from __future__ import annotations

import re
from typing import Iterable, NamedTuple

from src.core.mcp import aliases, deprecated_tools
from src.core.mcp.registry.model import HEADINGS, MIN_SEGMENTS

GROUP_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

DIRECT = ""

FALLBACK_HEADING = "system"


class Place(NamedTuple):

    heading: str
    sub: str


def place_of(name: str) -> Place:
    if deprecated_tools.is_deprecated(name):
        return Place(deprecated_tools.GROUP, DIRECT)
    parts = (aliases.capability_id(name) or "").split(".")
    if parts[0] not in HEADINGS:
        return Place(FALLBACK_HEADING, DIRECT)
    return Place(parts[0], parts[1] if len(parts) > MIN_SEGMENTS else DIRECT)


def placement(names: Iterable[str]) -> dict[str, Place]:
    return {name: place_of(name) for name in names}


def group_map(names: Iterable[str]) -> dict[str, str]:
    return {name: place_of(name).heading for name in names}


def heading_order(heading: str) -> tuple[int, str]:
    return (len(HEADINGS) + 1, heading) if heading == deprecated_tools.GROUP else (
        HEADINGS.index(heading) if heading in HEADINGS else len(HEADINGS), heading)
