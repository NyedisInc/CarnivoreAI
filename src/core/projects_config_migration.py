
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.config_files_io import atomic_write
from src.core.db import connect, db_path_for, transaction
from src.core.project_reconcile import record_migration
from src.core.project_store import (
    PROJECTS_TABLE,
    import_from_config,
    normalize_root,
)
from src.core.project_tombstones import (
    TOMBSTONES_TABLE,
    tombstoned_roots,
)

logger = structlog.get_logger()

MIGRATION_OK = "ok"
MIGRATION_NOTHING_TO_DO = "nothing_to_do"
MIGRATION_CONFIG_MISSING = "config_missing"
MIGRATION_CONFIG_UNPARSEABLE = "config_unparseable"
MIGRATION_DATASTORE_UNREADABLE = "datastore_unreadable"
MIGRATION_COVERAGE_UNPROVEN = "coverage_unproven"
MIGRATION_WRITE_FAILED = "write_failed"

PROJECTS_KEY = "projects"

PROJECTS_COMMENT_KEY = "_comment_projects"

PROJECTS_RETIRED_KEY = "_comment_projects_retired"
PROJECTS_RETIRED_NOTE = (
    "Projects used to live here. They now live in cloude.db's projects "
    "table and nowhere else, and this key was removed automatically after "
    "every entry it held was moved into that table. Adding a projects key "
    "back here does nothing - the app does not read one. Add projects from "
    "the launchpad instead."
)


@dataclass(frozen=True)
class MigrationResult:

    ok: bool
    reason: str
    imported: List[Dict[str, Any]] = field(default_factory=list)
    imported_undetermined: List[Dict[str, Any]] = field(default_factory=list)
    already_present: int = 0
    skipped_deleted: List[Dict[str, Any]] = field(default_factory=list)
    detail: Optional[str] = None

    @property
    def changed(self) -> bool:
        return bool(self.imported or self.imported_undetermined) or (
            self.reason == MIGRATION_OK
        )

    def notice(self) -> Optional[str]:
        parts: List[str] = []
        if self.imported:
            names = ", ".join(e["name"] for e in self.imported)
            parts.append(
                f"{len(self.imported)} project(s) were still only in "
                f"config.json and have been moved into the database: "
                f"{names}."
            )
        if self.imported_undetermined:
            names = ", ".join(e["name"] for e in self.imported_undetermined)
            parts.append(
                f"{len(self.imported_undetermined)} project(s) in "
                "config.json could not be matched to a database row, and "
                "this install predates deletion tracking, so it CANNOT BE "
                "DETERMINED whether you removed them or they were never "
                "imported. They have been kept rather than dropped, "
                f"because dropping them would be permanent: {names}."
            )
        if self.skipped_deleted:
            parts.append(
                f"{len(self.skipped_deleted)} project(s) in config.json "
                "stayed removed because you deleted them here."
            )
        if not self.ok and self.reason != MIGRATION_NOTHING_TO_DO:
            parts.append(
                "config.json still carries its old projects list because "
                f"this could not be completed ({self.reason}). Nothing was "
                "lost; it will be retried on the next start."
            )
        return " ".join(parts) if parts else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "cannot_determine": bool(self.imported_undetermined),
            "imported": self.imported,
            "imported_undetermined": self.imported_undetermined,
            "already_present": self.already_present,
            "skipped_deleted": self.skipped_deleted,
            "detail": self.detail,
            "notice": self.notice(),
        }


class _Entry:

    __slots__ = ("name", "path", "description", "agent_type")

    def __init__(
        self,
        name: str,
        path: str,
        description: Optional[str] = None,
        agent_type: Optional[str] = None,
    ) -> None:
        self.name = name
        self.path = path
        self.description = description
        self.agent_type = agent_type


def _read_config_doc(config_path: Path) -> Any:
    return json.loads(config_path.read_text())


def _entries_from(doc: Any) -> List[_Entry]:
    raw = doc.get(PROJECTS_KEY) or []
    if not isinstance(raw, list):
        return []
    entries: List[_Entry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not path or not isinstance(path, str):
            continue
        entries.append(
            _Entry(
                name=str(item.get("name") or path),
                path=path,
                description=item.get("description"),
                agent_type=item.get("agent_type"),
            )
        )
    return entries


def _drop_projects_key(config_path: Path, doc: Any) -> None:
    doc.pop(PROJECTS_KEY, None)
    doc.pop(PROJECTS_COMMENT_KEY, None)
    doc[PROJECTS_RETIRED_KEY] = PROJECTS_RETIRED_NOTE
    atomic_write(config_path, json.dumps(doc, indent=2) + "\n")


def migrate_projects_out_of_config(
    state_dir: Path, config_path: Path
) -> MigrationResult:
    try:
        doc = _read_config_doc(config_path)
    except FileNotFoundError:
        return MigrationResult(
            ok=True,
            reason=MIGRATION_NOTHING_TO_DO,
            detail="config.json does not exist, so it carries no projects.",
        )
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("projects_migration_config_unparseable", error=str(exc))
        return MigrationResult(
            ok=False,
            reason=MIGRATION_CONFIG_UNPARSEABLE,
            detail=(
                f"config.json could not be parsed ({exc}), so it was left "
                "alone rather than rewritten from a document nobody could "
                "read."
            ),
        )
    except OSError as exc:
        return MigrationResult(
            ok=False,
            reason=MIGRATION_CONFIG_MISSING,
            detail=f"config.json could not be read ({exc}).",
        )

    if not isinstance(doc, dict) or PROJECTS_KEY not in doc:
        return MigrationResult(ok=True, reason=MIGRATION_NOTHING_TO_DO)

    entries = _entries_from(doc)

    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            return _migrate_with_db(conn, doc, entries, config_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "projects_migration_datastore_unreadable", error=str(exc)
        )
        return MigrationResult(
            ok=False,
            reason=MIGRATION_DATASTORE_UNREADABLE,
            detail=(
                f"cloude.db could not be read ({exc}), so config.json's "
                "projects were left exactly where they are. Removing them "
                "now would delete the only copy this install can still "
                "see."
            ),
        )


def _migrate_with_db(
    conn: Any, doc: Any, entries: List[_Entry], config_path: Path
) -> MigrationResult:
    from src.core.db import table_exists

    if not table_exists(conn, PROJECTS_TABLE):
        return MigrationResult(
            ok=False,
            reason=MIGRATION_DATASTORE_UNREADABLE,
            detail=(
                "the projects table does not exist yet, so nothing can be "
                "migrated into it and config.json was left alone."
            ),
        )

    existing = _db_roots(conn)
    tombstones = tombstoned_roots(conn)
    has_tombstone_table = table_exists(conn, TOMBSTONES_TABLE)

    already = 0
    to_import: List[_Entry] = []
    undetermined: List[_Entry] = []
    skipped: List[Dict[str, Any]] = []

    for entry in entries:
        root = normalize_root(entry.path)
        if root in existing:
            already += 1
        elif root in tombstones:
            skipped.append({"root": root, "name": entry.name})
        elif has_tombstone_table:
            to_import.append(entry)
        else:
            undetermined.append(entry)

    importable = to_import + undetermined
    if importable:
        with transaction(conn):
            import_from_config(conn, importable)

    after = _db_roots(conn)
    unaccounted = [
        {"root": normalize_root(e.path), "name": e.name}
        for e in entries
        if normalize_root(e.path) not in after
        and normalize_root(e.path) not in tombstones
    ]
    if unaccounted:
        logger.error(
            "projects_migration_coverage_unproven",
            unaccounted=[u["root"] for u in unaccounted],
        )
        return MigrationResult(
            ok=False,
            reason=MIGRATION_COVERAGE_UNPROVEN,
            imported=_named(to_import),
            imported_undetermined=_named(undetermined),
            already_present=already,
            skipped_deleted=skipped,
            detail=(
                f"{len(unaccounted)} project(s) in config.json are still "
                "not in cloude.db after the import, so the config copy was "
                "kept: "
                + ", ".join(u["name"] for u in unaccounted)
            ),
        )

    try:
        _drop_projects_key(config_path, doc)
    except OSError as exc:
        logger.warning("projects_migration_write_failed", error=str(exc))
        return MigrationResult(
            ok=False,
            reason=MIGRATION_WRITE_FAILED,
            imported=_named(to_import),
            imported_undetermined=_named(undetermined),
            already_present=already,
            skipped_deleted=skipped,
            detail=(
                f"config.json could not be rewritten ({exc}). Every project "
                "is safely in cloude.db; the old list is still in the file "
                "and will be removed on the next start."
            ),
        )

    result = MigrationResult(
        ok=True,
        reason=MIGRATION_OK,
        imported=_named(to_import),
        imported_undetermined=_named(undetermined),
        already_present=already,
        skipped_deleted=skipped,
    )
    try:
        with transaction(conn):
            record_migration(conn, result.to_dict())
    except Exception as exc:  # noqa: BLE001
        logger.warning("projects_migration_record_failed", error=str(exc))
    logger.info(
        "projects_migration_complete",
        imported=len(to_import),
        imported_undetermined=len(undetermined),
        already_present=already,
        skipped_deleted=len(skipped),
    )
    return result


def _db_roots(conn: Any) -> set:
    return {
        row[0] for row in conn.execute("SELECT root FROM projects").fetchall()
    }


def _named(entries: List[_Entry]) -> List[Dict[str, Any]]:
    return [
        {"root": normalize_root(e.path), "name": e.name} for e in entries
    ]


__all__ = [
    "MIGRATION_CONFIG_MISSING",
    "MIGRATION_CONFIG_UNPARSEABLE",
    "MIGRATION_COVERAGE_UNPROVEN",
    "MIGRATION_DATASTORE_UNREADABLE",
    "MIGRATION_NOTHING_TO_DO",
    "MIGRATION_OK",
    "MIGRATION_WRITE_FAILED",
    "MigrationResult",
    "migrate_projects_out_of_config",
]
