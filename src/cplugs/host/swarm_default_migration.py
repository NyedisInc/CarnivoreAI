
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import structlog

from src.cplugs.host import runtime, state as owner_state

logger = structlog.get_logger()

SWARM_ID = "huddle"


def migrate(state_dir: Path, fresh_install: bool) -> Optional[bool]:
    """Seed the huddle's owner state when it has none. Output: what was stored (True on, False off), None when nothing was written.

    Inputs: state_dir (Path); fresh_install (``DatastoreState.fresh_install``: ``cloude.db`` was absent or empty at this boot).
    Raises ``StateWriteFailed`` when the state file cannot be written (the host's boot logs it and goes on; the next boot retries).
    Example: migrate(state, True) -> True; a second call -> None
    """
    if owner_state.stored_enabled(state_dir, SWARM_ID) is not None:
        return None
    definition = runtime.find(SWARM_ID)
    if definition is None:
        return None
    on = fresh_install is True
    owner_state.update(state_dir, definition.manifest, None, lambda st: replace(
        st, enabled=on, grants=tuple(definition.manifest.permissions) if on else ()))
    logger.info("cplug_swarm_default_migrated", enabled=on)
    return on
