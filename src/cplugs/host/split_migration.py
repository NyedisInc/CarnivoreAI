
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Dict

import structlog

from src.cplugs.host import runtime, state as owner_state

logger = structlog.get_logger()

SPLIT_IDS = ("save",)


def effective_switches(config_path: Path, fresh_install: bool = False) -> Dict[str, bool]:
    save = not fresh_install and os.environ.get("CLOUDE_SAVE_PIPELINE") != "0"
    return {"save": save}


def migrate(state_dir: Path, config_path: Path, fresh_install: bool = False) -> Dict[str, bool]:
    pending = [i for i in SPLIT_IDS if owner_state.stored_enabled(state_dir, i) is None]
    if not pending:
        return {}
    effective = effective_switches(config_path, fresh_install)
    written: Dict[str, bool] = {}
    for cplug_id in pending:
        definition = runtime.find(cplug_id)
        if definition is None:
            continue
        on = effective[cplug_id]
        owner_state.update(state_dir, definition.manifest, None, lambda st, on=on, asked=definition.manifest.permissions: replace(
            st, enabled=on, grants=tuple(asked) if on else ()))
        written[cplug_id] = on
    logger.info("cplug_split_migrated", **written)
    return written
