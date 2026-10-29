
from __future__ import annotations

from typing import Dict, Iterable, Tuple

PERMISSION_RENAMES: Dict[str, str] = {"pack": "swarm"}


def current_names(grants: Iterable[str]) -> Tuple[str, ...]:
    out: list = []
    for name in grants:
        name = PERMISSION_RENAMES.get(name, name)
        if name not in out:
            out.append(name)
    return tuple(out)
