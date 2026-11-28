
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from src.plugins.save.offload import alerts, purge, scrub, settings
from src.plugins.save.offload.ledger import Ledger, LedgerUnreadable, offloaded_units
from src.plugins.save.offload.move import holding_root
from src.plugins.save.vault.store import Vault
from src.plugins.sdk.blob_codec import Throttle

logger = structlog.get_logger()


def _ledger_readable(ledger: Ledger, state_dir: Path, now: float) -> bool:
    readable = not offloaded_units(ledger.path.parent, state_dir=state_dir).unreadable
    alerts.record_ledger(state_dir, ledger.path, readable=readable, now=now)
    return readable


def run(vault: Vault, state_dir: Path, now: float, pace: Optional[Throttle] = None) -> None:
    ledger = Ledger(vault.root, state_dir)
    if not _ledger_readable(ledger, state_dir, now):
        return
    try:
        if not ledger.path.exists():
            return
        if settings.is_enabled(state_dir):
            purge.run_purge(vault, ledger, holding_root(state_dir), now=now, pace=pace, allowed=lambda: settings.is_enabled(state_dir))
        if scrub.due(vault.root, now) and not (pace is not None and pace.cancelled):
            scrub.run_scrub(vault, ledger, now=now, pace=pace)
    except LedgerUnreadable as exc:
        logger.error("offload_upkeep_ledger_unreadable", error=str(exc)[:200])
    except (OSError, ValueError) as exc:
        logger.error("offload_upkeep_failed", error_type=type(exc).__name__, error=str(exc)[:200])
