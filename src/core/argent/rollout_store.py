
from __future__ import annotations

import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core.argent import store

RUNNING, PAUSED, CANCELLED, DONE = "running", "paused", "cancelled", "done"
PENDING, PARKED, RESTARTED, FAILED, EXCLUDED = "pending", "parked", "restarted", "failed", "excluded"
OPEN_ROW_STATES = (PENDING,)


def current(tenant_id: str, *, state_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with closing(store.open_db(state_dir)) as conn:
        row = conn.execute("SELECT epoch, direction, state, reason, started_at, updated_at FROM rollout WHERE tenant_id = ?", (tenant_id,)).fetchone()
    return dict(row) if row else None


def start(tenant_id: str, direction: str, *, state_dir: Optional[Path] = None, clock: Callable[[], float] = time.time) -> int:
    now = float(clock())
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        prev = conn.execute("SELECT epoch FROM rollout WHERE tenant_id = ?", (tenant_id,)).fetchone()
        epoch = int(prev[0]) + 1 if prev else 1
        conn.execute("DELETE FROM rollout_rows WHERE tenant_id = ?", (tenant_id,))
        conn.execute("INSERT INTO rollout (tenant_id, epoch, direction, state, reason, started_at, updated_at) VALUES (?, ?, ?, ?, '', ?, ?) "
                     "ON CONFLICT(tenant_id) DO UPDATE SET epoch = excluded.epoch, direction = excluded.direction, state = excluded.state, "
                     "reason = '', started_at = excluded.started_at, updated_at = excluded.updated_at", (tenant_id, epoch, direction, RUNNING, now, now))
        conn.execute("COMMIT")
    return epoch


def set_state(tenant_id: str, epoch: int, state: str, reason: str = "", *, state_dir: Optional[Path] = None, clock: Callable[[], float] = time.time) -> bool:
    with closing(store.open_db(state_dir)) as conn:
        cur = conn.execute("UPDATE rollout SET state = ?, reason = ?, updated_at = ? WHERE tenant_id = ? AND epoch = ?", (state, reason, float(clock()), tenant_id, epoch))
        return cur.rowcount == 1


def ensure_row(tenant_id: str, epoch: int, name: str, *, state_dir: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
    now = float(clock())
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("INSERT OR IGNORE INTO rollout_rows (tenant_id, epoch, tmux_name, state, reason, first_seen, updated_at) VALUES (?, ?, ?, ?, '', ?, ?)",
                     (tenant_id, epoch, name, PENDING, now, now))


def set_row(tenant_id: str, epoch: int, name: str, state: str, reason: str = "", *, state_dir: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("UPDATE rollout_rows SET state = ?, reason = ?, updated_at = ? WHERE tenant_id = ? AND epoch = ? AND tmux_name = ?",
                     (state, reason, float(clock()), tenant_id, epoch, name))


def rows(tenant_id: str, epoch: int, *, state_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    with closing(store.open_db(state_dir)) as conn:
        return [dict(r) for r in conn.execute("SELECT tmux_name, state, reason, first_seen, updated_at FROM rollout_rows WHERE tenant_id = ? AND epoch = ? "
                                              "ORDER BY first_seen, tmux_name", (tenant_id, epoch))]
