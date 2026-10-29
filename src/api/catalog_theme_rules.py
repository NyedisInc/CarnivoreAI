
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
    """Refuse a scope this KIND does not have. 409 ``scope_not_supported``.

    Description: asked AFTER the item is resolved, because the rule
      depends on the item's kind and the kind comes off the verified
      index. It sits beside :func:`scope_arguments` rather than inside it
      for that reason: that function validates the request against
      itself and runs before anything is resolved.

      A THEME IS A PER-APP RESOURCE AND HAS NO PROJECT SCOPE. This app
      reads themes from the bundled tree and from one user directory, and
      neither is inside a project, so there is no directory a project
      install could write that anything would ever read. The
      project-level equivalent already exists and the catalog does not
      own it: ``<working_dir>/.cc.theme`` NAMES a theme rather than
      containing one.

      IT IS NOT ``project_path_invalid``, which says the path you named
      may not be written and invites you to name another one. There is no
      path that would work here, so the refusal has to say the scope
      itself is not a thing this kind has.
    Inputs: item (CatalogItem) - from a VERIFIED index. scope (str).
    Output: None when the scope is allowed.
    Raises: HTTPException(409) carrying ``scope_not_supported``.
    Example: refuse_unsupported_scope(item, "project")
    """
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
    """After a theme's bytes land, kill a run-grant naming the old ones.

    Description: THE SECOND CONSENT, AND IT IS NOT THIS ONE. Installing a
      theme consents to WRITING its files; running its ``effects.js`` is
      a separate decision held by the six-outcome ladder in
      :mod:`src.core.theme_script_consent`, where an ``always`` records
      the sha256 of the exact file it was granted for. A catalog install
      or update replaces that file without the user being anywhere near
      the theme picker, so the stored grant is left naming bytes that no
      longer exist. It is dropped here rather than left to expire.

      SYNCHRONOUS, FOR A THREAD. It reads a manifest, hashes a file and
      commits ``config.json``; the callers hand it to
      ``asyncio.to_thread`` exactly as they do every other filesystem
      step on these routes.

      A MISSING STORE IS LOGGED, NEVER SHRUGGED OFF. A caller that
      assembled an app without one would otherwise skip this in silence,
      and a silent skip on a security record is the shape this project
      keeps removing. It stays non-fatal because the ladder still
      refuses to run the changed script without us: the grant is inert
      either way, and failing an install whose bytes are already on disk
      would be the worse outcome.

      IT TAKES THE SERVICES, NOT A REQUEST, AND THAT IS WHY THE STORE
      MOVED ONTO THEM. The automatic update pass applies exactly this
      write with no request in hand, so a drop reachable only through
      ``app.state`` was a drop that path could not perform: it wrote a
      new ``effects.js`` and left the stored ``always`` naming the old
      one standing, which is the exact record this whole module exists
      to remove.
    Inputs: services (AppServices). row (InstalledItem) - the ledger row
      as stored, whose ``name`` IS the theme id because the folder name
      is.
    Output: None.
    Example: await asyncio.to_thread(drop_theme_run_grant_with, services, row)
    """
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
