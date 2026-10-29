
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.blobcodec.place import PlaceConflict, PlaceMismatch, file_matches, sha256_file, write_verified
from src.core.crate_format.backup_files import is_backup_point_file
from src.core.crate_format.constants import HOME_PLUGIN_PREFIX, ROLE_PLUGIN_FILE
from src.core.crate_format.errors import CrateError
from src.core.crate_format.model_files import FileRecord
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import files_place, task_files_in, undo
from src.core.crate_import import idmap as ids_keys
from src.core.crate_import.env import BoardRelinkFailed, ImportEnv, StoreHome
from src.core.crate_import.idmap import IdMap
from src.core.crate_import.model import W_BOARD_UNLINKED, W_STORE_NO_FOLDER, W_STORE_PLUGIN_OFF, W_STORE_UNLOCATED, Collector
from src.core.inventory.plugin_units import BOARD_SIDECAR, MAX_BOARD_DEPTH
from src.cplugs.sdk import task_folders

logger = structlog.get_logger()

BESIDE_DIR = ".crate-import"
PURGE_KEPT = "kept"
MAX_SIDECAR_BYTES = 16 * 1024 * 1024
MAX_COMPARE_FILES = 20_000
MARKERS = (task_folders.PROJECT_MARKER, task_folders.TASK_MARKER)
PLACE, SAME, BESIDE = "place", "same", "beside"
RECEIPT_SUBDIR = "plugin-data"


@dataclass
class Unit:

    slug: str
    rel: str
    files: List[Tuple[str, FileRecord]] = field(default_factory=list)
    old_item: Optional[int] = None
    old_list: Optional[str] = None
    sidecar_sha: Optional[str] = None


@dataclass
class Store:

    plugin: str
    data: str
    records: List[FileRecord] = field(default_factory=list)
    units: List[Unit] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.plugin}.{self.data}"

    def below(self, record: FileRecord) -> str:
        return record.rel[len(self.data) + 1:]


UndoLog = Callable[[Dict[str, Any]], None]
SCOPE_RECEIPT = "receipt"


def store_scope(store: "Store") -> Dict[str, Any]:
    return {"store": [store.plugin, store.data]}


def undo_roots(entries: List[Dict[str, Any]], env: ImportEnv, import_id: Optional[str]) -> List[Path]:
    roots: List[Path] = []
    for entry in entries:
        store = entry.get("store")
        if isinstance(store, list) and len(store) == 2:
            home = env.plugin_homes(str(store[0]), str(store[1]))
            if home is not None:
                roots.append(Path(home.root))
        if entry.get(SCOPE_RECEIPT) is True and import_id:
            roots.append(env.backup_dir(import_id).parent)
        if entry.get("task_files") is True:
            roots.append(Path(env.state).joinpath(*task_files_in.FILES_DIR))
    return list(dict.fromkeys(roots))


def _store_of(record: FileRecord) -> Optional[Tuple[str, str]]:
    if record.role != ROLE_PLUGIN_FILE or not record.home.startswith(HOME_PLUGIN_PREFIX):
        return None
    plugin = record.home[len(HOME_PLUGIN_PREFIX):]
    data = str(record.extra.get("data") or record.rel.split("/", 1)[0])
    if is_backup_point_file(record.role, record.home, record.rel, record.extra):
        return None
    return (plugin, data) if plugin and data and record.rel.startswith(data + "/") and len(record.rel) > len(data) + 1 else None


def _json_of(reader: CrateReader, record: FileRecord) -> Dict[str, Any]:
    if record.length > MAX_SIDECAR_BYTES:
        return {}
    try:
        value = json.loads(b"".join(reader.file_chunks(record)))
    except (ValueError, CrateError):
        return {}
    return value if isinstance(value, dict) else {}


def _int_or_none(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def sidecar_fingerprint(sidecar: Dict[str, Any]) -> str:
    body = {k: v for k, v in sidecar.items() if k != "task"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def stores_of(reader: CrateReader) -> List[Store]:
    found: Dict[Tuple[str, str], Store] = {}
    for record in reader.files():
        key = _store_of(record)
        if key is not None:
            found.setdefault(key, Store(*key)).records.append(record)
    for store in found.values():
        by_rel = {store.below(r): r for r in store.records}
        for below, record in sorted(by_rel.items()):
            if os.path.basename(below) != BOARD_SIDECAR:
                continue
            unit_rel = os.path.dirname(below)
            unit = Unit(slug=os.path.basename(unit_rel), rel=unit_rel,
                        files=[(r_below[len(unit_rel) + 1:], r) for r_below, r in sorted(by_rel.items())
                               if r_below.startswith(unit_rel + "/") and os.path.basename(r_below) not in MARKERS])
            if not unit.slug:
                continue
            sidecar = _json_of(reader, record)
            unit.sidecar_sha = sidecar_fingerprint(sidecar)
            task = sidecar.get("task")
            unit.old_item = _int_or_none(task.get("item_id")) if isinstance(task, dict) else None
            parts = unit_rel.split("/")
            for depth in range(len(parts) - 1, 0, -1):
                ancestor = "/".join(parts[:depth])
                if unit.old_item is None and f"{ancestor}/{task_folders.TASK_MARKER}" in by_rel:
                    unit.old_item = _int_or_none(_json_of(reader, by_rel[f"{ancestor}/{task_folders.TASK_MARKER}"]).get("item_id"))
                if unit.old_list is None and f"{ancestor}/{task_folders.PROJECT_MARKER}" in by_rel:
                    listed = _json_of(reader, by_rel[f"{ancestor}/{task_folders.PROJECT_MARKER}"]).get("list")
                    unit.old_list = str(listed) if isinstance(listed, (str, int)) and not isinstance(listed, bool) else None
            store.units.append(unit)
    return [found[k] for k in sorted(found)]


def find_board(root: Path, slug: str) -> Optional[Path]:
    stack: List[Tuple[Path, int]] = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                        continue
                    here = Path(entry.path)
                    if entry.name == slug and (here / BOARD_SIDECAR).is_file() and not (here / BOARD_SIDECAR).is_symlink():
                        return here
                    if depth + 1 < MAX_BOARD_DEPTH:
                        stack.append((here, depth + 1))
        except OSError:
            continue
    return None


def _digest(folder: Path) -> Optional[Dict[str, str]]:
    out: Dict[str, str] = {}
    for current, dirs, names in os.walk(folder, followlinks=False):
        if any(os.path.islink(os.path.join(current, d)) for d in dirs):
            return None
        for name in names:
            full = os.path.join(current, name)
            if not stat.S_ISREG(os.lstat(full).st_mode) or len(out) >= MAX_COMPARE_FILES:
                return None
            out[os.path.relpath(full, folder).replace(os.sep, "/")] = sha256_file(Path(full))
    return out


def board_outcome(unit: Unit, root: Path) -> Tuple[str, Optional[Path]]:
    existing = find_board(root, unit.slug)
    if existing is None:
        return PLACE, None
    try:
        local = _digest(existing)
    except OSError:
        local = None
    theirs = {rel: record.content_sha256 for rel, record in unit.files}
    if local is not None and BOARD_SIDECAR in local and BOARD_SIDECAR in theirs:
        try:
            local[BOARD_SIDECAR] = sidecar_fingerprint(json.loads((existing / BOARD_SIDECAR).read_text()))
        except (OSError, ValueError, AttributeError):
            local = None
        theirs[BOARD_SIDECAR] = unit.sidecar_sha or ""
    return (SAME, existing) if local is not None and local == theirs else (BESIDE, existing)


def linked_item(folder: Path) -> Optional[int]:
    path = folder / BOARD_SIDECAR
    try:
        if path.is_symlink() or path.stat().st_size > MAX_SIDECAR_BYTES:
            return None
        task = json.loads(path.read_text()).get("task")
    except (OSError, ValueError, AttributeError):
        return None
    return _int_or_none(task.get("item_id")) if isinstance(task, dict) else None


@dataclass
class PluginDataOutcome:

    written: int = 0
    same: int = 0
    boards: List[Dict[str, Any]] = field(default_factory=list)
    unlocated: List[str] = field(default_factory=list)
    not_restored: List[Dict[str, str]] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)

    def as_json(self) -> Dict[str, Any]:
        return {"written": self.written, "same": self.same, "boards": list(self.boards), "unlocated": list(self.unlocated),
                "not_restored": list(self.not_restored), "kept": list(self.kept), "failed": list(self.failed)}


def unlocated_reason(store: Store, env: ImportEnv) -> str:
    if not store.units:
        return W_STORE_UNLOCATED
    return W_STORE_NO_FOLDER if env.plugin_enabled(store.plugin) else W_STORE_PLUGIN_OFF


def _has_place(store: Store, env: ImportEnv) -> Optional[StoreHome]:
    if store.units and not env.plugin_enabled(store.plugin):
        return None
    return env.plugin_homes(store.plugin, store.data)


def preview(stores: List[Store], env: ImportEnv, request_ticked: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for store in stores:
        home = _has_place(store, env)
        decision = "not_ticked" if not request_ticked else ("restore" if home is not None else "unlocated")
        boards = []
        if decision == "restore" and home is not None:
            boards = [{"slug": u.slug, "outcome": board_outcome(u, home.root)[0]} for u in store.units]
        out.append({"store": store.key, "files": len(store.records), "bytes": sum(r.length for r in store.records),
                    "decision": decision, "reason": unlocated_reason(store, env) if decision == "unlocated" else None, "boards": boards})
    return out


def _put(reader: CrateReader, record: FileRecord, dest: Path, root: Path, out: PluginDataOutcome,
         log: Optional[UndoLog] = None, scope: Optional[Dict[str, Any]] = None) -> str:
    problem = files_place.contained(dest, root)
    if problem is not None:
        out.failed.append(f"{dest}: {problem}")
        return "failed"
    try:
        info = os.lstat(dest)
    except FileNotFoundError:
        info = None
    except OSError as exc:
        out.failed.append(f"{dest}: {type(exc).__name__}")
        return "failed"
    if info is not None:
        if stat.S_ISREG(info.st_mode) and file_matches(dest, record.content_sha256, record.length):
            out.same += 1
            return "same"
        out.kept.append(str(dest))
        return "kept"
    try:
        if log is not None:
            for entry in undo.creation_entries(dest, root, record.content_sha256, record.length, scope or {}):
                log(entry)
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_verified(reader.file_chunks(record), dest, length=record.length, sha256=record.content_sha256, mode=record.mode,
                       mtime_ns=record.mtime_ns)
    except PlaceConflict:
        out.kept.append(str(dest))
        return "kept"
    except (PlaceMismatch, CrateError, OSError) as exc:
        logger.warning("crate_import_plugin_file_failed", dest=str(dest), error_type=type(exc).__name__)
        out.failed.append(f"{dest}: {type(exc).__name__}")
        return "failed"
    out.written += 1
    return "written"


def _announcer(log: Optional[UndoLog], scope: Optional[Dict[str, Any]]) -> Optional[task_folders.Before]:
    if log is None:
        return None

    def before(kind: str, path: Path, match: Optional[Dict[str, Any]]) -> None:
        log({**(undo.marker_entry(path, match or {}) if kind == "marker" else undo.dir_entry(path)), **(scope or {})})

    return before


def _task_folder(conn: Any, root: Path, new_item: int, before: Optional[task_folders.Before] = None) -> Optional[Path]:
    row = conn.execute("SELECT list_key, title, text FROM work_items WHERE id = ?", (new_item,)).fetchone()
    if row is None:
        return None
    name = None
    if str(row["list_key"]).isdigit():
        found = conn.execute("SELECT display_name FROM projects WHERE id = ?", (int(row["list_key"]),)).fetchone()
        name = found["display_name"] if found else None
    return task_folders.ensure_task(root, new_item, str(row["list_key"]), name, row["title"] or row["text"], before)


def _board_target(conn: Any, root: Path, unit: Unit, idmap: IdMap, before: Optional[task_folders.Before] = None) -> Tuple[Path, Optional[int]]:
    new_item = idmap.get(ids_keys.WORK_ITEMS, unit.old_item) if unit.old_item is not None else None
    if new_item is not None:
        task = _task_folder(conn, root, int(new_item), before)
        if task is not None:
            return task_folders.kind_dir(task, task_folders.BOARDS, before=before) / unit.slug, int(new_item)
    new_list = idmap.get(ids_keys.PROJECTS, unit.old_list) if unit.old_list is not None and str(unit.old_list).isdigit() else None
    if new_list is not None:
        row = conn.execute("SELECT display_name FROM projects WHERE id = ?", (int(new_list),)).fetchone()
        return task_folders.ensure_project(root, str(new_list), row["display_name"] if row else None, before) / unit.slug, None
    return root / unit.slug, None


def _place_board(reader: CrateReader, unit: Unit, store: Store, root: Path, import_id: str, conn: Any, idmap: IdMap,
                 out: PluginDataOutcome, log: Optional[UndoLog] = None) -> Optional[Tuple[str, int]]:
    outcome, existing = board_outcome(unit, root)
    state, base, item = outcome, None, None
    if outcome == PLACE:
        base, item = _board_target(conn, root, unit, idmap, _announcer(log, store_scope(store)))
    elif outcome == BESIDE:
        base = root / BESIDE_DIR / import_id / store.data / unit.rel
    if outcome == SAME and existing is not None and unit.old_item is not None:
        wanted = idmap.get(ids_keys.WORK_ITEMS, unit.old_item)
        if wanted is not None and wanted != unit.old_item and linked_item(existing) in (unit.old_item, None):
            try:
                at_target = _board_target(conn, root, unit, idmap, _announcer(log, store_scope(store)))[0] == existing
            except OSError:
                at_target = False
            item = int(wanted) if at_target else item
    entry = {"slug": unit.slug, "state": state, "path": str(base or existing), "old_item": unit.old_item, "new_item": item, "relinked": None}
    out.boards.append(entry)
    if base is None:
        out.same += len(unit.files)
        return (unit.slug, item) if item is not None and outcome == SAME else None
    results = {_put(reader, record, base / rel, root, out, log, store_scope(store)) for rel, record in unit.files}
    entry["state"] = state if not results & {"failed"} else "failed"
    return (unit.slug, item) if state == PLACE and item is not None and item != unit.old_item and entry["state"] == PLACE else None


def _log_relinked_sidecar(sidecar: Path, log: UndoLog, store: Optional["Store"], before: Optional[bytes] = None,
                          keep_in: Optional[Path] = None) -> None:
    try:
        info = os.lstat(sidecar)
        if store is None or not stat.S_ISREG(info.st_mode):
            return
        if before is None:
            log({**undo.file_entry(sidecar, sha256_file(sidecar), info.st_size), **store_scope(store)})
        elif keep_in is not None and hashlib.sha256(before).hexdigest() != sha256_file(sidecar):
            keep_in.mkdir(parents=True, exist_ok=True)
            backup = keep_in / BOARD_SIDECAR
            backup.write_bytes(before)
            log({**undo.grow_entry(sidecar, backup, hashlib.sha256(before).hexdigest(), len(before), sha256_file(sidecar), info.st_size),
                 **store_scope(store)})
    except OSError as exc:
        logger.warning("crate_import_relinked_sidecar_not_logged", error_type=type(exc).__name__)


def _place_files(reader: CrateReader, store: Store, home: StoreHome, import_id: str, out: PluginDataOutcome,
                 log: Optional[UndoLog] = None) -> None:
    boards = {record.rel for u in store.units for _rel, record in u.files} | {
        record.rel for record in store.records if os.path.basename(record.rel) in MARKERS and store.units}
    for record in store.records:
        if record.rel in boards:
            continue
        dest = home.root / store.below(record)
        verdict = _put(reader, record, dest, home.root, out, log, store_scope(store))
        if verdict == "kept" and home.purge == PURGE_KEPT:
            _put(reader, record, home.root / BESIDE_DIR / import_id / store.data / store.below(record), home.root, out, log, store_scope(store))


def _keep_in_receipts(reader: CrateReader, store: Store, env: ImportEnv, import_id: str, col: Collector, out: PluginDataOutcome,
                      log: Optional[UndoLog] = None) -> None:
    col.warn(W_STORE_UNLOCATED, store.key)
    out.unlocated.append(store.key)
    receipt = env.backup_dir(import_id).parent
    base = receipt / RECEIPT_SUBDIR / store.plugin / store.data
    for record in store.records:
        _put(reader, record, base / store.below(record), receipt, out, log, {SCOPE_RECEIPT: True})


def _made_default(home: StoreHome) -> bool:
    try:
        task_folders.ensure_root(Path(home.root))
    except OSError as exc:
        logger.warning("crate_import_default_store_not_made", path=str(home.root), error_type=type(exc).__name__)
        return False
    return True


def place_plugin_data(reader: CrateReader, env: ImportEnv, idmap: IdMap, import_id: str, col: Collector, conn: Any,
                      log: Optional[UndoLog] = None) -> PluginDataOutcome:
    out = PluginDataOutcome()
    relink: List[Tuple[str, int]] = []
    store_by_slug: Dict[str, Store] = {}
    for store in stores_of(reader):
        home = _has_place(store, env)
        if home is not None and home.default and store.units and not _made_default(home):
            home = None
        if home is None or not Path(home.root).is_dir() or Path(home.root).is_symlink():
            if store.units:
                reason = unlocated_reason(store, env)
                col.warn(reason, store.key)
                out.not_restored.append({"what": f"plugin_data:{store.key}", "why": reason})
            else:
                _keep_in_receipts(reader, store, env, import_id, col, out, log)
            continue
        for unit in store.units:
            try:
                moved = _place_board(reader, unit, store, Path(home.root), import_id, conn, idmap, out, log)
            except OSError as exc:
                out.failed.append(f"{unit.slug}: {type(exc).__name__}")
                continue
            if moved is not None:
                relink.append(moved)
                store_by_slug[moved[0]] = store
        _place_files(reader, store, home, import_id, out, log)
    for slug, item in relink:
        placed_board = next(b for b in out.boards if b["slug"] == slug)
        sidecar_path = Path(str(placed_board["path"])) / BOARD_SIDECAR
        owed_again = placed_board["state"] == SAME
        try:
            before = sidecar_path.read_bytes() if owed_again else None
        except OSError:
            before = None
        try:
            done = bool(env.relink_board(slug, item))
        except BoardRelinkFailed as exc:
            logger.warning("crate_import_board_relink_failed", slug=slug, error=str(exc)[:120])
            done = False
        placed_board["relinked"] = done
        if done and log is not None and (before is not None or not owed_again):
            _log_relinked_sidecar(sidecar_path, log, store_by_slug.get(slug), before, env.backup_dir(import_id) / "relink" / slug)
        if not done:
            col.warn(W_BOARD_UNLINKED, f"{slug}: task {item}")
    return out
