"""Ask whether one shipped plugin is on, from core code that must not import the host runtime at import time.

THE REQUIRES GATE (``docs/cplugs.md`` 15, #1611): :func:`is_on` is the plugin's OWN switch; :func:`effective_on` is
"my switch and everything I require, all the way down, are on". A core stage that does a plugin's work asks
:func:`effective_on`, so a plugin whose requirement is off does nothing (inert) instead of half running, and
:func:`blocked_by` names which requirements hold it, for the plugins page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Set, Tuple

from src.cplugs.host import runtime, state as owner_state


def _state_dir(state_dir: Optional[Path]) -> Path:
    """This install's state directory when none is given. Output: Path."""
    if state_dir is None:
        from src.config import settings  # noqa: PLC0415

        return Path(settings.get_state_dir())
    return Path(state_dir)


def is_on(cplug_id: str, state_dir: Optional[Path] = None) -> bool:
    """Whether the shipped plugin ``cplug_id``'s own switch is on. Output: bool (False for an id the ship list lacks).

    Inputs: cplug_id (str); state_dir (Path | None: this install's state directory).
    Example: is_on("share", tmp_path)  # True: ``share`` ships on and nothing was changed
    """
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
