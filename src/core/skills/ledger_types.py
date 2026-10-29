
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

SCOPE_GLOBAL = "global"

SCOPE_PROJECT = "project"

GLOBAL_PROJECT_PATH = ""

HARNESS_CLAUDE = "claude"
HARNESS_CODEX = "codex"

ITEM_COLUMNS: Tuple[str, ...] = (
    "install_id",
    "item_id",
    "kind",
    "publisher",
    "name",
    "version",
    "digest",
    "scope",
    "project_path",
    "auto_update",
    "source_index_url",
    "consented_digest",
    "consented_body_sha",
    "publisher_key_id",
    "revision",
    "installed_at",
    "updated_at",
    "consent_via",
)

MUTABLE_COLUMNS = frozenset(
    ITEM_COLUMNS[1:]
) - {"revision", "installed_at", "updated_at", "consent_via"}


class LedgerError(RuntimeError):
    pass


class InstallNotFound(LedgerError):

    def __init__(self, message: str, install_id: str) -> None:
        super().__init__(message)
        self.install_id = install_id


class AlreadyInstalled(LedgerError):

    def __init__(self, existing: "InstalledItem") -> None:
        super().__init__(
            f"{existing.item_id!r} is already installed as {existing.name!r} "
            f"in scope {existing.scope!r}"
        )
        self.existing = existing


class StaleRevision(LedgerError):

    def __init__(self, current: "InstalledItem") -> None:
        super().__init__(
            f"install {current.install_id!r} is at revision "
            f"{current.revision}"
        )
        self.current = current


@dataclass(frozen=True)
class InstalledItem:

    install_id: str
    item_id: str
    kind: str
    publisher: str
    name: str
    version: str
    digest: str
    scope: str
    project_path: str
    auto_update: bool
    source_index_url: str
    consented_digest: Optional[str]
    consented_body_sha: Optional[str]
    publisher_key_id: str
    revision: int
    installed_at: str
    updated_at: str
    consent_via: str


@dataclass(frozen=True)
class InstallTarget:

    install_id: str
    harness: str
    path: str


def row_to_item(row: sqlite3.Row) -> InstalledItem:
    return InstalledItem(
        install_id=str(row["install_id"]),
        item_id=str(row["item_id"]),
        kind=str(row["kind"]),
        publisher=str(row["publisher"]),
        name=str(row["name"]),
        version=str(row["version"]),
        digest=str(row["digest"]),
        scope=str(row["scope"]),
        project_path=str(row["project_path"]),
        auto_update=bool(row["auto_update"]),
        source_index_url=str(row["source_index_url"]),
        consented_digest=(
            None if row["consented_digest"] is None
            else str(row["consented_digest"])
        ),
        consented_body_sha=(
            None if row["consented_body_sha"] is None
            else str(row["consented_body_sha"])
        ),
        publisher_key_id=str(row["publisher_key_id"]),
        revision=int(row["revision"]),
        installed_at=str(row["installed_at"]),
        updated_at=str(row["updated_at"]),
        consent_via=str(row["consent_via"]),
    )


def item_values(item: InstalledItem) -> Tuple[Any, ...]:
    return (
        item.install_id,
        item.item_id,
        item.kind,
        item.publisher,
        item.name,
        item.version,
        item.digest,
        item.scope,
        item.project_path,
        1 if item.auto_update else 0,
        item.source_index_url,
        item.consented_digest,
        item.consented_body_sha,
        item.publisher_key_id,
        int(item.revision),
        item.installed_at,
        item.updated_at,
        item.consent_via,
    )


def as_dict(item: InstalledItem) -> Dict[str, Any]:
    return {column: getattr(item, column) for column in ITEM_COLUMNS}
