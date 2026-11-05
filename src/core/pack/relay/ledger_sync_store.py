
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.core.pack.relay.codex_target import codex_relay_profile_name
from src.core.pack.relay.ledger_sync_wire import LedgerSessionsBody, LedgerStatusBody
from src.core.pack.relay.target_side import relay_profile_name

logger = structlog.get_logger()

PATH: Optional[Callable[[], Path]] = None

_DDL = """CREATE TABLE IF NOT EXISTS pack_ledger_sync (
    kind        TEXT NOT NULL CHECK (kind IN ('status', 'sessions')),
    sender      TEXT NOT NULL,
    provider    TEXT NOT NULL,
    account_key TEXT NOT NULL,
    body        TEXT NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY (kind, sender, provider, account_key)
)"""


@dataclass(frozen=True)
class StoredStatus:

    sender: str
    body: LedgerStatusBody
    received_at: float


@dataclass(frozen=True)
class StoredSessions:

    sender: str
    body: LedgerSessionsBody
    received_at: float


def _connect() -> Optional[sqlite3.Connection]:
    if PATH is None:
        return None
    path = PATH()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute(_DDL)
    return conn


def _save(kind: str, sender: str, provider: str, key: str, body_json: str, now: Optional[float]) -> None:
    conn = _connect()
    if conn is None:
        return
    with closing(conn), conn:
        conn.execute("INSERT OR REPLACE INTO pack_ledger_sync VALUES (?, ?, ?, ?, ?, ?)",
                     (kind, sender, provider, key, body_json, now if now is not None else time.time()))


def save_status(sender: str, body: LedgerStatusBody, now: Optional[float] = None) -> None:
    _save("status", sender, body.provider, body.account_key, body.model_dump_json(), now)


def save_sessions(sender: str, body: LedgerSessionsBody, now: Optional[float] = None) -> None:
    _save("sessions", sender, body.provider, body.account_key, body.model_dump_json(), now)


def forget(sender: str, provider: str, account_key: str) -> None:
    conn = _connect()
    if conn is None:
        return
    with closing(conn), conn:
        conn.execute("DELETE FROM pack_ledger_sync WHERE sender = ? AND provider = ? AND account_key = ?", (sender, provider, account_key))


def _rows(kind: str) -> List[Tuple[str, str, str, str, float]]:
    conn = _connect()
    if conn is None:
        return []
    with closing(conn):
        return conn.execute("SELECT sender, provider, account_key, body, received_at FROM pack_ledger_sync WHERE kind = ?", (kind,)).fetchall()


def statuses_by_profile() -> Dict[str, StoredStatus]:
    out: Dict[str, StoredStatus] = {}
    for sender, provider, key, body, at in _rows("status"):
        try:
            parsed = LedgerStatusBody.model_validate_json(body)
        except ValidationError:
            logger.warning("pack_ledger_sync_bad_stored_status", account=key)
            continue
        name = (codex_relay_profile_name if provider == "codex" else relay_profile_name)(key, sender)
        out[name] = StoredStatus(sender, parsed, at)
    return out


def sessions_reports(provider: str, account_key: str) -> List[StoredSessions]:
    out: List[StoredSessions] = []
    for sender, prov, key, body, at in _rows("sessions"):
        if prov != provider or key != account_key:
            continue
        try:
            out.append(StoredSessions(sender, LedgerSessionsBody.model_validate_json(body), at))
        except ValidationError:
            logger.warning("pack_ledger_sync_bad_stored_sessions", account=key)
    return out
