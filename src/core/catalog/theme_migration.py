
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, FrozenSet, List, Optional, Set

import structlog

from src.core import theme_paths
from src.core.catalog.first_party import is_first_party_item
from src.core.catalog.verify import check_digest
from src.core.sessions import theme_dotfile, theme_global
from src.core.skills.consent_via_ddl import CONSENT_ONE_CLICK
from src.core.skills.install_plan import plan_install
from src.core.skills.install_types import InstallPlan
from src.core.skills.installer import apply_install, discard_staging, iso_from
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, LedgerError
from src.core.test_write_guard import OutsideTempWriteError, assert_test_write_allowed
from src.models.catalog_names import (
    FIRST_PARTY_THEME_NAMES,
    FIRST_PARTY_HANDLES,
    RETIRED_THEME_NAMES,
)

logger = structlog.get_logger()

MOVED_THEME_IDS: FrozenSet[str] = FIRST_PARTY_THEME_NAMES

DELETED_UNPUBLISHED_THEME_IDS: FrozenSet[str] = frozenset({"black_market", "cannabis"})

BUNDLED_THEMES_ROOT = Path(__file__).resolve().parents[3] / "client" / "css" / "themes"


def ensure_user_themes_dir() -> bool:
    path = theme_paths.user_themes_dir()
    if path.is_dir():
        return True
    try:
        assert_test_write_allowed(path)
        path.mkdir(parents=True, exist_ok=True)
    except (OutsideTempWriteError, OSError) as exc:
        logger.warning("theme_migration_mkdir_failed", path=str(path), error=str(exc))
        return False
    return True


def collect_in_use(services: Any) -> Set[str]:
    ids: Set[str] = set(services.themes.pinned_themes.values())
    global_id = theme_global.read_global_theme(services.themes.global_theme_reader)
    if global_id:
        ids.add(global_id)
    try:
        with closing(services.catalog.open_db()) as conn:
            ids.update(r[0] for r in conn.execute("SELECT DISTINCT pinned_theme FROM sessions WHERE pinned_theme IS NOT NULL"))
            roots = [r[0] for r in conn.execute("SELECT root FROM projects")]
    except sqlite3.Error as exc:
        logger.warning("theme_migration_db_unreadable", error=str(exc))
        roots = []
    for root in roots:
        found = theme_dotfile.read_project_theme(root)
        if found:
            ids.add(found)
    return {i for i in ids if isinstance(i, str) and i}


def wanted_ids(services: Any, in_use: Set[str], *, bundled_root: Optional[Path] = None) -> List[str]:
    bundled_root = bundled_root or BUNDLED_THEMES_ROOT
    user_root = theme_paths.user_themes_dir()
    out: List[str] = []
    with services.catalog.ledger() as ledger:
        for theme_id in sorted(in_use & MOVED_THEME_IDS):
            if (bundled_root / theme_id).exists() or os.path.lexists(user_root / theme_id):
                continue
            if all(ledger.find(f"{handle}/{theme_id}", SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) is None
                   for handle in FIRST_PARTY_HANDLES):
                out.append(theme_id)
    return out


def prune_retired_pins(services: Any) -> List[str]:
    user_root = theme_paths.user_themes_dir()
    ids = {i for i in set(RETIRED_THEME_NAMES) | DELETED_UNPUBLISHED_THEME_IDS if not os.path.lexists(user_root / i)}
    dropped: List[str] = []
    for theme_id in sorted(ids):
        dropped.extend(services.themes.discard_theme(theme_id))
    if dropped:
        logger.info("theme_migration_retired_pins_pruned", sessions=len(dropped))
    return dropped


def _plan_and_record(services: Any, item: Any, version: Any, staged: Any, index_url: str) -> Any:
    from src.api.catalog_install_support import announce_theme_change, discovery_listing

    roots = services.install_roots
    with services.catalog.ledger() as ledger:
        verdict = plan_install(
            item=item, version=version, staged=staged, scope=SCOPE_GLOBAL, project_path=None,
            ledger=ledger, roots=roots, discovery_listing=discovery_listing(roots),
            harnesses=frozenset(roots.present_harnesses()),
        )
        if not isinstance(verdict, InstallPlan):
            logger.info("theme_migration_refused", item_id=item.id, code=getattr(verdict, "code", "unknown"))
            return None
        row = apply_install(
            verdict, ledger=ledger, roots=roots, clock=services.clock, source_index_url=index_url,
            publisher_key_id=services.catalog.publisher_key_id, consent_via=CONSENT_ONE_CLICK,
        )
        row = ledger.update(row.install_id, expected_revision=row.revision, now=iso_from(services.clock), auto_update=True)
    announce_theme_change(row)
    return row


async def install_one(services: Any, snapshot: Any, theme_id: str) -> bool:
    from fastapi import HTTPException

    from src.api.catalog_install_support import fetch_and_stage_with
    from src.api.catalog_views import find_item, latest_version
    from src.core.skills.validate import ArchiveRefused

    for handle in FIRST_PARTY_HANDLES:
        item_id = f"{handle}/{theme_id}"
        item, untrusted = find_item(snapshot, item_id)
        if item is not None:
            break
    if item is None:
        logger.debug("theme_migration_not_in_index", item_id=item_id)
        return False
    version = latest_version(item)
    if untrusted or version is None or not is_first_party_item(item):
        logger.warning("theme_migration_item_refused", item_id=item_id, untrusted=untrusted)
        return False
    if item.deprecated is not None:
        logger.info("theme_migration_item_deprecated", item_id=item_id)
        return False
    try:
        staging, staged = await fetch_and_stage_with(services, item, version)
    except (HTTPException, ArchiveRefused, OSError) as exc:
        logger.warning("theme_migration_fetch_failed", item_id=item_id, error=str(exc))
        return False
    try:
        if check_digest(version.digest, staged.digest) is not None:
            logger.warning("theme_migration_digest_mismatch", item_id=item_id)
            return False
        try:
            row = await asyncio.to_thread(
                _plan_and_record, services, item, version, staged, services.catalog.index_url()
            )
        except (OSError, sqlite3.Error, HTTPException, LedgerError) as exc:
            logger.warning("theme_migration_install_failed", item_id=item_id, error=str(exc))
            return False
    finally:
        await asyncio.to_thread(discard_staging, staging)
    if row is None:
        return False
    logger.info(
        "theme_migration_installed", item_id=item_id, version=version.v, consent_via=CONSENT_ONE_CLICK,
        reason="first_party_theme_moved_to_catalog",
    )
    return True


async def run(snapshot: Any, services: Any) -> List[str]:
    if snapshot.verified is None or snapshot.refusal is not None:
        return []
    if snapshot.degraded:
        logger.info("theme_migration_index_degraded")
        return []
    wanted = await asyncio.to_thread(lambda: wanted_ids(services, collect_in_use(services)))
    installed: List[str] = []
    for theme_id in wanted:
        if await install_one(services, snapshot, theme_id):
            installed.append(theme_id)
    return installed
