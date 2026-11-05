
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from src.core.pack.relay import ledger_sync_view
from src.core.provider_ledger import relay_accounts
from src.models.provider_ledger import AccountUsage, LedgerSnapshot

MAX_SYNC_AGE = timedelta(seconds=900)

MIN_EXPIRY_MARGIN = timedelta(seconds=600)


def usable(row: AccountUsage, now: datetime) -> bool:
    if not row.relayed or row.provider != "claude" or row.fetched_at is None or row.synced_at is None:
        return False
    if now - row.fetched_at > MAX_SYNC_AGE or now - row.synced_at > MAX_SYNC_AGE:
        return False
    return row.relay_expires_at is not None and row.relay_expires_at - now >= MIN_EXPIRY_MARGIN


def with_relayed(snapshot: LedgerSnapshot, now: datetime) -> LedgerSnapshot:
    rows: List[AccountUsage] = [r for r in relay_accounts.relay_rows(now) if usable(r, now)]
    if not rows:
        return snapshot
    keys = ledger_sync_view.identity_keys([*snapshot.accounts, *rows])
    mine = {keys[a.id] for a in snapshot.accounts if keys.get(a.id)}
    extra = [r for r in rows if not (keys.get(r.id) and keys[r.id] in mine)]
    return snapshot.model_copy(update={"accounts": [*snapshot.accounts, *extra]}) if extra else snapshot
