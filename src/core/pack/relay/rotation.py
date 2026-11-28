
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.core.pack.relay import removed_copies
from src.core.provider_ledger.poller_scan import AUTO_DEFAULT_ACCOUNT_ID as AUTO_DEFAULT

PROVIDERS = ("claude", "codex")
SEEN_MARGIN_MS = 60_000
_DDL = """CREATE TABLE IF NOT EXISTS pack_rotation (
    account_id      TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    started_at      INTEGER NOT NULL,
    deadline_before INTEGER,
    identity_hash   TEXT
)"""
NOT_STARTED, NOT_CHECKABLE, OTHER_ACCOUNT, SEEN, NOT_SEEN = "not_started", "not_checkable", "other_account", "seen", "not_seen"


def _exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pack_rotation'").fetchone() is not None


def read_rows(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    if not _exists(conn):
        return {}
    return {r[0]: {"provider": r[1], "started_at": int(r[2]), "deadline_before": r[3], "identity_hash": r[4]}
            for r in conn.execute("SELECT account_id, provider, started_at, deadline_before, identity_hash FROM pack_rotation")}


def deadline_ms(usage: Any) -> Optional[int]:
    if usage is None or usage.provider != "claude" or usage.credential_state not in ("ok", "expired") or usage.login_expires_at is None:
        return None
    return int(usage.login_expires_at.timestamp() * 1000)


def identity_hash(usage: Any) -> Optional[str]:
    ident = None if usage is None else usage.identity
    return hashlib.sha256(ident.encode("utf-8")).hexdigest() if ident else None


def record_start(conn: sqlite3.Connection, account_id: str, provider: str, now_ms: int, usage: Any) -> int:
    conn.execute(_DDL)
    conn.execute("INSERT OR REPLACE INTO pack_rotation (account_id, provider, started_at, deadline_before, identity_hash) VALUES (?, ?, ?, ?, ?)",
                 (account_id, provider, now_ms, deadline_ms(usage), identity_hash(usage)))
    conn.commit()
    return now_ms


def sign_in_seen(row: Optional[Dict[str, Any]], usage: Any) -> str:
    if row is None:
        return NOT_STARTED
    if row["provider"] != "claude" or row["deadline_before"] is None:
        return NOT_CHECKABLE
    if row["identity_hash"] != identity_hash(usage):
        return OTHER_ACCOUNT
    now_deadline = deadline_ms(usage)
    return SEEN if now_deadline is not None and now_deadline > int(row["deadline_before"]) + SEEN_MARGIN_MS else NOT_SEEN


def seen_fn(rows: Dict[str, Dict[str, Any]], usage_by_id: Dict[str, Any]) -> Callable[[str], Optional[int]]:
    def seen(account_id: str) -> Optional[int]:
        row = rows.get(account_id)
        return row["started_at"] if row is not None and sign_in_seen(row, usage_by_id.get(account_id)) == SEEN else None
    return seen


def seen_from(open_db: Callable[[], sqlite3.Connection], usage: Iterable[Any]) -> Callable[[str], Optional[int]]:
    with closing(open_db()) as conn:
        return seen_fn(read_rows(conn), {u.id: u for u in usage})


def _row(c: Dict[str, Any], iid: str, label: Optional[str] = None) -> Dict[str, Any]:
    return {"install_id": iid, "label": label, "status": c["status"], "expires_at": c["expires_at"], "killed_at": c["killed_at"], "ended_by": c["ended_by"]}


def walk(open_db: Callable[[], sqlite3.Connection], accounts: Iterable[Any], usage_by_id: Dict[str, Any], argent: Optional[removed_copies.ArgentFn],
         now_ms: int) -> Dict[str, Any]:
    stored: List[Any] = [a for a in accounts if a.provider in PROVIDERS]
    listed = [(a.id, a.name, a.provider, "app") for a in stored]
    auto = usage_by_id.get(AUTO_DEFAULT)
    if auto is not None and auto.provider == "claude" and all(a.id != AUTO_DEFAULT for a in stored):
        listed.append((AUTO_DEFAULT, auto.name, "claude", "terminal"))
    with closing(open_db()) as conn:
        rows = read_rows(conn)
        answer = removed_copies.build(open_db, argent, now_ms, seen_fn(rows, usage_by_id))
    by_account: Dict[str, List[Dict[str, Any]]] = {}
    argent_copies: List[Dict[str, Any]] = []
    by_unlisted: Dict[Any, List[Dict[str, Any]]] = {}
    listed_ids = {entry[0] for entry in listed}
    for comp in answer["computers"]:
        for c in comp["copies"]:
            if c["kind"] == "argent":
                argent_copies.append(_row(c, comp["install_id"], comp.get("label")))
            elif c["account"] in listed_ids:
                by_account.setdefault(c["account"], []).append(_row(c, comp["install_id"], comp.get("label")))
            elif c["account"] is not None:
                by_unlisted.setdefault((c["account"], c["kind"]), []).append(_row(c, comp["install_id"], comp.get("label")))
    out = []
    unlisted = [{"account": aid, "provider": kind, "copies": cs} for (aid, kind), cs in sorted(by_unlisted.items())]
    for aid, name, provider, sign_in in listed:
        row = rows.get(aid)
        out.append({"account": aid, "name": name, "provider": provider, "sign_in": sign_in,
                    "started_at": None if row is None else row["started_at"], "sign_in_seen": sign_in_seen(row, usage_by_id.get(aid)),
                    "sign_in_ends": removed_copies.SIGN_IN_ENDS.get(provider, "unknown"), "copies": by_account.get(aid, [])})
    return {"accounts": out, "argent": {"known": answer["argent_known"], "copies": argent_copies}, "removed_computers": len(answer["computers"]),
            "unlisted": unlisted, "not_tracked": answer["not_tracked"]}
