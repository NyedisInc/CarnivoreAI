
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import structlog

from src.core.deepsearch import index_scope
from src.cplugs.host import state as plugin_state

logger = structlog.get_logger()

PLUGIN_ID = "deepsearch"
SETTING_KEY = "indexScope"


class PreferenceStore(Protocol):

    def read(self) -> Dict[str, Any]: ...

    def update(self, changes: Dict[str, Any], expected_revision: Any = None) -> Any: ...


def stored_scope(state_dir: Path) -> Optional[str]:
    entry = plugin_state.stored_entry(state_dir, PLUGIN_ID)
    settings = entry.get("settings") if isinstance(entry, dict) else None
    value = settings.get(SETTING_KEY) if isinstance(settings, dict) else None
    return value if value in index_scope.SCOPES else None


def migrate(state_dir: Path, store: PreferenceStore) -> bool:
    """Carry the plugin's stored scope into the preferences once. Output: True when it wrote.

    Inputs: state_dir (the app state directory); store (the ``UiPreferencesStore``). Never raises for a missing or
      unwritable config (logged; the next boot tries again).
    Example: migrate(Path("/state"), store) -> True on the first boot after the move for an owner who chose a scope
    """
    try:
        if index_scope.PREFERENCE_FIELD in (store.read().get("values") or {}):
            return False
        carried = stored_scope(state_dir)
        if carried is None:
            return False
        result = store.update({index_scope.PREFERENCE_FIELD: carried})
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.error("deepsearch_scope_migration_failed", error_type=type(exc).__name__)
        return False
    if result.status != "committed":
        logger.error("deepsearch_scope_migration_refused", status=result.status, detail=result.detail)
        return False
    logger.info("deepsearch_scope_migrated", scope=carried)
    return True
