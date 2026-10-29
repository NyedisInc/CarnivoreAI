
from __future__ import annotations

from typing import Any, List

import structlog
from fastapi import Request

from src.api.catalog_install_support import refuse_409
from src.core.skills import kinds
from src.core.skills.install_types import SCOPE_NOT_SUPPORTED
from src.core.skills.ledger_types import InstalledItem
from src.core.theme_catalog_consent import drop_stale_effects_grant
from src.models.catalog import CatalogItem

logger = structlog.get_logger()


def refuse_unsupported_scope(item: CatalogItem, scope: str) -> None:
    if kinds.scope_supported(item.kind, scope):
        return
    allowed = list(kinds.scopes_for(item.kind))
    logger.info(
        "catalog_scope_not_supported",
        item_id=item.id,
        kind=item.kind,
        scope=scope,
        allowed=allowed,
    )
    raise refuse_409(
        SCOPE_NOT_SUPPORTED,
        f"a {item.kind} installs at {allowed} scope only, not at "
        f"{scope!r}",
    )


def drop_theme_run_grant_with(services: Any, row: Any) -> None:
    if row.kind != kinds.KIND_THEME:
        return

    store = services.ui_preferences
    if store is None:
        logger.warning(
            "theme_script_grant_store_absent",
            item_id=row.item_id,
            theme_id=row.name,
            reason=(
                "no ui preferences store on the services, so a stale "
                "run-grant could not be checked; the consent ladder still "
                "refuses a changed script"
            ),
        )
        return

    roots = services.install_roots
    for target in roots.targets_for(row.kind, row.scope, None):
        drop_stale_effects_grant(store, row.name, target.leaf_dir / row.name)


def drop_theme_run_grant(request: Request, row: Any) -> None:
    drop_theme_run_grant_with(request.app.state.services, row)


def prune_theme_pins(request: Request, row: InstalledItem) -> List[str]:
    return prune_theme_pins_with(request.app.state.services, row)


def prune_theme_pins_with(services: Any, row: InstalledItem) -> List[str]:
    if row.kind != kinds.KIND_THEME:
        return []
    dropped = services.themes.discard_theme(row.name)
    if dropped:
        logger.info(
            "theme_pins_dropped_on_uninstall",
            item_id=row.item_id,
            theme_id=row.name,
            sessions=len(dropped),
        )
    return dropped
