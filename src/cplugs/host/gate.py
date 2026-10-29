
from __future__ import annotations

from pathlib import Path
from typing import Optional, Set, Tuple

from src.cplugs.host import runtime, state as owner_state


def _state_dir(state_dir: Optional[Path]) -> Path:
    if state_dir is None:
        from src.config import settings  # noqa: PLC0415

        return Path(settings.get_state_dir())
    return Path(state_dir)


def is_on(cplug_id: str, state_dir: Optional[Path] = None) -> bool:
    definition = runtime.find(cplug_id)
    if definition is None:
        return False
    return owner_state.get(_state_dir(state_dir), definition.manifest).enabled


def blocked_by(cplug_id: str, state_dir: Optional[Path] = None) -> Tuple[str, ...]:
    root = _state_dir(state_dir)
    blocked: list = []
    seen: Set[str] = {cplug_id}
    definition = runtime.find(cplug_id)
    queue = list(definition.manifest.requires) if definition is not None else []
    while queue:
        rid = queue.pop(0)
        if rid in seen:
            continue
        seen.add(rid)
        required = runtime.find(rid)
        if required is None or not owner_state.get(root, required.manifest).enabled:
            blocked.append(rid)
        if required is not None:
            queue.extend(required.manifest.requires)
    return tuple(blocked)


def effective_on(cplug_id: str, state_dir: Optional[Path] = None) -> bool:
    return is_on(cplug_id, state_dir) and not blocked_by(cplug_id, state_dir)
