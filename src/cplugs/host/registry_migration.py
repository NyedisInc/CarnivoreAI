
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core import plugin_layout
from src.core.db import DatastoreError, connect, db_path_for
from src.core.json_artifact import UnreadableArtifact, read_for_update
from src.core.skills import kinds
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.cplugs.host import identity, owner_switch, registry_files, registry_projection, sideload
from src.cplugs.host import state as owner_state

logger = structlog.get_logger()

OUTCOME_MIGRATED = "migrated"
OUTCOME_REFUSED = "refused"
JOURNAL_NAME = "layout-moves.json"
LEDGER_DUMP_NAME = "ledger-rows.json"
POST_RETIRED_NAME = "post-retired-shas.json"
LEDGER_COPY_FIELDS = ("version", "digest", "consented_digest", "consented_body_sha", "publisher_key_id", "auto_update", "revision", "installed_at", "updated_at",
                      "consent_via")
_BUILTIN_SOURCE = "builtin"


class MigrationRefused(Exception):

    def __init__(self, code: str, detail: str, *, item: str = "", field_name: str = "") -> None:
        super().__init__(detail)
        self.code, self.item, self.field_name = code, item, field_name


@dataclass
class MigrationResult:

    outcome: str
    generation: Optional[int] = None
    backup: Optional[Path] = None
    refusal: Optional[MigrationRefused] = None
    moved: List[str] = field(default_factory=list)


def read_old_documents(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    for name in registry_files.LEGACY_FILES:
        try:
            found[name] = read_for_update(registry_files.legacy_path(state_dir, name), log_event="plugin_registry_migration_input_unreadable")
        except UnreadableArtifact as exc:
            raise MigrationRefused("unreadable_store", f"{registry_files.LEGACY_FILES[name]} cannot be read: {exc.reason}", item=name) from exc
    return found


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pick_backup_dir(state_dir: Path, generation: int) -> Path:
    base = registry_files.backup_dir(state_dir, generation)
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = base.with_name(f"{base.name}-{n}")
    return candidate


def ledger_rows(state_dir: Path) -> List[Dict[str, Any]]:
    path = db_path_for(state_dir)
    if not path.exists():
        return []
    try:
        conn = connect(path, create=False)
        try:
            rows = InstallLedger(conn).list(scope=SCOPE_GLOBAL)
        finally:
            conn.close()
    except (DatastoreError, sqlite3.Error) as exc:
        raise MigrationRefused("ledger_unreadable", f"the install ledger cannot be read: {type(exc).__name__}") from exc
    return [dataclasses.asdict(r) for r in rows if r.kind == kinds.KIND_CPLUG and r.source_index_url != _BUILTIN_SOURCE and "/" in r.item_id]


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sources(state_dir: Path) -> List[Path]:
    registry = registry_files.registry_path(state_dir)
    paths = [registry_files.legacy_path(state_dir, n) for n in registry_files.LEGACY_FILES] + [registry, registry.with_suffix(".json.bak")]
    return [p for p in paths if p.exists()]


def _post_retired_shas(folder: Path) -> Dict[str, str]:
    try:
        found = json.loads((folder / POST_RETIRED_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def record_post_retired(state_dir: Path, backup: Path) -> None:
    try:
        shas = {p.name: _sha(p) for p in _sources(state_dir)}
        (backup / POST_RETIRED_NAME).write_text(json.dumps(shas, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("plugin_registry_post_retired_record_failed", error_type=type(exc).__name__, backup=backup.name)


def reusable_backup(state_dir: Path, rows: List[Dict[str, Any]]) -> Optional[Path]:
    try:
        folders = registry_files.backups_newest_first(state_dir)
        if not folders:
            return None
        newest = folders[0]
        after = _post_retired_shas(newest)
        same = all(_sha(p) in {_sha(newest / p.name) if (newest / p.name).is_file() else "", after.get(p.name, "")} for p in _sources(state_dir))
        dump = newest / LEDGER_DUMP_NAME
        return newest if same and dump.exists() and json.loads(dump.read_text(encoding="utf-8")) == json.loads(json.dumps(rows)) else None
    except (OSError, ValueError):
        return None


def back_up(state_dir: Path, generation: int, rows: List[Dict[str, Any]]) -> Path:
    reused = reusable_backup(state_dir, rows)
    if reused is not None:
        return reused
    target = pick_backup_dir(state_dir, generation)
    sources = _sources(state_dir)
    try:
        target.mkdir(parents=True)
        for src in sources:
            shutil.copy2(src, target / src.name)
            _fsync(target / src.name)
            if _sha(src) != _sha(target / src.name):
                raise OSError(f"{src.name}: the copy does not read back identical")
        dump = target / LEDGER_DUMP_NAME
        dump.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _fsync(dump)
        if json.loads(dump.read_text(encoding="utf-8")) != json.loads(json.dumps(rows)):
            raise OSError("the ledger dump does not read back identical")
    except (OSError, ValueError) as exc:
        raise MigrationRefused("backup_failed", f"the backup could not be written and verified: {type(exc).__name__}: {exc}") from exc
    return target


def ledger_copy(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["item_id"].partition("/")[2]: {k: r.get(k) for k in LEDGER_COPY_FIELDS} for r in rows}


def build(docs: Dict[str, Dict[str, Any]], generation: int, rows: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    block = {"version": registry_files.MIGRATION_VERSION, "migrated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    carry: Dict[str, Any] = {registry_files.MIGRATION_KEY: block}
    copies = ledger_copy(rows)
    if copies:
        carry[registry_files.LEDGER_COPY_KEY] = copies
    return registry_projection.build_document(generation=generation, docs=docs, carry=carry)


def _stage(root: Path, name: str, files: Dict[str, Any]) -> Path:
    folder = root / name
    (folder / registry_files.STATE_DIR_NAME).mkdir(parents=True)
    for rel, doc in files.items():
        (folder / registry_files.STATE_DIR_NAME / rel).write_text(json.dumps(doc), encoding="utf-8")
    return folder


def _read_everything(folder: Path) -> Dict[str, Any]:
    entries = {i: owner_state.stored_entry(folder, i) for i in owner_state.stored_ids(folder)}
    records = identity.installs(folder)
    return {"state.ids": list(owner_state.stored_ids(folder)), "state.entries": entries,
            "installs": [dataclasses.astuple(r) for r in records], "installs.removed": {r.name: identity.removal_of(folder, r.name) for r in records},
            "sideload.items": dict(sideload.items(folder)), "sideload.hours": sideload.duration_hours(folder), "sideload.expires_at": sideload.expires_at(folder), "third_party": owner_switch.read(folder)}


def compare(docs: Dict[str, Dict[str, Any]], candidate: Dict[str, Any], scratch: Path) -> None:
    joined = registry_projection.join(candidate)
    wanted = registry_projection.normalize(docs)
    for name in registry_files.LEGACY_FILES:
        if joined[name] != wanted[name]:
            raise MigrationRefused("compare_failed", f"{registry_files.LEGACY_FILES[name]} does not survive the copy", item=name, field_name=_first_difference(wanted[name], joined[name]))
    old = _stage(scratch, "old", {registry_files.LEGACY_FILES[n]: d for n, d in docs.items() if d})
    new = _stage(scratch, "new", {registry_files.REGISTRY_FILE: candidate})
    try:
        seen_old, seen_new = _read_everything(old), _read_everything(new)
    except (identity.LedgerUnreadable, owner_state.StateUnreadable, sideload.SideloadRefused) as exc:
        raise MigrationRefused("unreadable_store", f"a store cannot be read by the old readers: {type(exc).__name__}") from exc
    for key in seen_old:
        if seen_old[key] != seen_new[key]:
            raise MigrationRefused("compare_failed", f"the readers disagree on {key}", item=_item_of(seen_old[key], seen_new[key]), field_name=key)


def _first_difference(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    return next((k for k in sorted({*a, *b}) if a.get(k) != b.get(k)), "")


def _item_of(a: Any, b: Any) -> str:
    if isinstance(a, dict) and isinstance(b, dict):
        return next((str(k) for k in sorted({*a, *b}, key=str) if a.get(k) != b.get(k)), "")
    return ""


def migrate(state_dir: Path, *, retired: Callable[[], None], now: Optional[datetime] = None) -> MigrationResult:
    stamp = now or datetime.now(timezone.utc)
    generation = max(registry_files.read_generation(state_dir) or 0, registry_files.marker_generation(state_dir)) + 1
    backup: Optional[Path] = None
    try:
        rows = ledger_rows(state_dir)
        read_old_documents(state_dir)
        backup = back_up(state_dir, generation, rows)
        retired()
        docs = read_old_documents(state_dir)
        candidate = build(docs, generation, ledger_rows(state_dir), stamp)
        with tempfile.TemporaryDirectory(dir=backup, prefix="compare-") as scratch:
            compare(docs, candidate, Path(scratch))
        return _commit(state_dir, candidate, backup, generation)
    except OSError as exc:
        return _refused(MigrationRefused("io_failed", f"{type(exc).__name__}: {exc}"), backup)
    except MigrationRefused as refusal:
        return _refused(refusal, backup)


def _refused(refusal: MigrationRefused, backup: Optional[Path]) -> MigrationResult:
    logger.error("plugin_registry_migration_refused", code=refusal.code, item=refusal.item, field=refusal.field_name, detail=str(refusal)[:200])
    return MigrationResult(OUTCOME_REFUSED, backup=backup, refusal=refusal)


def _commit(state_dir: Path, candidate: Dict[str, Any], backup: Path, generation: int) -> MigrationResult:
    try:
        moves = plugin_layout.plan_moves(state_dir)
        plugin_layout.apply_moves(moves, backup / JOURNAL_NAME)
    except OSError as exc:
        raise MigrationRefused("layout_move_failed", f"the plugin folders could not be moved: {exc}") from exc
    try:
        registry_files.write_registry(registry_files.registry_path(state_dir), candidate)
    except (OSError, ValueError, TypeError) as exc:
        _undo_quietly(moves)
        raise MigrationRefused("write_failed", f"plugins.json could not be written: {type(exc).__name__}") from exc
    try:
        registry_files.record_marker(state_dir, generation, migration_version=registry_files.MIGRATION_VERSION,
                                     migrated_at=candidate[registry_files.MIGRATION_KEY]["migrated_at"])
    except (OSError, sqlite3.Error, DatastoreError) as exc:
        logger.warning("plugin_registry_marker_failed", error_type=type(exc).__name__, generation=generation)
    if not registry_files.mirror(state_dir, registry_projection.join(candidate), generation):
        logger.error("plugin_registry_mirror_incomplete", generation=generation)
    logger.info("plugin_registry_migrated", generation=generation, moved=len(moves), backup=backup.name)
    return MigrationResult(OUTCOME_MIGRATED, generation=generation, backup=backup, moved=[str(m.dst) for m in moves])


def _undo_quietly(moves: List[plugin_layout.Move]) -> None:
    try:
        plugin_layout.undo_moves(moves)
    except plugin_layout.LayoutMoveFailed as exc:
        logger.error("plugin_layout_undo_incomplete", detail=str(exc)[:200])
