
from __future__ import annotations

import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import structlog

from src.core.blobcodec.place import sha256_file
from src.core.project_move.paths import is_within

logger = structlog.get_logger()

OP_FILE = "file"
OP_DIR = "dir"
OP_GROW = "grow"
OP_LINK = "link"
OP_SETTINGS = "settings"
OP_MARKER = "marker"
OP_VAULT = "vault_point"
_SIDE_NAME = re.compile(r"^.+-\d{8}(-\d+)?$")


@dataclass
class UndoReport:

    removed: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    removed_dirs: List[str] = field(default_factory=list)

    @property
    def files_removed(self) -> int:
        return len(self.removed) - len(self.removed_dirs)


_FILE_OPS = (OP_FILE, OP_GROW, OP_VAULT, OP_MARKER, OP_SETTINGS, OP_LINK)


def log_counts(log: List[Dict[str, Any]]) -> Dict[str, int]:
    files = {(e.get("op"), str(e.get("path", ""))) if e.get("op") == OP_FILE else id(e) for e in log if e.get("op") in _FILE_OPS}
    return {"files": len(files), "folders": sum(1 for e in log if e.get("op") == OP_DIR)}


def file_entry(path: Path, sha256: str, length: int, side: Optional[Path] = None) -> Dict[str, Any]:
    return {"op": OP_FILE, "path": str(path), "sha256": sha256, "length": int(length), **_side(side)}


def link_entry(path: Path, target: str, side: Path) -> Dict[str, Any]:
    return {"op": OP_LINK, "path": str(path), "target": target, **_side(side)}


def settings_entry(path: Path, backup: Optional[Path], sha256: str, existed: bool) -> Dict[str, Any]:
    return {"op": OP_SETTINGS, "path": str(path), "backup": str(backup) if backup else None, "sha256": sha256, "existed": existed}


def marker_entry(path: Path, match: Dict[str, Any]) -> Dict[str, Any]:
    return {"op": OP_MARKER, "path": str(path), "match": dict(match)}


def _undo_marker(entry: Dict[str, Any], path: str, info: os.stat_result, report: UndoReport) -> None:
    """Remove a marker file the import wrote, only while it is a regular file holding every logged field (someone else's file is kept)."""
    import json

    try:
        found = json.loads(Path(path).read_text(encoding="utf-8")) if stat.S_ISREG(info.st_mode) else None
    except (OSError, ValueError):
        found = None
    if isinstance(found, dict) and all(found.get(k) == v for k, v in (entry.get("match") or {}).items()):
        os.unlink(path)
        report.removed.append(path)
    else:
        report.kept.append(path)


def _side(side: Optional[Path]) -> Dict[str, Any]:
    return {"side": str(side)} if side is not None else {}


def grow_entry(path: Path, backup: Path, old_sha256: str, old_length: int, sha256: str, length: int) -> Dict[str, Any]:
    return {"op": OP_GROW, "path": str(path), "backup": str(backup), "old_sha256": old_sha256, "old_length": int(old_length),
            "sha256": sha256, "length": int(length)}


def _undo_grow(entry: Dict[str, Any], path: str, info: os.stat_result, report: UndoReport) -> None:
    if not stat.S_ISREG(info.st_mode):
        report.kept.append(path)
        return
    if info.st_size == entry.get("old_length") and sha256_file(path) == entry.get("old_sha256"):
        return
    backup = str(entry.get("backup", ""))
    if not (info.st_size == entry.get("length") and sha256_file(path) == entry.get("sha256")
            and backup and os.path.isfile(backup) and sha256_file(backup) == entry.get("old_sha256")):
        report.kept.append(path)
        return
    temp = f"{path}.{os.getpid()}.undo"
    shutil.copyfile(backup, temp)
    os.replace(temp, path)
    report.removed.append(path)


def dir_entry(path: Path, side: Optional[Path] = None) -> Dict[str, Any]:
    return {"op": OP_DIR, "path": str(path), **_side(side)}


def creation_entries(dest: Path, root: Path, sha256: str, length: int, scope: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The undo entries of a file about to be CREATED after the rows committed: a ``dir`` entry for each folder between ``root`` and
    the file that does not exist yet (outermost first, so the newest-first replay removes the file, then the inner folders) and the
    ``file`` entry. ``scope`` names which root the replay must resolve (``{"store": [plugin, data]}``, ``{"receipt": True}`` or
    ``{"task_files": True}``); the replay derives the root from the install, never from the entry. Blocking (it looks at the disk).
    Example: creation_entries(Path('/b/x/a.json'), Path('/b'), 'ab', 3, {'store': ['p', 'd']})[-1]['op'] -> 'file'"""
    missing: List[Path] = []
    folder = Path(dest).parent
    while folder != Path(root) and is_within(str(folder), str(root)) and not os.path.lexists(folder):
        missing.append(folder)
        folder = folder.parent
    return [*[{**dir_entry(d), **scope} for d in reversed(missing)], {**file_entry(Path(dest), sha256, length), **scope}]


def _allowed(path: str, roots: Sequence[Path]) -> bool:
    real_parent = os.path.realpath(os.path.dirname(path))
    return any(is_within(real_parent, os.path.realpath(str(root))) for root in roots)


def _in_side(entry: Dict[str, Any], path: str) -> bool:
    """Whether the entry names a side folder (a name ending in a crate date) and ``path`` is that folder or lies inside it.
    The one reach beyond the allowed roots: an import restoring project files makes its OWN new folder anywhere. Pure."""
    side = str(entry.get("side") or "")
    if not side or not os.path.isabs(side) or not is_within(path, side):
        return False
    if entry.get("project_root") is True:
        return len(Path(side).parts) >= 3
    return _SIDE_NAME.match(os.path.basename(side)) is not None


def _undo_settings(entry: Dict[str, Any], path: str, report: UndoReport) -> None:
    if sha256_file(path) != entry.get("sha256"):
        report.kept.append(path)
        return
    backup = entry.get("backup")
    if backup and os.path.isfile(backup):
        os.replace(backup, path)
        report.removed.append(path)
    elif not entry.get("existed"):
        os.unlink(path)
        report.removed.append(path)
    else:
        report.kept.append(path)


def _undo_vault_point(entry: Dict[str, Any], report: UndoReport) -> None:
    from src.core.deepsearch import fallback_hook as fb

    name = f"backup point {entry.get('unit')}/{entry.get('point_id')}"
    remover = next((s for s in fb.sources() if hasattr(s, "remove_adopted")), None)
    if remover is None:
        report.kept.append(name)
        return
    try:
        done = remover.remove_adopted([entry])
    except OSError as exc:
        report.errors.append(f"{name}: {type(exc).__name__}")
        return
    report.removed += [f"backup point {x}" for x in done.get("removed", [])]
    report.kept += [f"backup point {x}" for x in done.get("kept", [])]
    report.errors += list(done.get("errors", []))


def rollback(entries: Iterable[Dict[str, Any]], allowed_roots: Sequence[Path]) -> UndoReport:
    report = UndoReport()
    log = list(entries)
    seen_files: Dict[str, int] = {}
    for entry in log:
        if entry.get("op") == OP_FILE:
            seen_files[str(entry.get("path", ""))] = seen_files.get(str(entry.get("path", "")), 0) + 1
    for entry in reversed(log):
        if entry.get("op") == OP_VAULT:
            _undo_vault_point(entry, report)
            continue
        path, op = str(entry.get("path", "")), entry.get("op")
        if not path or op not in (OP_FILE, OP_DIR, OP_GROW, OP_LINK, OP_SETTINGS, OP_MARKER) or not (_allowed(path, allowed_roots) or _in_side(entry, path)):
            report.kept.append(path)
            logger.warning("crate_import_undo_entry_refused", path=path, op=op)
            continue
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            report.errors.append(f"{path}: {type(exc).__name__}")
            continue
        try:
            if op == OP_GROW:
                _undo_grow(entry, path, info, report)
            elif op == OP_SETTINGS:
                _undo_settings(entry, path, report)
            elif op == OP_MARKER:
                _undo_marker(entry, path, info, report)
            elif op == OP_FILE:
                if stat.S_ISREG(info.st_mode) and info.st_size == entry.get("length") and sha256_file(path) == entry.get("sha256"):
                    os.unlink(path)
                    report.removed.append(path)
                    seen_files[path] = 0
                elif seen_files.get(path, 0) > 1:
                    seen_files[path] -= 1
                else:
                    report.kept.append(path)
            elif op == OP_LINK:
                if stat.S_ISLNK(info.st_mode) and os.readlink(path) == entry.get("target"):
                    os.unlink(path)
                    report.removed.append(path)
                else:
                    report.kept.append(path)
            elif stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                try:
                    os.rmdir(path)
                    report.removed.append(path)
                    report.removed_dirs.append(path)
                except OSError:
                    report.kept.append(path)
            else:
                report.kept.append(path)
        except OSError as exc:
            report.errors.append(f"{path}: {type(exc).__name__}")
    return report
