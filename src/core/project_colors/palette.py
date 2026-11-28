
from __future__ import annotations

import re
from typing import Tuple

SOFT_PALETTE: Tuple[str, ...] = (
    "#e6495c", "#e67329", "#c99214",
    "#6ea61c", "#1ea662", "#12a392",
    "#1c9ed6", "#4a80eb", "#7a6af0",
    "#ae62eb", "#de54be", "#e64e83",
)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex_color(value: object) -> bool:
    return isinstance(value, str) and _HEX.match(value) is not None


def normalize_color(value: str) -> str:
    return value.lower()
