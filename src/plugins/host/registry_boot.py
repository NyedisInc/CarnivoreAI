
from __future__ import annotations

import copy
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.app_alerts import constants as alert_const
from src.core.app_alerts import service as alert_service
from src.core.db import DatastoreError
from src.plugins.host import registry_store

logger = structlog.get_logger()

ALERT_SOURCE = "plugin_registry"
_T = "app_alert.plugin_registry."
KEY_REFUSED, KEY_OLDER, KEY_RESTORED, KEY_READ_ONLY = (
    f"{ALERT_SOURCE}.migration_refused",
    f"{ALERT_SOURCE}.older_copy",
    f"{ALERT_SOURCE}.restored_backup",
    f"{ALERT_SOURCE}.read_only",
)
STICKY_KEYS = (KEY_REFUSED, KEY_OLDER, KEY_RESTORED, KEY_READ_ONLY)
REASON_BUSY = "registry_busy"
RESOLVE_ROUTE = "/cplug-owner/registry/resolve"
CHOICE_KEEP, CHOICE_BACKUP = "keep", "backup"

A_NORMAL, A_MIGRATED, A_REFUSED, A_ACCEPTED_FILE, A_OLDER_COPY, A_RESTORED, A_READ_ONLY = (
    "normal",
    "migrated",
    "refused",
    "accepted_file",
    "older_copy",
    "restored_backup",
    "read_only",
)

AlertSink = Callable[..., Any]


@dataclass
class BootOutcome:

    action: str
    detail: str = ""
    read_only: bool = False
    backup: Optional[Path] = None


def _alert(
    sink: AlertSink,
    key: str,
    severity: str,
    title: str,
    detail: str,
    params: Mapping[str, Any],
    actions: Optional[List[Dict[str, Any]]] = None,
) -> None:
    sink(
        key,
        source=ALERT_SOURCE,
        severity=severity,
        title_key=f"{_T}{title}",
        detail_key=f"{_T}{detail}",
        params=dict(params),
        sticky=True,
        auto_resolve=False,
        actions=actions or [],
    )


def _marker_flipped(state_dir: Path) -> bool:
    held = registry_store.read_marker(state_dir)
    return held is not None and (held.schema >= registry_store.SCHEMA or held.migration_version >= registry_store.MIGRATION_VERSION)


def _bak_doc(state_dir: Path) -> Optional[Dict[str, Any]]:
    doc, _ = registry_store.parse_registry(registry_store.registry_path(state_dir).with_suffix(".json.bak"))
    return doc if doc is not None and registry_store.is_migrated(doc) else None


def _backup_candidate(folder: Path, generation: int) -> Optional[Dict[str, Any]]:
    reg = folder / registry_store.REGISTRY_FILE
    if not reg.is_file():
        return None
    doc, status = registry_store.parse_registry(reg)
    if status != registry_store.STATUS_OK or doc is None or not registry_store.is_migrated(doc):
        return None
    out = copy.deepcopy(doc)
    out["generation"] = generation
    return out


def _install(state_dir: Path, document: Dict[str, Any]) -> None:
    registry_store.write_registry(registry_store.registry_path(state_dir), document)
    block = document.get(registry_store.MIGRATION_KEY) if isinstance(document.get(registry_store.MIGRATION_KEY), Mapping) else {}
    try:
        registry_store.record_marker(
            state_dir,
            document["generation"],
            migration_version=block.get("version", registry_store.MIGRATION_VERSION),
            migrated_at=block.get(registry_store.MIGRATED_AT_KEY),
        )
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__)


def restore_from_copy(state_dir: Path) -> Optional[str]:
    top = max(registry_store.read_generation(state_dir) or 0, registry_store.marker_generation(state_dir))
    bak = _bak_doc(state_dir)
    if bak is not None:
        restored = copy.deepcopy(bak)
        restored["generation"] = max(top, bak["generation"]) + 1
        _install(state_dir, restored)
        return registry_store.registry_path(state_dir).name + ".bak"
    for folder in registry_store.backups_newest_first(state_dir):
        candidate = _backup_candidate(folder, top + 1)
        if candidate is not None:
            _install(state_dir, candidate)
            return folder.name
    return None


def _resolve_sticky() -> None:
    for key in STICKY_KEYS:
        alert_service.resolve(key)


def _go_read_only(state_dir: Path, reason: str, sink: AlertSink) -> BootOutcome:
    registry_store.set_read_only(state_dir, reason)
    detail = "busy.detail" if reason == REASON_BUSY else "read_only.detail"
    _alert(sink, KEY_READ_ONLY, alert_const.SEV_ERROR, "read_only.title", detail, {"reason": reason})
    logger.error("plugin_registry_read_only", reason=reason)
    return BootOutcome(A_READ_ONLY, reason, read_only=True)


def _recover(state_dir: Path, sink: AlertSink) -> BootOutcome:
    used = restore_from_copy(state_dir)
    if used is None:
        return _go_read_only(state_dir, "registry_unreadable", sink)
    _alert(sink, KEY_RESTORED, alert_const.SEV_WARN, "restored_backup.title", "restored_backup.detail", {"copy": used})
    logger.warning("plugin_registry_restored_from_copy", copy=used)
    return BootOutcome(A_RESTORED, used)


def _heal_marker(state_dir: Path, doc: Dict[str, Any], marker: Any) -> None:
    if marker is not None and marker.generation == doc["generation"] and marker.migration_version >= registry_store.MIGRATION_VERSION:
        return
    block = doc.get(registry_store.MIGRATION_KEY, {})
    try:
        registry_store.record_marker(
            state_dir,
            doc["generation"],
            migration_version=block.get("version", registry_store.MIGRATION_VERSION),
            migrated_at=block.get(registry_store.MIGRATED_AT_KEY),
        )
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__)


def _judge_generation(state_dir: Path, doc: Dict[str, Any], sink: AlertSink) -> Optional[BootOutcome]:
    marker = registry_store.read_marker(state_dir)
    if marker is None:
        _heal_marker(state_dir, doc, None)
        return None
    if doc["generation"] >= marker.generation:
        _heal_marker(state_dir, doc, marker)
    if marker.generation == doc["generation"]:
        return None
    if doc["generation"] < marker.generation:
        registry_store.set_read_only(state_dir, "older_copy")
        actions = [
            {"id": CHOICE_KEEP, "label_key": f"{_T}action.keep", "method": "PUT", "route": RESOLVE_ROUTE, "body": {"choice": CHOICE_KEEP}},
            {"id": CHOICE_BACKUP, "label_key": f"{_T}action.backup", "method": "PUT", "route": RESOLVE_ROUTE, "body": {"choice": CHOICE_BACKUP}},
        ]
        _alert(
            sink,
            KEY_OLDER,
            alert_const.SEV_ERROR,
            "older_copy.title",
            "older_copy.detail",
            {"file": doc["generation"], "database": marker.generation},
            actions,
        )
        logger.error("plugin_registry_older_copy", file_generation=doc["generation"], marker_generation=marker.generation)
        return BootOutcome(A_OLDER_COPY, f"file {doc['generation']} below marker {marker.generation}", read_only=True)
    logger.info("plugin_registry_accepted_newer_file", file_generation=doc["generation"], marker_generation=marker.generation)
    return None


def _boot_flipped(state_dir: Path, doc: Dict[str, Any], retired: Callable[[], None], sink: AlertSink) -> BootOutcome:
    stop = _judge_generation(state_dir, doc, sink)
    if stop is not None:
        return stop
    retired()
    _resolve_sticky()
    return BootOutcome(A_NORMAL)


def run(state_dir: Path, *, retired: Callable[[], None], alert: Optional[AlertSink] = None, now: Optional[datetime] = None) -> BootOutcome:
    sink: AlertSink = alert or alert_service.raise_alert
    try:
        with registry_store.exclusive(state_dir):
            doc, status = registry_store.load_registry(state_dir)
            if status == registry_store.STATUS_OK and doc is not None and registry_store.is_migrated(doc):
                return _boot_flipped(state_dir, doc, retired, sink)
            if status == registry_store.STATUS_UNREADABLE or (
                status != registry_store.STATUS_OK and (_marker_flipped(state_dir) or _bak_doc(state_dir) is not None)
            ):
                return _recover(state_dir, sink)
            retired()
            stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
            doc_after, status_after = registry_store.load_registry(state_dir)
            if status_after == registry_store.STATUS_MISSING or doc_after is None:
                gen = max(0, registry_store.marker_generation(state_dir)) + 1
                _install(state_dir, registry_store.new_document(generation=gen, migrated_at=stamp))
            elif status_after == registry_store.STATUS_OK and not registry_store.is_migrated(doc_after):
                gen = max(doc_after["generation"], registry_store.marker_generation(state_dir)) + 1
                _install(state_dir, registry_store.normalize_document(doc_after, generation=gen, migrated_at=stamp))
            elif status_after == registry_store.STATUS_OK:
                _heal_marker(state_dir, doc_after, registry_store.read_marker(state_dir))
            _resolve_sticky()
            return BootOutcome(A_NORMAL)
    except registry_store.RegistryBusy as exc:
        logger.error("plugin_registry_boot_busy", error_type=type(exc).__name__, detail=str(exc)[:200])
        return _go_read_only(state_dir, REASON_BUSY, sink)


def resolve(state_dir: Path, choice: str) -> bool:
    if choice not in (CHOICE_KEEP, CHOICE_BACKUP):
        raise ValueError(f"unknown choice {choice!r}")
    with registry_store.exclusive(state_dir):
        if choice == CHOICE_BACKUP:
            if restore_from_copy(state_dir) is None:
                return False
        else:
            doc, status = registry_store.load_registry(state_dir)
            if status != registry_store.STATUS_OK or doc is None:
                return False
            updated = copy.deepcopy(doc)
            updated["generation"] = max(doc["generation"], registry_store.marker_generation(state_dir)) + 1
            _install(state_dir, updated)
        registry_store.clear_read_only(state_dir)
        alert_service.resolve(KEY_OLDER)
    return True
