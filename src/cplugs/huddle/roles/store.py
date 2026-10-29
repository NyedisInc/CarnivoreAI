
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Collection, ContextManager, Dict, FrozenSet, Optional

from src.cplugs.huddle.roles import lead

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore


class SeatTaken(Exception):

    def __init__(self, holder: str) -> None:
        super().__init__(f"the lead seat is held by {holder}")
        self.holder = holder


class LeadCannotDnd(Exception):
    pass


class RoleStore:

    def __init__(self, store: "TaskManagerStore") -> None:
        self._store = store

    def read_scope(self) -> ContextManager[None]:
        return self._store.read_scope()

    @staticmethod
    def _seat_of(row: Optional[tuple], list_key: str) -> lead.Seat:
        if row is None:
            return lead.Seat(list_key)
        return lead.Seat(list_key, lead_key=row[0], lead_by=row[1], lead_at=float(row[2]), ever_led=bool(row[3]))

    def seat(self, list_key: str) -> lead.Seat:
        with closing(self._store._read_connection()) as conn:
            return self._read_seat(conn, list_key)

    @classmethod
    def _read_seat(cls, conn: sqlite3.Connection, list_key: str) -> lead.Seat:
        row = conn.execute("SELECT lead_key, lead_by, lead_at, ever_led FROM work_project_roles WHERE list_key = ?", (list_key,)).fetchone()
        return cls._seat_of(tuple(row) if row else None, list_key)

    def seats(self) -> Dict[str, lead.Seat]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute("SELECT list_key, lead_key, lead_by, lead_at, ever_led FROM work_project_roles").fetchall()
        return {r[0]: self._seat_of(tuple(r[1:]), r[0]) for r in rows}

    def dnd_keys(self) -> FrozenSet[str]:
        with closing(self._store._read_connection()) as conn:
            return frozenset(r[0] for r in conn.execute("SELECT session_uuid FROM work_session_prefs WHERE dnd = 1"))

    def set_dnd(self, session_key: str, on: bool, also_leads: Collection[str] = ()) -> bool:
        with closing(self._store._connect(True)) as conn, conn:
            if on and (session_key in also_leads or conn.execute("SELECT 1 FROM work_project_roles WHERE lead_key = ?", (session_key,)).fetchone()):
                raise LeadCannotDnd(session_key)
            conn.execute("INSERT INTO work_session_prefs (session_uuid, nudge, dnd, updated_at) VALUES (?, NULL, ?, ?) "
                         "ON CONFLICT(session_uuid) DO UPDATE SET dnd = excluded.dnd, updated_at = excluded.updated_at",
                         (session_key, int(on), self._store._clock()))
        return on

    def set_lead(self, list_key: str, session_key: str, by: str) -> lead.Seat:
        now = self._store._clock()
        with closing(self._store._connect(True)) as conn:
            with conn:
                self._write_seat(conn, list_key, session_key, by if session_key else "", now)
            return self._read_seat(conn, list_key)

    @staticmethod
    def _write_seat(conn: sqlite3.Connection, list_key: str, session_key: str, by: str, now: float) -> None:
        conn.execute(
            "INSERT INTO work_project_roles (list_key, lead_key, lead_by, lead_at, ever_led) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(list_key) DO UPDATE SET lead_key = excluded.lead_key, lead_by = excluded.lead_by, lead_at = excluded.lead_at, "
            "ever_led = MAX(ever_led, excluded.ever_led)", (list_key, session_key, by, now, int(bool(session_key))))
        if session_key:
            conn.execute("UPDATE work_session_prefs SET dnd = 0, updated_at = ? WHERE session_uuid = ? AND dnd = 1", (now, session_key))

    def take_if_vacant(self, list_key: str, session_key: str, live_keys: Collection[str], asleep_keys: Collection[str], by: str,
                       present_keys: Collection[str] = ()) -> lead.Seat:
        with closing(self._store._connect(True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                row = conn.execute("SELECT lead_key, lead_by, lead_at, ever_led FROM work_project_roles WHERE list_key = ?", (list_key,)).fetchone()
                current = self._seat_of(tuple(row) if row else None, list_key)
                if by == lead.BY_AUTO and current.ever_led:
                    raise SeatTaken(current.lead_key)
                if not lead.may_take(current, live_keys, asleep_keys, session_key, present_keys):
                    raise SeatTaken(current.lead_key)
                self._write_seat(conn, list_key, session_key, by, self._store._clock())
            return self._read_seat(conn, list_key)
