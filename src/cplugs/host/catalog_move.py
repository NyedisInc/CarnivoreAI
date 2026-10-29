
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.app_alerts import constants as alert_constants
from src.cplugs.host import state as owner_state
from src.cplugs.host.adoption import BUILTIN_SOURCE, KIND_CPLUG, NAME_PREFIX
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, LedgerError

logger = structlog.get_logger()

MOVED_TO_CATALOG: Dict[str, str] = {"mcphealth": "carnivore/mcphealth"}
ALERT_TITLE_KEY = "app_alert.cplug_moved.title"
ALERT_DETAIL_KEY = "app_alert.cplug_moved.detail"
ACTION_LABEL_KEY = "app_alert.action.open_warez"


def _alert(raise_alert: Callable[..., Any], plugin_id: str, catalog_id: str) -> bool:
    row = raise_alert(
        f"cplug.{plugin_id}.moved_to_catalog", source=f"cplug.{plugin_id}", severity=alert_constants.SEV_WARN, title_key=ALERT_TITLE_KEY,
        detail_key=ALERT_DETAIL_KEY, params={"plugin": plugin_id}, sticky=True, auto_resolve=False,
        actions=({"id": "open_warez", "label_key": ACTION_LABEL_KEY, "href": f"#warez/{catalog_id}"},))
    return row is not None


def migrate(services: Any, state_dir: Path, raise_alert: Optional[Callable[..., Any]] = None) -> List[str]:
    if raise_alert is None:
        from src.core.app_alerts.service import raise_alert as default_raise  # noqa: PLC0415

        raise_alert = default_raise
    done: List[str] = []
    try:
        with services.catalog.ledger() as ledger:
            for plugin_id, catalog_id in MOVED_TO_CATALOG.items():
                try:
                    stale = ledger.find_by_name(f"{NAME_PREFIX}{plugin_id}", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
                    if stale is None or stale.kind != KIND_CPLUG or stale.source_index_url != BUILTIN_SOURCE:
                        continue
                    if owner_state.stored_enabled(state_dir, plugin_id) is True and not _alert(raise_alert, plugin_id, catalog_id):
                        continue
                    owner_state.strip_consent(state_dir, plugin_id)
                    ledger.delete(stale.install_id)
                    done.append(plugin_id)
                    logger.info("cplug_moved_to_catalog", cplug=plugin_id, catalog_id=catalog_id)
                except (LedgerError, sqlite3.Error, owner_state.StateWriteFailed) as exc:
                    logger.warning("cplug_move_failed", cplug=plugin_id, error=type(exc).__name__, detail=str(exc)[:200])
    except (LedgerError, sqlite3.Error, OSError) as exc:
        logger.warning("cplug_move_failed", cplug="*", error=type(exc).__name__, detail=str(exc)[:200])
    return done


async def run_catalog_move_pass(services: Any, state_dir: Path) -> List[str]:
    return await asyncio.to_thread(migrate, services, state_dir)
