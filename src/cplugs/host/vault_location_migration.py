
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import structlog

from src.core.backup_health import vault_record
from src.cplugs.host import runtime, state as owner_state

logger = structlog.get_logger()


def migrate(state_dir: Path, config_path: Path) -> Optional[str]:
    entry = owner_state.stored_entry(state_dir, vault_record.SAVE_PLUGIN_ID)
    if entry is None:
        logger.info("vault_location_migration_waiting", reason="the save plugin has no stored entry yet; the old value is still read")
        return None
    settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
    if vault_record.LOCATION_SETTING in settings:
        return None
    definition = runtime.find(vault_record.SAVE_PLUGIN_ID)
    if definition is None:
        return None
    value = vault_record.location_of(vault_record.read_config(config_path))
    copied = {"done": False}

    def mutate(st: owner_state.CplugState) -> owner_state.CplugState:
        if vault_record.LOCATION_SETTING in st.settings:
            return st
        copied["done"] = True
        return replace(st, settings={**st.settings, vault_record.LOCATION_SETTING: value})

    owner_state.update(state_dir, definition.manifest, None, mutate)
    if not copied["done"]:
        return None
    logger.info("vault_location_migrated", copied=value or "(blank: the default folder)", source="config.json save_pipeline.vault_location",
                note="the setting value only; no file was moved and the old key is left in place")
    return value
