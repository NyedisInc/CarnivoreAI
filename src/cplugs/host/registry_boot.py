
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.app_alerts import constants as alert_const
from src.core.app_alerts import service as alert_service
from src.core.db import DatastoreError
from src.core.json_artifact import UnreadableArtifact, read_for_update
from src.cplugs.host import registry_files, registry_migration, registry_projection, registry_store

logger = structlog.get_logger()

ALERT_SOURCE = "plugin_registry"
_T = "app_alert.plugin_registry."
KEY_REFUSED, KEY_OLDER, KEY_RESTORED, KEY_READ_ONLY = (f"{ALERT_SOURCE}.migration_refused", f"{ALERT_SOURCE}.older_copy", f"{ALERT_SOURCE}.restored_backup",
                                                      f"{ALERT_SOURCE}.read_only")
STICKY_KEYS = (KEY_REFUSED, KEY_OLDER, KEY_RESTORED, KEY_READ_ONLY)
REASON_BUSY = "registry_busy"
RESOLVE_ROUTE = "/cplug-owner/registry/resolve"
CHOICE_KEEP, CHOICE_BACKUP = "keep", "backup"

A_NORMAL, A_MIGRATED, A_REFUSED, A_ACCEPTED_FILE, A_OLDER_COPY, A_RESTORED, A_READ_ONLY, A_REIMPORTED = (
    "normal", "migrated", "refused", "accepted_file", "older_copy", "restored_backup", "read_only", "reimported_mirror")

KNOWN_FIELDS = tuple(registry_projection.STATE_DEFAULTS)

AlertSink = Callable[..., Any]


@dataclass
class BootOutcome:

    action: str
    detail: str = ""
    read_only: bool = False
    reimported: Optional[List[str]] = None
    backup: Optional[Path] = None


def _alert(sink: AlertSink, key: str, severity: str, title: str, detail: str, params: Mapping[str, Any], actions: Optional[List[Dict[str, Any]]] = None) -> None:
    sink(key, source=ALERT_SOURCE, severity=severity, title_key=f"{_T}{title}", detail_key=f"{_T}{detail}", params=dict(params), sticky=True, auto_resolve=False,
         actions=actions or [])


def _marker_flipped(state_dir: Path) -> bool:
    held = registry_files.read_marker(state_dir)
    return held is not None and held.migration_version >= registry_files.MIGRATION_VERSION


def _bak_doc(state_dir: Path) -> Optional[Dict[str, Any]]:
    doc, _ = registry_files.parse_registry(registry_files.registry_path(state_dir).with_suffix(".json.bak"))
    return doc if doc is not None and registry_files.is_migrated(doc) else None


def _backup_candidate(folder: Path, generation: int) -> Optional[Dict[str, Any]]:
    docs: Dict[str, Dict[str, Any]] = {}
    for name, file_name in registry_files.LEGACY_FILES.items():
        try:
            docs[name] = read_for_update(folder / file_name, log_event="plugin_registry_backup_unreadable")
        except UnreadableArtifact:
            return None
    block = {"version": registry_files.MIGRATION_VERSION, "migrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return registry_projection.build_document(generation=generation, docs=docs, carry={registry_files.MIGRATION_KEY: block})


def _install(state_dir: Path, document: Dict[str, Any]) -> None:
    registry_files.write_registry(registry_files.registry_path(state_dir), document)
    try:
        registry_files.record_marker(state_dir, document["generation"], migration_version=registry_files.MIGRATION_VERSION)
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__)
    registry_files.mirror(state_dir, registry_projection.join(document), document["generation"])


def restore_from_copy(state_dir: Path) -> Optional[str]:
    top = max(registry_files.read_generation(state_dir) or 0, registry_files.marker_generation(state_dir))
    bak = _bak_doc(state_dir)
    if bak is not None:
        carry = registry_files.carried(bak)
        _install(state_dir, registry_projection.build_document(generation=max(top, bak["generation"]) + 1, docs=registry_projection.join(bak), carry=carry))
        return registry_files.registry_path(state_dir).name + ".bak"
    for folder in registry_files.backups_newest_first(state_dir):
        candidate = _backup_candidate(folder, top + 1)
        if candidate is not None:
            _install(state_dir, candidate)
            return folder.name
    return None


def _resolve_sticky() -> None:
    for key in STICKY_KEYS:
        alert_service.resolve(key)


def _go_read_only(state_dir: Path, reason: str, sink: AlertSink) -> BootOutcome:
    registry_files.set_read_only(state_dir, reason)
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


def _reimport_rollback_writes(state_dir: Path, doc: Dict[str, Any]) -> List[str]:
    path = registry_files.legacy_path(state_dir, "state")
    try:
        mirror = read_for_update(path, log_event="plugin_registry_mirror_unreadable")
        newer = path.exists() and path.stat().st_mtime_ns > registry_files.registry_path(state_dir).stat().st_mtime_ns
    except (UnreadableArtifact, OSError):
        return []
    entries = mirror.get("cplugs") if isinstance(mirror.get("cplugs"), dict) else {}
    if mirror.get(registry_projection.MIRROR_STAMP) is not None or not newer:
        return []
    docs = registry_projection.join(doc)
    held = docs["state"]["cplugs"]
    changed = [i for i, e in sorted(entries.items()) if isinstance(e, dict) and held.get(i) != e]
    for item in changed:
        merged = {**held.get(item, {}), **{k: v for k, v in entries[item].items() if k in KNOWN_FIELDS}} if isinstance(held.get(item), dict) else dict(entries[item])
        held[item] = merged
        logger.info("plugin_registry_reimported_rollback_write", item=item)
    if changed and not registry_store.write_document(state_dir, "state", docs["state"], log_event="plugin_registry_reimport_failed"):
        return []
    return changed


def _heal_marker(state_dir: Path, doc: Dict[str, Any], marker: Any) -> None:
    if marker is not None and marker.generation == doc["generation"] and marker.migration_version >= registry_files.MIGRATION_VERSION:
        return
    block = doc.get(registry_files.MIGRATION_KEY, {})
    try:
        registry_files.record_marker(state_dir, doc["generation"], migration_version=block.get("version", registry_files.MIGRATION_VERSION),
                                     migrated_at=block.get("migrated_at"))
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__)


def _judge_generation(state_dir: Path, doc: Dict[str, Any], sink: AlertSink) -> Optional[BootOutcome]:
    marker = registry_files.read_marker(state_dir)
    if marker is None:
        _heal_marker(state_dir, doc, None)
        return None
    if doc["generation"] >= marker.generation:
        _heal_marker(state_dir, doc, marker)
    if marker.generation == doc["generation"]:
        return None
    if doc["generation"] < marker.generation:
        registry_files.set_read_only(state_dir, "older_copy")
        actions = [{"id": CHOICE_KEEP, "label_key": f"{_T}action.keep", "method": "PUT", "route": RESOLVE_ROUTE, "body": {"choice": CHOICE_KEEP}},
                   {"id": CHOICE_BACKUP, "label_key": f"{_T}action.backup", "method": "PUT", "route": RESOLVE_ROUTE, "body": {"choice": CHOICE_BACKUP}}]
        _alert(sink, KEY_OLDER, alert_const.SEV_ERROR, "older_copy.title", "older_copy.detail",
               {"file": doc["generation"], "database": marker.generation}, actions)
        logger.error("plugin_registry_older_copy", file_generation=doc["generation"], marker_generation=marker.generation)
        return BootOutcome(A_OLDER_COPY, f"file {doc['generation']} below marker {marker.generation}", read_only=True)
    logger.info("plugin_registry_accepted_newer_file", file_generation=doc["generation"], marker_generation=marker.generation)
    return None


def _boot_flipped(state_dir: Path, doc: Dict[str, Any], retired: Callable[[], None], sink: AlertSink) -> BootOutcome:
    stop = _judge_generation(state_dir, doc, sink)
    if stop is not None:
        return stop
    reimported = _reimport_rollback_writes(state_dir, doc)
    retired()
    _resolve_sticky()
    return BootOutcome(A_REIMPORTED if reimported else A_NORMAL, reimported=reimported or None)


def _migrate(state_dir: Path, retired: Callable[[], None], sink: AlertSink, now: Optional[datetime]) -> BootOutcome:
    result = registry_migration.migrate(state_dir, retired=retired, now=now)
    if result.outcome == registry_migration.OUTCOME_MIGRATED:
        _resolve_sticky()
        return BootOutcome(A_MIGRATED, f"generation {result.generation}")
    refusal = result.refusal
    _alert(sink, KEY_REFUSED, alert_const.SEV_ERROR, "migration_refused.title", "migration_refused.detail",
           {"item": refusal.item or "-", "field": refusal.field_name or "-", "code": refusal.code})
    if result.backup is None:
        retired()
    return BootOutcome(A_REFUSED, f"{refusal.code}: {refusal}", backup=result.backup)


def run(state_dir: Path, *, retired: Callable[[], None], alert: Optional[AlertSink] = None, now: Optional[datetime] = None) -> BootOutcome:
    sink: AlertSink = alert or alert_service.raise_alert
    try:
        with registry_store.exclusive(state_dir):
            doc, status = registry_files.load_registry(state_dir)
            if status == registry_files.STATUS_OK and registry_files.is_migrated(doc):
                return _boot_flipped(state_dir, doc, retired, sink)
            if status != registry_files.STATUS_OK and (_marker_flipped(state_dir) or _bak_doc(state_dir) is not None):
                return _recover(state_dir, sink)
            outcome = _migrate(state_dir, retired, sink, now)
        if outcome.backup is not None:
            try:
                with registry_store.exclusive(state_dir):
                    registry_migration.record_post_retired(state_dir, outcome.backup)
            except registry_store.RegistryBusy as exc:
                logger.warning("plugin_registry_post_retired_record_busy", error=str(exc)[:200])
        return outcome
    except registry_store.RegistryBusy as exc:
        logger.error("plugin_registry_boot_busy", error=str(exc)[:200])
        return _go_read_only(state_dir, REASON_BUSY, sink)


def resolve(state_dir: Path, choice: str) -> bool:
    if choice not in (CHOICE_KEEP, CHOICE_BACKUP):
        raise ValueError(f"unknown choice {choice!r}")
    with registry_store.exclusive(state_dir):
        if choice == CHOICE_BACKUP:
            if restore_from_copy(state_dir) is None:
                return False
        else:
            doc, status = registry_files.load_registry(state_dir)
            if status != registry_files.STATUS_OK:
                return False
            top = max(doc["generation"], registry_files.marker_generation(state_dir)) + 1
            _install(state_dir, registry_projection.build_document(generation=top, docs=registry_projection.join(doc), carry=registry_files.carried(doc)))
        registry_files.clear_read_only(state_dir)
        alert_service.resolve(KEY_OLDER)
    return True
