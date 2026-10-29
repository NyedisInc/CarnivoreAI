
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import structlog

from src.core.db import transaction
from src.core.skills.loadout_members import MEMBER_STATES, MemberOutcome

logger = structlog.get_logger()

MEMBER_COLUMNS: Tuple[str, ...] = (
    "install_id",
    "item_id",
    "version",
    "state",
    "member_install_id",
    "detail",
)

_MEMBER_SELECT = (
    f"SELECT {', '.join(MEMBER_COLUMNS)} FROM installed_loadout_members"
)


@dataclass(frozen=True)
class LoadoutMemberRow:

    install_id: str
    item_id: str
    version: str
    state: str
    member_install_id: Optional[str]
    detail: Optional[str]


def row_to_member(row: sqlite3.Row) -> LoadoutMemberRow:
    return LoadoutMemberRow(
        install_id=str(row["install_id"]),
        item_id=str(row["item_id"]),
        version=str(row["version"]),
        state=str(row["state"]),
        member_install_id=(
            None
            if row["member_install_id"] is None
            else str(row["member_install_id"])
        ),
        detail=None if row["detail"] is None else str(row["detail"]),
    )


class LoadoutLedger:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


    def members(self, install_id: str) -> Tuple[LoadoutMemberRow, ...]:
        rows = self._conn.execute(
            f"{_MEMBER_SELECT} WHERE install_id = ? ORDER BY item_id ASC",
            (install_id,),
        ).fetchall()
        return tuple(row_to_member(row) for row in rows)

    def claims(
        self, item_id: str, *, excluding: Optional[str] = None
    ) -> Tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT install_id FROM installed_loadout_members "
            "WHERE item_id = ? AND state != 'refused' "
            "ORDER BY install_id ASC",
            (item_id,),
        ).fetchall()
        found = tuple(str(row["install_id"]) for row in rows)
        if excluding is None:
            return found
        return tuple(value for value in found if value != excluding)

    def unclaimed(self, install_id: str) -> Tuple[LoadoutMemberRow, ...]:
        offered: list[LoadoutMemberRow] = []
        for row in self.members(install_id):
            if row.state == "refused":
                continue
            if self.claims(row.item_id, excluding=install_id):
                continue
            offered.append(row)
        return tuple(offered)


    def record(
        self, install_id: str, outcomes: Iterable[MemberOutcome]
    ) -> Tuple[LoadoutMemberRow, ...]:
        prepared = list(outcomes)
        for outcome in prepared:
            if outcome.state not in MEMBER_STATES:
                raise ValueError(
                    f"unknown member state {outcome.state!r}; known states "
                    f"are {sorted(MEMBER_STATES)}"
                )

        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM installed_loadout_members WHERE install_id = ?",
                (install_id,),
            )
            for outcome in prepared:
                self._conn.execute(
                    "INSERT INTO installed_loadout_members "
                    f"({', '.join(MEMBER_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        install_id,
                        outcome.item_id,
                        outcome.version,
                        outcome.state,
                        outcome.install_id,
                        outcome.detail,
                    ),
                )
        stored = self.members(install_id)
        logger.info(
            "loadout_membership_recorded",
            install_id=install_id,
            members=len(stored),
            refused=sum(1 for row in stored if row.state == "refused"),
        )
        return stored
