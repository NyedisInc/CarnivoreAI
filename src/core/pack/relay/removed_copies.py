
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.computers import mesh_removal
from src.core.db import transaction
from src.core.federation import peer_hosts

log = structlog.get_logger(__name__)

DIES_BY, EXPIRED, EXPIRY_UNKNOWN, DEAD_NOW = "dies_by", "expired", "expiry_unknown", "dead_now"
NOT_TRACKED = ["github"]
_CODEX_SUFFIX = "-relay-codex"
SIGN_IN_ENDS: Dict[str, str] = {"claude": "unknown", "codex": "unknown"}
ArgentFn = Callable[[str, int], List[Dict[str, Any]]]


def status_for(expires_at_ms: Optional[int], now_ms: int) -> str:
    if expires_at_ms is None:
        return EXPIRY_UNKNOWN
    return EXPIRED if expires_at_ms <= now_ms else DIES_BY


def removed_computers(conn: sqlite3.Connection) -> List[Tuple[str, str, int]]:
    out: List[Tuple[str, str, int]] = []
    for iid, row in mesh_removal.read_rows(conn).items():
        if row.state not in (mesh_removal.REMOVED, mesh_removal.PURGED) or row.removed_at is None:
            continue
        if peer_hosts.get(conn, iid) is not None:
            continue
        out.append((iid, row.state, int(row.removed_at * 1000)))
    return out


_RECORDS_DDL = """CREATE TABLE IF NOT EXISTS pack_relay_removed_copies (
    target_install_id TEXT NOT NULL,
    account_key       TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('claude', 'codex')),
    expires_at        INTEGER NOT NULL,
    pushed_at         REAL NOT NULL,
    PRIMARY KEY (target_install_id, account_key, kind)
)"""


def _records_exist(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pack_relay_removed_copies'").fetchone() is not None


def keep_records(conn: sqlite3.Connection, rows: Iterable[Tuple[str, str, str, int, float]]) -> None:
    with transaction(conn):
        conn.execute(_RECORDS_DDL)
        conn.executemany("INSERT INTO pack_relay_removed_copies (target_install_id, account_key, kind, expires_at, pushed_at) VALUES (?, ?, ?, ?, ?) "
                         "ON CONFLICT(target_install_id, account_key, kind) DO UPDATE SET expires_at = excluded.expires_at, pushed_at = excluded.pushed_at "
                         "WHERE excluded.pushed_at >= pack_relay_removed_copies.pushed_at", list(rows))


def prune_records(conn: sqlite3.Connection, now_ms: int) -> int:
    if not _records_exist(conn):
        return 0
    with transaction(conn):
        return conn.execute("DELETE FROM pack_relay_removed_copies WHERE expires_at <= ?", (now_ms,)).rowcount


def relay_copies(conn: sqlite3.Connection, iid: str, now_ms: int) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT account_key, target_profile, last_expiry_pushed, last_push_at FROM pack_relay_targets "
                        "WHERE target_install_id = ? AND last_push_at IS NOT NULL", (iid,)).fetchall()
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for account, profile, expiry, pushed in rows:
        kind = "codex" if str(profile).endswith(_CODEX_SUFFIX) else "claude"
        merged[(kind, str(account))] = {"kind": kind, "account": str(account), "expires_at": None if expiry is None else int(expiry), "pushed_at": int(pushed * 1000)}
    if _records_exist(conn):
        for account, kind, expiry, pushed in conn.execute("SELECT account_key, kind, expires_at, pushed_at FROM pack_relay_removed_copies "
                                                          "WHERE target_install_id = ? AND expires_at > ?", (iid, now_ms)).fetchall():
            kept = {"kind": str(kind), "account": str(account), "expires_at": int(expiry), "pushed_at": int(pushed * 1000)}
            if (str(kind), str(account)) not in merged or kept["pushed_at"] > merged[(str(kind), str(account))]["pushed_at"]:
                merged[(str(kind), str(account))] = kept
    return list(merged.values())


def _copy(kind: str, account: Optional[str], expires_at: Optional[int], killed_at: Optional[int], now_ms: int,
          pushed_at: Optional[int] = None, seen: Optional[Callable[[str], Optional[int]]] = None) -> Dict[str, Any]:
    ended_by: Optional[str] = None
    if killed_at is not None:
        status, ended_by = DEAD_NOW, "argent_204"
    else:
        status = status_for(expires_at, now_ms)
        started = seen(account) if (seen is not None and account is not None and pushed_at is not None and SIGN_IN_ENDS.get(kind) == "ends") else None
        if started is not None and pushed_at < started:
            status, ended_by = DEAD_NOW, "sign_in"
    return {"kind": kind, "account": account, "status": status, "expires_at": expires_at, "killed_at": killed_at, "ended_by": ended_by}


KILL_MARGIN_MS = 60_000


def build(open_db: Callable[[], sqlite3.Connection], argent: Optional[ArgentFn], now_ms: int,
          seen: Optional[Callable[[str], Optional[int]]] = None) -> Dict[str, Any]:
    computers: List[Dict[str, Any]] = []
    argent_known = argent is not None
    with closing(open_db()) as conn:
        labels = {i: r.label for i, r in mesh_removal.read_rows(conn).items()}
        for iid, state, removed_at in sorted(removed_computers(conn), key=lambda r: -r[2]):
            copies = [_copy(c["kind"], c["account"], c["expires_at"], None, now_ms, c["pushed_at"], seen) for c in relay_copies(conn, iid, now_ms)]
            if argent is not None and argent_known:
                try:
                    copies += [_copy("argent", None, c["expires_at"], c["killed_at"], now_ms) for c in argent(iid, removed_at - KILL_MARGIN_MS)]
                except (sqlite3.Error, OSError, ValueError) as exc:
                    log.warning("pack_removed_logins_argent_unreadable", error=type(exc).__name__)
                    argent_known = False
                    copies = [c for c in copies if c["kind"] != "argent"]
                    for done in computers:
                        done["copies"] = [c for c in done["copies"] if c["kind"] != "argent"]
                    computers = [d for d in computers if d["copies"]]
            copies.sort(key=lambda c: (c["kind"], c["account"] or "", c["expires_at"] if c["expires_at"] is not None else -1))
            if copies:
                computers.append({"install_id": iid, "removed_at": removed_at, "state": state, "label": labels.get(iid) or None, "copies": copies})
    return {"computers": computers, "argent_known": argent_known, "not_tracked": list(NOT_TRACKED)}
