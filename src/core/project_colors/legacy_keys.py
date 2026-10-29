
from __future__ import annotations

from typing import Dict, Optional, Tuple

from src.core.project_colors.color_math import delta_e_hex
from src.core.project_colors.palette import SOFT_PALETTE, is_hex_color

LEGACY_KEYS: Tuple[str, ...] = (
    "orange", "green", "cyan", "yellow", "coral", "violet", "green-bright", "yellow-bright",
)

LEGACY_KEY_REFERENCE_HEX: Dict[str, str] = {
    "orange": "#ff4652", "green": "#4acf93", "cyan": "#6cb0e0", "yellow": "#dbca76",
    "coral": "#e78475", "violet": "#a98fe0", "green-bright": "#36ef94", "yellow-bright": "#e4c13c",
}


def _nearest_soft(hex_color: str) -> str:
    return min(SOFT_PALETTE, key=lambda candidate: delta_e_hex(hex_color, candidate))


LEGACY_KEY_HEX: Dict[str, str] = {key: _nearest_soft(ref) for key, ref in LEGACY_KEY_REFERENCE_HEX.items()}


def cycle_key(index: int) -> str:
    return LEGACY_KEYS[index % len(LEGACY_KEYS)]


def stored_hex(value: object) -> Optional[str]:
    if is_hex_color(value):
        return str(value).lower()
    return LEGACY_KEY_HEX.get(value) if isinstance(value, str) else None
