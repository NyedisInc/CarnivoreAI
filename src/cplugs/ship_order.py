
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

ORDER_FILE = Path(__file__).resolve().parent / "order.json"


class ShipOrderError(Exception):
    pass


def ship_order(path: Path = ORDER_FILE) -> Tuple[str, ...]:
    try:
        names = json.loads(path.read_text(encoding="utf-8"))["order"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ShipOrderError(f"the ship order file {path.name} is unreadable: {exc}") from exc
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ShipOrderError(f"the ship order file {path.name} must hold a list of plugin names under 'order'")
    return tuple(names)
