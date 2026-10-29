
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional

import structlog

from src.core import resource_push
from src.core.catalog.first_party_listing import pinned_key_id
from src.core.catalog.index_snapshot import IndexSnapshot
from src.core.catalog.revocation import version_subject
from src.core.catalog import release_vouch
from src.core.catalog.trust_root import production_trust_root
from src.core.catalog.verify_items import _verify_release
from src.core.resource_push import topics as resource_topics
from src.core.skills.installer import iso_from
from src.core.skills.records import SIDECAR_NAME
from src.core.test_write_guard import assert_test_write_allowed
from src.models.catalog import CatalogItem
from src.models.catalog_names import (
    FIRST_PARTY_THEME_PUBLISHER, LEGACY_FIRST_PARTY_PUBLISHER, is_first_party_publisher,
)

logger = structlog.get_logger()

LEGACY_PUBLISHERS = {
    LEGACY_FIRST_PARTY_PUBLISHER: (FIRST_PARTY_THEME_PUBLISHER,),
}


def _vouched(item: Optional[CatalogItem], row: sqlite3.Row, old_id: str, revoked: tuple) -> bool:
    if item is None or item.kind != str(row["kind"]):
        return False
    version = next((v for v in item.versions if v.v == row["version"] and v.digest == row["digest"]), None)
    if version is None:
        return False
    return release_vouch.vouch(
        item, version, str(row["digest"]), revoked,
        publisher_key=production_trust_root().publisher_key, pinned_key_id=pinned_key_id(),
        verify=_verify_release, extra_subjects=(version_subject(old_id, str(row["version"])),),
    ) is None


def _rewrite_sidecar(directory: Path, old: str, new: str) -> None:
    path = directory / SIDECAR_NAME
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("catalog_publisher_rename_sidecar_unreadable", path=str(path), error=str(exc))
        return
    if not isinstance(data, dict) or data.get("publisher") != old:
        return
    data["publisher"] = new
    assert_test_write_allowed(path)
    tmp = path.with_name(SIDECAR_NAME + ".rename.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _rename_rows(conn: sqlite3.Connection, row: sqlite3.Row, new_id: str, new: str, stamp: str) -> bool:
    with conn:
        moved = conn.execute(
            "UPDATE installed_items SET item_id = ?, publisher = ?, updated_at = ?, revision = revision + 1 "
            "WHERE install_id = ? AND item_id = ? AND digest = ? AND publisher_key_id = ? AND revision = ?",
            (new_id, new, stamp, row["install_id"], row["item_id"], row["digest"],
             row["publisher_key_id"], row["revision"]),
        ).rowcount
        if moved != 1:
            return False
        conn.execute(
            "UPDATE installed_loadout_members SET item_id = ? WHERE item_id = ? AND member_install_id = ?",
            (new_id, row["item_id"], row["install_id"]),
        )
    resource_push.notify(resource_topics.CATALOG)
    return True


def repair_sidecars(conn: sqlite3.Connection) -> None:
    for old, news in LEGACY_PUBLISHERS.items():
        for new in news:
            paths = [
                str(r["path"]) for r in conn.execute(
                    "SELECT t.path FROM installed_item_targets t JOIN installed_items i USING (install_id) "
                    "WHERE i.publisher = ?", (new,),
                )
            ]
            for path in paths:
                try:
                    _rewrite_sidecar(Path(path), old, new)
                except OSError as exc:
                    logger.warning("catalog_publisher_rename_repair_failed", path=path, error=str(exc))


def apply(snapshot: IndexSnapshot, services: Any) -> List[str]:
    verified = snapshot.verified
    if verified is None or snapshot.refusal is not None:
        return []
    revoked = services.catalog.index_cache.revoked_sets(verified)
    trusted = {item.id: item for item in verified.items if is_first_party_publisher(item.publisher)}
    renamed: List[str] = []
    try:
        with closing(services.catalog.open_db()) as conn:
            marks = ",".join("?" * len(LEGACY_PUBLISHERS))
            rows = conn.execute(
                "SELECT install_id, item_id, kind, name, version, digest, publisher_key_id, revision FROM installed_items "
                f"WHERE publisher IN ({marks})",
                tuple(LEGACY_PUBLISHERS),
            ).fetchall()
            for row in rows:
                old_id = str(row["item_id"])
                old, _, name = old_id.partition("/")
                if old not in LEGACY_PUBLISHERS or name != str(row["name"]):
                    continue
                new = next((h for h in LEGACY_PUBLISHERS[old]
                            if _vouched(trusted.get(f"{h}/{name}"), row, old_id, revoked)), None)
                if new is None:
                    logger.info("catalog_publisher_rename_skipped", item_id=old_id, install_id=row["install_id"])
                    continue
                new_id = f"{new}/{name}"
                install_id = str(row["install_id"])
                try:
                    if not _rename_rows(conn, row, new_id, new, iso_from(services.clock)):
                        logger.info("catalog_publisher_rename_row_changed", item_id=old_id, install_id=install_id)
                        continue
                except sqlite3.Error as exc:
                    logger.warning("catalog_publisher_rename_failed", item_id=old_id, error=str(exc))
                    continue
                renamed.append(install_id)
                logger.info("catalog_publisher_renamed", old_id=old_id, new_id=new_id, install_id=install_id)
            repair_sidecars(conn)
    except sqlite3.Error as exc:
        logger.warning("catalog_publisher_rename_ledger_unreadable", error=str(exc))
    return renamed
