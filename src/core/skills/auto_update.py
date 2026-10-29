
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Tuple

import structlog

from src.core.catalog import install_reporter
from src.core.catalog.first_party import is_first_party_item
from src.core.catalog.verify import check_digest
from src.core.skill_watch import sentinel
from src.core.skill_watch.store import default_watch_store
from src.core.skills import update_holds
from src.core.skills.digest import hash_file
from src.core.skills.kinds import manifest_name
from src.core.skills.ledger_types import SCOPE_GLOBAL, InstalledItem
from src.core.skills.manifest_rules import declares_script
from src.core.skills.updates import (
    ALREADY_CURRENT,
    AUTO_UPDATE_OFF,
    DRIFTED,
    DEPRECATED,
    FORKED,
    INSTRUCTIONS_WRITE,
    NO_CONSENTED_BODY,
    SCRIPTS_PRESENT,
    auto_update_eligible,
    update_available,
)
from src.models.catalog import CatalogItem, ItemVersion, review_writes_instructions

logger = structlog.get_logger()

OUTCOME_UPDATED = "updated"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"

NOT_IN_INDEX = "not_in_index"
DIGEST_MISMATCH = "digest_mismatch"
APPLY_FAILED = "apply_failed"

_PASS_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class AutoUpdateRow:

    install_id: str
    item_id: str
    outcome: str
    reason: str
    version: Optional[str] = None


@dataclass(frozen=True)
class AutoUpdateReport:
    """What a whole pass came to, for a log line and for a test.

    Description: the rows are kept separated by outcome rather than
      counted, because "two were skipped" is not an answer anybody can
      act on and "these two, for these reasons" is.
    Inputs: considered (int) - rows the ledger offered. rows
      (tuple[AutoUpdateRow, ...]) - one per row considered. busy (bool) -
      another pass was already running, so this one did nothing. THAT IS
      NOT A FAILURE and it is not an empty pass either, which is why it
      is its own field.
    Output: none, it is a record.
    Example: report.updated  # the rows that actually moved
    """

    considered: int = 0
    rows: Tuple[AutoUpdateRow, ...] = field(default_factory=tuple)
    busy: bool = False

    @property
    def updated(self) -> Tuple[AutoUpdateRow, ...]:
        return tuple(row for row in self.rows if row.outcome == OUTCOME_UPDATED)

    @property
    def skipped(self) -> Tuple[AutoUpdateRow, ...]:
        return tuple(row for row in self.rows if row.outcome == OUTCOME_SKIPPED)

    @property
    def failed(self) -> Tuple[AutoUpdateRow, ...]:
        """The rows that were eligible and could not be applied."""
        return tuple(row for row in self.rows if row.outcome == OUTCOME_FAILED)


def candidate_rows(services: Any) -> List[InstalledItem]:
    with services.catalog.ledger() as ledger:
        return [
            row
            for row in ledger.list()
            if row.scope == SCOPE_GLOBAL and row.auto_update and not update_holds.held(row.item_id)
        ]


def _find_version(
    snapshot: Any, item_id: str
) -> Tuple[Optional[CatalogItem], Optional[ItemVersion]]:
    from src.api.catalog_views import find_item, latest_version

    item, untrusted = find_item(snapshot, item_id)
    if item is None or untrusted:
        return None, None
    return item, latest_version(item)


def _prefetch_skip(
    row: InstalledItem, version: ItemVersion, item: Optional[CatalogItem] = None
) -> Optional[str]:
    if not update_available(row, version):
        return ALREADY_CURRENT
    if item is not None and item.deprecated is not None:
        return DEPRECATED
    if version.scripts > 0:
        return SCRIPTS_PRESENT
    if review_writes_instructions(version.review):
        return INSTRUCTIONS_WRITE
    if row.consented_body_sha is None:
        return NO_CONSENTED_BODY
    if not row.auto_update:
        return AUTO_UPDATE_OFF
    return None


def _folder_drifted(services: Any, row: InstalledItem) -> bool:
    with services.catalog.ledger() as ledger:
        paths = [t.path for t in ledger.targets(row.install_id)]
    verdict = sentinel.check_row(default_watch_store(), row.install_id, row.digest, paths)
    return verdict.state == sentinel.STATE_DRIFTED


def _is_forked(services: Any, install_id: str) -> bool:
    try:
        with services.catalog.ledger() as ledger:
            return install_id in ledger.forked_ids()
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill_fork_state_unreadable", install_id=install_id,
                       error_type=type(exc).__name__)
        return True


async def _one_row(
    services: Any, row: InstalledItem, snapshot: Any
) -> AutoUpdateRow:
    from fastapi import HTTPException

    from src.api.catalog_install_support import fetch_and_stage_with
    from src.api.catalog_installed_support import apply_update_with
    from src.core.skills.installer import discard_staging
    from src.core.skills.validate import ArchiveRefused

    item, version = _find_version(snapshot, row.item_id)
    if item is None or version is None:
        return AutoUpdateRow(
            install_id=row.install_id,
            item_id=row.item_id,
            outcome=OUTCOME_SKIPPED,
            reason=NOT_IN_INDEX,
        )

    early = _prefetch_skip(row, version, item)
    forked = early is None and await asyncio.to_thread(_is_forked, services, row.install_id)
    if forked:
        early = FORKED
    if early is None and await asyncio.to_thread(_folder_drifted, services, row):
        early = DRIFTED
    if early is not None:
        return AutoUpdateRow(
            install_id=row.install_id,
            item_id=row.item_id,
            outcome=OUTCOME_SKIPPED,
            reason=early,
        )

    try:
        staging, staged = await fetch_and_stage_with(services, item, version)
    except (HTTPException, ArchiveRefused, OSError) as exc:
        logger.warning(
            "skill_auto_update_fetch_failed",
            install_id=row.install_id,
            item_id=row.item_id,
            error=str(exc),
        )
        return AutoUpdateRow(
            install_id=row.install_id,
            item_id=row.item_id,
            outcome=OUTCOME_FAILED,
            reason=f"{type(exc).__name__}",
        )

    try:
        mismatch = check_digest(version.digest, staged.digest)
        if mismatch is not None:
            return AutoUpdateRow(
                install_id=row.install_id,
                item_id=row.item_id,
                outcome=OUTCOME_SKIPPED,
                reason=DIGEST_MISMATCH,
            )

        body_sha, _size = await asyncio.to_thread(
            hash_file, staged.path / manifest_name(row.kind)
        )
        scripts_present = (
            await asyncio.to_thread(declares_script, row.kind, staged.path)
            and not is_first_party_item(item)
        )
        verdict = auto_update_eligible(
            row,
            version,
            body_sha,
            verified=True,
            scripts_present=scripts_present,
            forked=await asyncio.to_thread(_is_forked, services, row.install_id),
            deprecated=item.deprecated is not None,
        )
        if not verdict.ok:
            return AutoUpdateRow(
                install_id=row.install_id,
                item_id=row.item_id,
                outcome=OUTCOME_SKIPPED,
                reason=verdict.reason,
            )

        try:
            await asyncio.to_thread(
                apply_update_with,
                services,
                row=row,
                version=version,
                staged=staged,
                body_sha=body_sha,
                expected_revision=row.revision,
            )
        except (HTTPException, OSError, sqlite3.Error) as exc:
            logger.error(
                "skill_auto_update_apply_failed",
                install_id=row.install_id,
                item_id=row.item_id,
                version=version.v,
                error=str(exc),
            )
            return AutoUpdateRow(
                install_id=row.install_id,
                item_id=row.item_id,
                outcome=OUTCOME_FAILED,
                reason=APPLY_FAILED,
                version=version.v,
            )
        install_reporter.schedule_for(services, row.item_id, version.v)
        return AutoUpdateRow(
            install_id=row.install_id,
            item_id=row.item_id,
            outcome=OUTCOME_UPDATED,
            reason="ok",
            version=version.v,
        )
    finally:
        await asyncio.to_thread(discard_staging, staging)


async def run_auto_update_pass(services: Any) -> AutoUpdateReport:
    if _PASS_LOCK.locked():
        logger.debug("skill_auto_update_busy")
        return AutoUpdateReport(busy=True)

    async with _PASS_LOCK:
        snapshot = services.catalog.index_cache.snapshot()
        if snapshot.verified is None:
            logger.debug("skill_auto_update_no_index")
            return AutoUpdateReport()

        try:
            rows = await asyncio.to_thread(candidate_rows, services)
        except (OSError, sqlite3.Error) as exc:
            # could not
            logger.warning("skill_auto_update_ledger_unreadable", error=str(exc))
            return AutoUpdateReport()

        results: List[AutoUpdateRow] = []
        for row in rows:
            try:
                result = await _one_row(services, row, snapshot)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "skill_auto_update_row_crashed",
                    install_id=row.install_id,
                    item_id=row.item_id,
                    error=type(exc).__name__,
                    detail=str(exc),
                )
                result = AutoUpdateRow(
                    install_id=row.install_id,
                    item_id=row.item_id,
                    outcome=OUTCOME_FAILED,
                    reason=type(exc).__name__,
                )
            results.append(result)
            logger.info(
                "skill_auto_update_row",
                install_id=result.install_id,
                item_id=result.item_id,
                outcome=result.outcome,
                reason=result.reason,
                version=result.version,
            )

        report = AutoUpdateReport(considered=len(rows), rows=tuple(results))
        if report.updated or report.failed:
            logger.info(
                "skill_auto_update_pass",
                considered=report.considered,
                updated=len(report.updated),
                skipped=len(report.skipped),
                failed=len(report.failed),
            )
        return report


def after_refresh_hook(services: Any) -> Callable[[], Awaitable[None]]:

    async def _hook() -> None:
        await run_auto_update_pass(services)

    return _hook
