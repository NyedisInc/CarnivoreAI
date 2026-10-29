
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

import structlog

from src.core.catalog import builtins
from src.core.skills import kinds
from src.core.skills.consent_via_ddl import CONSENT_ONE_CLICK
from src.core.skills.installer import iso_from
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstalledItem, LedgerError
from src.cplugs.host.dependencies import app_version

logger = structlog.get_logger()

BUILTIN_SOURCE = "builtin"
KIND_CPLUG = kinds.KIND_CPLUG
NAME_PREFIX = "cplug-"


@dataclass
class AdoptionResult:

    adopted: int = 0
    updated: int = 0
    failed: int = 0


def _digest() -> str:
    return f"{BUILTIN_SOURCE}:{app_version() or 'unknown'}"


def _adopt_one(ledger: Any, entry: Any, stamp: str, result: AdoptionResult) -> None:
    existing = ledger.find(entry.id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
    if existing is not None:
        if existing.source_index_url == BUILTIN_SOURCE and existing.version != entry.version:
            ledger.update(existing.install_id, expected_revision=existing.revision, now=stamp, version=entry.version, digest=_digest())
            result.updated += 1
        return
    publisher, plugin_id = entry.id.split("/", 1)
    ledger.insert(InstalledItem(
        install_id=uuid.uuid4().hex, item_id=entry.id, kind=KIND_CPLUG, publisher=publisher, name=f"{NAME_PREFIX}{plugin_id}",
        version=entry.version, digest=_digest(), scope=SCOPE_GLOBAL, project_path=GLOBAL_PROJECT_PATH, auto_update=False,
        source_index_url=BUILTIN_SOURCE, consented_digest=None, consented_body_sha=None, publisher_key_id=BUILTIN_SOURCE,
        revision=1, installed_at=stamp, updated_at=stamp, consent_via=CONSENT_ONE_CLICK))
    result.adopted += 1


def adopt_builtin_plugins(services: Any) -> AdoptionResult:
    result = AdoptionResult()
    try:
        entries = builtins.plugin_entries(builtins.PLUGINS_ROOT)
        stamp = iso_from(services.clock)
        with services.catalog.ledger() as ledger:
            for entry in entries:
                try:
                    _adopt_one(ledger, entry, stamp, result)
                except (LedgerError, sqlite3.Error) as exc:
                    result.failed += 1
                    logger.warning("cplug_adoption_failed", cplug=entry.id, error=type(exc).__name__, detail=str(exc)[:200])
    except (LedgerError, sqlite3.Error, OSError, ValueError) as exc:
        result.failed += 1
        logger.warning("cplug_adoption_failed", cplug="*", error=type(exc).__name__, detail=str(exc)[:200])
    if result.adopted or result.updated:
        logger.info("cplug_adoption_done", adopted=result.adopted, updated=result.updated, failed=result.failed)
    return result


async def run_adoption_pass(services: Any) -> AdoptionResult:
    return await asyncio.to_thread(adopt_builtin_plugins, services)
