
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, Optional

import structlog

from src.plugins.save.offload import constants as C, reconcile, run, target_folder
from src.plugins.save.offload.homes import claude_homes
from src.plugins.save.offload.ledger import Ledger, LedgerUnreadable
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault.location import VaultUnavailable
from src.plugins.save.vault.manifest import ManifestError
from src.plugins.save.vault.units import Scanner
from src.plugins.sdk import session_chains, transcript_files as tf

logger = structlog.get_logger()


def _on_disk_probe() -> Callable[[str], bool]:
    scanner = Scanner(RUNTIME.sources())

    def on_disk(conversation_id: str) -> bool:
        try:
            return scanner.plan_claude(conversation_id) is not None
        except (ManifestError, OSError) as exc:
            logger.warning("offload_start_probe_failed", conversation_id=conversation_id, error_type=type(exc).__name__)
            return False

    return on_disk


def tell_index_of_offloaded(ledger: Ledger) -> None:
    run.tell_index(e.conversation_id for e in ledger.read().values() if e.state == C.STATE_OFFLOADED)


def _resend() -> None:
    try:
        ledger = Ledger(RUNTIME.vault().root, Path(tf.state_dir()))
        tell_index_of_offloaded(ledger)
    except (VaultUnavailable, LedgerUnreadable, OSError) as exc:
        logger.warning("offload_start_resend_failed", error_type=type(exc).__name__, error=str(exc)[:200])


def resend_in_background() -> threading.Thread:
    thread = threading.Thread(target=_resend, name="offload-index-resend", daemon=True)
    thread.start()
    return thread


def _resume_folders(ledger: Ledger) -> Optional[Dict[str, str]]:
    try:
        return target_folder.resume_folders(session_chains.read_snapshot(), ledger.read())
    except session_chains.SessionChainsUnreadable as exc:
        logger.warning("offload_start_sessions_unreadable", error=str(exc)[:200])
        return None


def settle_on_start() -> None:
    try:
        vault = RUNTIME.vault()
    except VaultUnavailable as exc:
        logger.warning("offload_start_vault_unavailable", error=str(exc)[:200])
        return
    ledger = Ledger(vault.root, Path(tf.state_dir()))
    try:
        ledger.sync_marker(on_disk=_on_disk_probe())
        roots = RUNTIME.sources().claude_roots
        if roots:
            reconcile.reconcile(vault, ledger, claude_homes(roots), _resume_folders(ledger))
    except (LedgerUnreadable, OSError) as exc:
        logger.error("offload_start_failed", error_type=type(exc).__name__, error=str(exc)[:300])
