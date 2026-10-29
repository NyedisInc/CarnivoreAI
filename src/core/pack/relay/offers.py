
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Collection, Dict, List, Optional

import structlog

from src.core.computers import direction
from src.core.pack.relay import consent as consent_mod, targets

logger = structlog.get_logger()


def local_offers(open_db: Callable[[], sqlite3.Connection], auth_config_file: str) -> List[Dict[str, str]]:
    from src.core.provider_ledger import accounts_store

    try:
        rows = [a for a in accounts_store.list_accounts(Path(auth_config_file).expanduser()) if a.provider == "claude"]
        with closing(open_db()) as conn:
            return consent_mod.clean_offers([{"account_key": a.id, "label": a.name} for a in rows
                                             if targets.effective_on(conn, a.id)])
    except (OSError, ValueError, sqlite3.Error):
        return []


def peer_offers(entries: Dict[str, Any], paired: Optional[Collection[str]] = None) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for iid, entry in sorted(entries.items()):
        snapshot = getattr(entry, "snapshot", None)
        if not isinstance(snapshot, dict) or (paired is not None and iid not in paired) or direction.contained(iid) or not consent_mod.SENDER_RE.fullmatch(iid):
            continue
        for offer in consent_mod.clean_offers(snapshot.get("credential_offers")):
            out.append({"key": consent_mod.offer_key(iid, offer["account_key"]), "sender": iid,
                        "sender_label": str(getattr(entry, "label", "") or "")[:64], **offer})
    return out


def view(entries: Dict[str, Any], current: consent_mod.Consent, receiving_on: bool,
         paired: Optional[Collection[str]] = None) -> Dict[str, Any]:
    offers = peer_offers(entries, paired)
    waiting = set(consent_mod.pending(current, [o["key"] for o in offers]))
    return {"mode": current.mode, "answered": current.mode is not None, "may_receive_credentials": receiving_on,
            "accepted": list(current.accounts),
            "offers": [{**o, "accepted": consent_mod.accepts(current, o["sender"], o["account_key"]),
                        "pending": o["key"] in waiting} for o in offers],
            "pending": [o["key"] for o in offers if o["key"] in waiting]}


def signature(entries: Dict[str, Any], peer_id: str) -> Any:
    entry = entries.get(peer_id)
    snapshot = getattr(entry, "snapshot", None)
    return (str(getattr(entry, "label", "") or ""), tuple((o["account_key"], o["label"]) for o in consent_mod.clean_offers(
        snapshot.get("credential_offers") if isinstance(snapshot, dict) else None)))


def revoke_keys(keys: List[str]) -> int:
    from src.core.pack.relay import target_side  # noqa: PLC0415

    removed = 0
    for key in keys:
        sender, _, account = key.rpartition(":")
        try:
            removed += bool(target_side.revoke(sender, account))
        except target_side.RelayRefused as exc:
            logger.warning("pack_relay_consent_revoke_failed", sender=sender, account=account, code=exc.code)
    return removed
