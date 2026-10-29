
from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.project_colors.color_math import delta_e_hex
from src.core.project_colors.legacy_keys import LEGACY_KEY_REFERENCE_HEX
from src.core.project_colors.palette import SOFT_PALETTE, is_hex_color

_UNCOLORED = "#808080"


def reference_hex(color: Optional[str]) -> str:
    if isinstance(color, str) and is_hex_color(color):
        return color.lower()
    return LEGACY_KEY_REFERENCE_HEX.get(color or "", _UNCOLORED)


def nearest_calm_color(color: Optional[str], palette: Tuple[str, ...] = SOFT_PALETTE) -> str:
    ref = reference_hex(color)
    return min(palette, key=lambda candidate: delta_e_hex(ref, candidate))


def sibling_key(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    return words[0].lower() if words else name.lower()


def assign_calm_colors(
    projects: Iterable[Tuple[str, Optional[str]]], palette: Tuple[str, ...] = SOFT_PALETTE,
) -> Dict[str, str]:
    items: List[Tuple[str, Optional[str]]] = sorted(projects, key=lambda p: p[0])
    cap = max(1, math.ceil(len(items) / len(palette)))
    pairs = sorted(
        (delta_e_hex(reference_hex(color), hex_), name, hex_)
        for name, color in items for hex_ in palette
    )
    use: Dict[str, int] = {h: 0 for h in palette}
    worn: Dict[str, set] = {}
    out: Dict[str, str] = {}
    for _, name, hex_ in pairs:
        if name in out or use[hex_] >= cap or hex_ in worn.setdefault(sibling_key(name), set()):
            continue
        out[name] = hex_
        use[hex_] += 1
        worn[sibling_key(name)].add(hex_)
    for name, color in items:
        if name in out:
            continue
        taken = worn.setdefault(sibling_key(name), set())
        hex_ = min((h for h in palette if h not in taken), key=lambda h: (use[h], delta_e_hex(reference_hex(color), h)))
        out[name] = hex_
        use[hex_] += 1
        taken.add(hex_)
    return out
