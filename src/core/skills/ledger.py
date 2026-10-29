
from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Any, Iterable, List, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.catalog.log_safe import log_value
from src.core.db import transaction
from src.core.resource_push import topics as resource_topics
from src.core.skills.ledger_types import (  # noqa: F401
    GLOBAL_PROJECT_PATH,
    HARNESS_CLAUDE,
    HARNESS_CODEX,
    ITEM_COLUMNS,
    MUTABLE_COLUMNS,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    AlreadyInstalled,
    InstallNotFound,
    InstallTarget,
    InstalledItem,
    LedgerError,
    StaleRevision,
    as_dict,
    item_values,
    row_to_item,
)

logger = structlog.get_logger()

_ITEM_SELECT = f"SELECT {', '.join(ITEM_COLUMNS)} FROM installed_items"


class InstallLedger:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn


    def get(self, install_id: str) -> Optional[InstalledItem]:
        row = self._conn.execute(
            f"{_ITEM_SELECT} WHERE install_id = ?", (install_id,)
        ).fetchone()
        return None if row is None else row_to_item(row)


    def forked_ids(self) -> frozenset:
        return frozenset(
            r[0] for r in self._conn.execute(
                "SELECT install_id FROM installed_items WHERE forked = 1"))

    def set_forked(self, install_id: str, forked: bool) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE installed_items SET forked = ? WHERE install_id = ?",
                (1 if forked else 0, install_id))
            if cursor.rowcount == 0:
                raise InstallNotFound("no install row carries that id", install_id)

    def targets(self, install_id: str) -> Tuple[InstallTarget, ...]:
        rows = self._conn.execute(
            "SELECT install_id, harness, path FROM installed_item_targets "
            "WHERE install_id = ? ORDER BY path ASC",
            (install_id,),
        ).fetchall()
        return tuple(
            InstallTarget(
                install_id=str(row["install_id"]),
                harness=str(row["harness"]),
                path=str(row["path"]),
            )
            for row in rows
        )

    def list(
        self,
        *,
        scope: Optional[str] = None,
        project_path: Optional[str] = None,
    ) -> Tuple[InstalledItem, ...]:
        clauses: List[str] = []
        params: List[Any] = []
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if project_path is not None:
            clauses.append("project_path = ?")
            params.append(project_path)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"{_ITEM_SELECT}{where} ORDER BY name ASC, install_id ASC",
            tuple(params),
        ).fetchall()
        return tuple(row_to_item(row) for row in rows)

    def find(
        self, item_id: str, scope: str, project_path: str
    ) -> Optional[InstalledItem]:
        row = self._conn.execute(
            f"{_ITEM_SELECT} WHERE item_id = ? AND scope = ? "
            "AND project_path = ?",
            (item_id, scope, project_path),
        ).fetchone()
        return None if row is None else row_to_item(row)

    def find_by_name(
        self, name: str, scope: str, project_path: str
    ) -> Optional[InstalledItem]:
        row = self._conn.execute(
            f"{_ITEM_SELECT} WHERE name = ? AND scope = ? "
            "AND project_path = ?",
            (name, scope, project_path),
        ).fetchone()
        return None if row is None else row_to_item(row)

    def find_name_any_scope(self, name: str) -> Tuple[InstalledItem, ...]:
        rows = self._conn.execute(
            f"{_ITEM_SELECT} WHERE name = ? "
            "ORDER BY scope ASC, project_path ASC",
            (name,),
        ).fetchall()
        return tuple(row_to_item(row) for row in rows)


    def insert(
        self,
        item: InstalledItem,
        targets: Iterable[InstallTarget] = (),
    ) -> InstalledItem:
        with transaction(self._conn):
            try:
                self._conn.execute(
                    f"INSERT INTO installed_items "
                    f"({', '.join(ITEM_COLUMNS)}) VALUES "
                    f"({', '.join('?' * len(ITEM_COLUMNS))})",
                    item_values(item),
                )
            except sqlite3.IntegrityError as exc:
                existing = self._conflicting(item)
                if existing is None:
                    raise
                raise AlreadyInstalled(existing) from exc
            self._write_targets(item.install_id, targets)
            stored = self.get(item.install_id)
        if stored is None:
            raise InstallNotFound(
                "the install row vanished between its INSERT and its read",
                item.install_id,
            )
        resource_push.notify(resource_topics.CATALOG)
        logger.info(
            "install_ledger_inserted",
            install_id=stored.install_id,
            item_id=log_value(stored.item_id),
            scope=stored.scope,
        )
        return stored

    def update(
        self,
        install_id: str,
        /,
        *,
        expected_revision: int,
        now: str,
        **fields: Any,
    ) -> InstalledItem:
        if not fields:
            raise LedgerError(
                "update was given no fields to write; a no-op write would "
                "still step the revision and invalidate every other "
                "reader's for nothing"
            )
        unknown = sorted(set(fields) - MUTABLE_COLUMNS)
        if unknown:
            raise LedgerError(
                f"not writable through the ledger: {', '.join(unknown)}"
            )
        with transaction(self._conn):
            current = self.get(install_id)
            if current is None:
                raise InstallNotFound(
                    f"no install row carries the id {install_id!r}",
                    install_id,
                )
            if current.revision != expected_revision:
                logger.warning(
                    "install_ledger_stale_revision",
                    install_id=install_id,
                    expected_revision=expected_revision,
                    current_revision=current.revision,
                )
                raise StaleRevision(current)
            projected = replace(
                current,
                **{
                    key: (
                        bool(value) if key == "auto_update" else value
                    )
                    for key, value in fields.items()
                },
            )
            assignments = [f"{key} = ?" for key in fields]
            params: List[Any] = [
                (1 if value else 0) if key == "auto_update" else value
                for key, value in fields.items()
            ]
            assignments.append("revision = ?")
            params.append(current.revision + 1)
            assignments.append("updated_at = ?")
            params.append(now)
            params.append(install_id)
            try:
                self._conn.execute(
                    f"UPDATE installed_items SET {', '.join(assignments)} "
                    "WHERE install_id = ?",
                    tuple(params),
                )
            except sqlite3.IntegrityError as exc:
                existing = self._conflicting(
                    projected, exclude_install_id=install_id
                )
                if existing is None:
                    raise
                raise AlreadyInstalled(existing) from exc
            stored = self.get(install_id)
        if stored is None:
            raise InstallNotFound(
                "the install row vanished between its UPDATE and its read",
                install_id,
            )
        resource_push.notify(resource_topics.CATALOG)
        return stored

    def delete(self, install_id: str) -> bool:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM installed_items WHERE install_id = ?",
                (install_id,),
            )
            removed = cursor.rowcount > 0
        if removed:
            resource_push.notify(resource_topics.CATALOG)
            logger.info("install_ledger_removed", install_id=install_id)
        return removed

    def replace_targets(
        self, install_id: str, targets: Iterable[InstallTarget]
    ) -> Tuple[InstallTarget, ...]:
        with transaction(self._conn):
            if self.get(install_id) is None:
                raise InstallNotFound(
                    f"no install row carries the id {install_id!r}",
                    install_id,
                )
            self._conn.execute(
                "DELETE FROM installed_item_targets WHERE install_id = ?",
                (install_id,),
            )
            self._write_targets(install_id, targets)
        return self.targets(install_id)


    def _write_targets(
        self, install_id: str, targets: Iterable[InstallTarget]
    ) -> None:
        for target in targets:
            self._conn.execute(
                "INSERT INTO installed_item_targets "
                "(install_id, harness, path) VALUES (?, ?, ?)",
                (install_id, target.harness, target.path),
            )

    def _conflicting(
        self,
        item: InstalledItem,
        *,
        exclude_install_id: Optional[str] = None,
    ) -> Optional[InstalledItem]:
        candidates = (
            self.find(item.item_id, item.scope, item.project_path),
            self.find_by_name(item.name, item.scope, item.project_path),
            self.get(item.install_id),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            if candidate.install_id == exclude_install_id:
                continue
            return candidate
        return None

