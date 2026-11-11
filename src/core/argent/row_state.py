
from __future__ import annotations

import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.argent import store

PENDING, NOT_TETHERED, TETHERED = "pending", "not tethered", "tethered"
NO_TRAFFIC_REASON = "gateway not reached"
TRAFFIC_GRACE_SECONDS = 90.0


def record_launch(tenant_id: str, session_ref: str, *, working_dir: str, tethered: bool, reason: str, key_id: str,
                  key_expires_at: float = 0.0, state_dir: Optional[Path] = None, clock: Any = time.time) -> None:
    now = float(clock())
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO row_state (tenant_id, session_ref, working_dir, pending_state, pending_reason, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(tenant_id, session_ref) DO UPDATE SET working_dir = excluded.working_dir, pending_state = excluded.pending_state, "
                     "pending_reason = excluded.pending_reason, updated_at = excluded.updated_at",
                     (tenant_id, session_ref, working_dir, PENDING if tethered else NOT_TETHERED, "" if tethered else reason, now))
        conn.execute("UPDATE row_keys SET status = 'stale' WHERE tenant_id = ? AND session_ref = ? AND status = 'pending'", (tenant_id, session_ref))
        if key_id:
            conn.execute("INSERT OR REPLACE INTO row_keys (tenant_id, session_ref, key_id, status, minted_at, key_expires_at) VALUES (?, ?, ?, 'pending', ?, ?)",
                         (tenant_id, session_ref, key_id, now, float(key_expires_at)))
        conn.execute("COMMIT")


def confirm(tenant_id: str, session_ref: str, *, state_dir: Optional[Path] = None, clock: Any = time.time) -> List[str]:
    with closing(store.open_db(state_dir)) as conn:
        row = conn.execute("SELECT pending_state, pending_reason FROM row_state WHERE tenant_id = ? AND session_ref = ?", (tenant_id, session_ref)).fetchone()
        if row is None or not row["pending_state"]:
            return []
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE row_keys SET status = 'stale' WHERE tenant_id = ? AND session_ref = ? AND status = 'live'", (tenant_id, session_ref))
        conn.execute("UPDATE row_keys SET status = 'live' WHERE tenant_id = ? AND session_ref = ? AND status = 'pending'", (tenant_id, session_ref))
        conn.execute("UPDATE row_state SET state = pending_state, reason = pending_reason, pending_state = '', pending_reason = '', "
                     "notified = CASE WHEN pending_state = ? THEN 0 ELSE notified END, updated_at = ? WHERE tenant_id = ? AND session_ref = ?",
                     (PENDING, float(clock()), tenant_id, session_ref))
        stale = [r[0] for r in conn.execute("SELECT key_id FROM row_keys WHERE tenant_id = ? AND session_ref = ? AND status = 'stale'", (tenant_id, session_ref))]
        conn.execute("COMMIT")
    return stale


def first_traffic(tenant_id: str, session_ref: str, *, seen: bool, unmetered_at: float, now: float, state_dir: Optional[Path] = None) -> str:
    if not seen and not (unmetered_at and now - unmetered_at >= TRAFFIC_GRACE_SECONDS):
        return ""
    new, reason = (TETHERED, "") if seen else (NOT_TETHERED, NO_TRAFFIC_REASON)
    with closing(store.open_db(state_dir)) as conn:
        cur = conn.execute("UPDATE row_state SET state = ?, reason = ?, updated_at = ? WHERE tenant_id = ? AND session_ref = ? AND state = ?",
                           (new, reason, now, tenant_id, session_ref, PENDING))
    return new if cur.rowcount == 1 else ""


def mint_epoch(tenant_id: str, session_ref: str, *, state_dir: Optional[Path] = None) -> float:
    with closing(store.open_db(state_dir)) as conn:
        value = conn.execute("SELECT MAX(minted_at) FROM row_keys WHERE tenant_id = ? AND session_ref = ? AND status = 'live'", (tenant_id, session_ref)).fetchone()[0]
    return float(value or 0.0)


def forget_key(tenant_id: str, session_ref: str, key_id: str, *, state_dir: Optional[Path] = None) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("DELETE FROM row_keys WHERE tenant_id = ? AND session_ref = ? AND key_id = ?", (tenant_id, session_ref, key_id))


def drop_keys(tenant_id: str, session_ref: str, *, state_dir: Optional[Path] = None) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("DELETE FROM row_keys WHERE tenant_id = ? AND session_ref = ?", (tenant_id, session_ref))


def claim_notice(tenant_id: str, session_ref: str, *, state_dir: Optional[Path] = None) -> bool:
    with closing(store.open_db(state_dir)) as conn:
        cur = conn.execute("UPDATE row_state SET notified = 1 WHERE tenant_id = ? AND session_ref = ? AND notified = 0", (tenant_id, session_ref))
        return cur.rowcount == 1


def rows(tenant_id: str, *, state_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    with closing(store.open_db(state_dir)) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT session_ref, working_dir, state, reason FROM row_state WHERE tenant_id = ? AND state != '' ORDER BY session_ref", (tenant_id,))]


def clear(tenant_id: str, session_ref: str, *, state_dir: Optional[Path] = None) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("DELETE FROM row_state WHERE tenant_id = ? AND session_ref = ?", (tenant_id, session_ref))


def lookup(tenant_id: str, tmux_name: str, *, state_dir: Optional[Path] = None) -> Dict[str, str]:
    with closing(store.open_db(state_dir)) as conn:
        alias = conn.execute("SELECT session_ref FROM ref_alias WHERE tenant_id = ? AND tmux_name = ?", (tenant_id, tmux_name)).fetchone()
        ref = str(alias[0]) if alias else tmux_name
        row = conn.execute("SELECT state, reason FROM row_state WHERE tenant_id = ? AND session_ref = ?", (tenant_id, ref)).fetchone()
    return {"ref": ref, "state": str(row["state"]) if row else "", "reason": str(row["reason"]) if row else ""}
