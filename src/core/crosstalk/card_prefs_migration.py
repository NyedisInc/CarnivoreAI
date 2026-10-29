
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Protocol

import structlog

from src.core.crosstalk.card_push import GATE_FIELD
from src.cplugs.host import state as plugin_state

logger = structlog.get_logger()

PLUGIN_ID = "xtalk"
SETTING_TO_FIELD: Mapping[str, str] = {
    "senderCards": "crosstalk_card_sender",
    "receiverCards": "crosstalk_card_receiver",
    "keepCards": "crosstalk_card_keep",
}


class PreferenceStore(Protocol):

    def read(self) -> Dict[str, Any]: ...

    def update(self, changes: Dict[str, Any], expected_revision: Any = None) -> Any: ...


def stored_preferences(state_dir: Path) -> Dict[str, bool]:
    entry = plugin_state.stored_entry(state_dir, PLUGIN_ID)
    if entry is None:
        return {GATE_FIELD: False}
    settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else {}
    carried: Dict[str, bool] = {GATE_FIELD: entry.get("enabled") is True}
    for setting, field in SETTING_TO_FIELD.items():
        if isinstance(settings.get(setting), bool):
            carried[field] = settings[setting]
    return carried


def migrate(state_dir: Path, store: PreferenceStore) -> bool:
    try:
        if GATE_FIELD in (store.read().get("values") or {}):
            return False
        carried = stored_preferences(state_dir)
        result = store.update(carried)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.error("crosstalk_cards_migration_failed", error_type=type(exc).__name__)
        return False
    if result.status != "committed":
        logger.error("crosstalk_cards_migration_refused", status=result.status, detail=result.detail)
        return False
    logger.info("crosstalk_cards_migrated", enabled=carried[GATE_FIELD], carried=len(carried))
    return True
