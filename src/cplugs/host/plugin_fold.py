
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

import structlog

from src.cplugs.host import runtime, state as owner_state

logger = structlog.get_logger()


def migrate(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    written: Dict[str, Dict[str, Any]] = {}
    for definition in runtime.definitions():
        fields = definition.manifest.settings_schema.get("fields", {})
        for old, switch in definition.manifest.legacy_ids.items():
            entry = owner_state.stored_entry(state_dir, old)
            if entry is None or switch in owner_state.get(state_dir, definition.manifest).settings:
                continue
            saved = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
            carried = {k: v for k, v in saved.items() if k in fields and k != switch}
            carried[switch] = entry.get("enabled") is True
            owner_state.update(state_dir, definition.manifest, None, lambda st, carried=carried: replace(st, settings={**st.settings, **carried}))
            written.setdefault(definition.id, {}).update(carried)
            logger.info("cplug_folded", old=old, into=definition.id, was_on=carried[switch], settings=sorted(carried))
    return written
