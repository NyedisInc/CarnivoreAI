"""THE ADOPTION PASS (docs/warez/05, section 3): record every compiled-in plugin as an installed built-in, and move nothing.

At boot, beside ``ensure_required``, each plugin on the ship list that has no install-ledger row gets one: kind ``cplug``, item
``nyedis/<id>``, version from its manifest, source ``builtin``. The rows are what lets warez later offer an update for a plugin
that is already running; until then they are inert.

- it never writes ``<state_dir>/cplugs/state.json`` or anything else under ``<state_dir>/cplugs/``, so every plugin's switch,
  grants, settings and data read exactly as before (a plugin with no state entry still follows ``default_enabled``);
- it never changes a plugin's on/off state, copies a byte of code, or restarts anything;
- it is idempotent: a second run on the same build writes nothing;
- it is inert on failure: a ledger error is logged as a warning (``cplug_adoption_failed``) and boot goes on;
- it is reversible: ``python3 -m scripts.warez.unadopt`` deletes the rows whose source is ``builtin`` (one statement).

The ledger's ``UNIQUE(name, ...)`` key is shared with skills, and the Task Manager plugin and the bundled ``huddle`` skill
share a name, so a plugin row's ``name`` is ``cplug-<id>``; its ``item_id`` stays ``nyedis/<id>``.
"""

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
