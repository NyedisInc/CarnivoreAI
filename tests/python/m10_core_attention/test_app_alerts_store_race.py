
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, List

import pytest

from src.core.app_alerts import conditions, store
from src.core.app_alerts import constants as K
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    return db_path_for(state)


class _Hooked:

    def __init__(self, conn: sqlite3.Connection, hook: Any) -> None:
        self._conn, self._hook = conn, hook

    def execute(self, sql: str, *args: Any) -> Any:
        cur = self._conn.execute(sql, *args)
        if sql.lstrip().upper().startswith("SELECT ID") and self._hook is not None:
            rows = cur.fetchall()
            hook, self._hook = self._hook, None
            hook()
            return _Rows(rows)
        return cur


class _Rows:
    def __init__(self, rows: List[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> List[Any]:
        return self._rows


def _dismiss_from_other_connection(db: Path, alert_id: int, landed: List[bool]) -> None:
    other = sqlite3.connect(str(db), timeout=0, isolation_level=None)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.execute(f"UPDATE {K.TABLE} SET state = ?, snoozed_until = NULL WHERE id = ?",
                      (K.STATE_DISMISSED, alert_id))
        other.execute("COMMIT")
        landed.append(True)
    except sqlite3.OperationalError:
        pass
    finally:
        other.close()


def _state(db: Path, alert_id: int) -> str:
    conn = connect(db, create=False)
    try:
        return conn.execute(f"SELECT state FROM {K.TABLE} WHERE id = ?", (alert_id,)).fetchone()[0]
    finally:
        conn.close()


def _snoozed(db: Path) -> int:
    conn = connect(db, create=False)
    spec = store.AlertSpec(key="x.k", source="t", severity="warn", title_key="app_alert.pipeline.llm_all_down.title")
    row, _ = store.raise_alert(conn, spec)
    store.snooze(conn, row["id"], 1)
    conn.close()
    return row["id"]


def test_wake_does_not_undo_a_racing_dismiss(db: Path) -> None:
    from datetime import datetime, timedelta, timezone
    rid = _snoozed(db)
    landed: List[bool] = []
    conn = connect(db, create=False)
    late = datetime.now(timezone.utc) + timedelta(hours=1)
    hooked = _Hooked(conn, lambda: _dismiss_from_other_connection(db, rid, landed))
    store.wake_snoozed(hooked, now=late)  # type: ignore[arg-type]
    conn.close()
    assert _state(db, rid) == (K.STATE_DISMISSED if landed else K.STATE_ACTIVE)


def test_resolve_does_not_undo_a_racing_dismiss(db: Path) -> None:
    conn = connect(db, create=False)
    spec = store.AlertSpec(key="x.r", source="t", severity="warn", title_key="app_alert.pipeline.llm_all_down.title")
    row, _ = store.raise_alert(conn, spec)
    rid = row["id"]
    landed: List[bool] = []
    store.resolve(_Hooked(conn, lambda: _dismiss_from_other_connection(db, rid, landed)), "x.r")  # type: ignore[arg-type]
    conn.close()
    assert _state(db, rid) == (K.STATE_DISMISSED if landed else K.STATE_RESOLVED)


def test_overrunning_probe_is_not_resubmitted(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    calls: List[int] = []

    def hung() -> None:
        calls.append(1)
        gate.wait(5)

    key = "m10.hung"
    conditions.register_condition(key, hung, 1.0, source="t")  # type: ignore[arg-type]
    try:
        for tick in (10.0, 20.0, 30.0):
            conditions.run_due(now=tick, budget=0.05)
        assert len(calls) == 1
    finally:
        gate.set()
        conditions.unregister_condition(key)
