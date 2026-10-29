
from __future__ import annotations

import re
from typing import Tuple

SOFT_PALETTE: Tuple[str, ...] = (
    "#966356", "#a7593d", "#a25e2b",
    "#a17557", "#c07e45", "#817040",
    "#4e69ba", "#7b75e2", "#7457c2",
    "#a167cf", "#b765a1", "#ad3f7f",
)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex_color(value: object) -> bool:
    return isinstance(value, str) and _HEX.match(value) is not None


def normalize_color(value: str) -> str:
    return value.lower()
