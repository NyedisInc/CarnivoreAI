from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.hosts.identity import is_remote_root
from src.core.project_store import list_projects
from src.core.stats.plugin.extract import project_key

logger = structlog.get_logger()

OTHER_GROUP = "@folders"
OTHER_PUBLIC_KEY = "project:other-folders"
CACHE_SECONDS = 30.0

_APP_DB_FOLDERS: Tuple[str, ...] = (
    "SELECT DISTINCT working_dir FROM sessions WHERE working_dir IS NOT NULL AND working_dir != ''",
    "SELECT DISTINCT working_dir FROM conversation_index WHERE working_dir IS NOT NULL AND working_dir != ''",
    "SELECT root FROM project_tombstones",
)


def other_label(count: int) -> str:
    return f"{count} folder outside projects" if count == 1 else f"{count} folders outside projects"


def _safe_name(label: str) -> str:
    if "/" in label or "\\" in label:
        return PurePath(label.replace("\\", "/")).name
    return label


@dataclass
class ProjectGroups:

    group: Dict[str, str] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    folders: Dict[str, str] = field(default_factory=dict)

    def group_of(self, raw: str) -> str:
        return self.group.get(raw, OTHER_GROUP)

    def folder_of(self, raw: str) -> Optional[str]:
        return self.folders.get(raw)

    def conversation_label(self, raw: str) -> str:
        group = self.group_of(raw)
        if group != OTHER_GROUP:
            return self.labels[group]
        return self.folders.get(raw) or other_label(1)

    def other_detail(self, members: Iterable[str]) -> Dict[str, object]:
        keys = list(dict.fromkeys(members))
        names: List[str] = []
        for raw in keys:
            name = self.folders.get(raw)
            if name and name not in names:
                names.append(name)
        unnamed = sum(1 for raw in keys if raw not in self.folders)
        return {"count": len(keys), "folders": names, "unnamed": unnamed}


def _registered(app_db: sqlite3.Connection) -> List[Tuple[str, str, List[str]]]:
    found: List[Tuple[str, str, List[str]]] = []
    for row in list_projects(app_db, include_archived=True):
        label = _safe_name((row["display_name"] or "").strip())
        root = row["root"]
        if not label or not root or is_remote_root(root):
            continue
        spellings = [p for p in (row["root"], row["raw_path"]) if p and not is_remote_root(p)]
        found.append((os.path.realpath(os.path.expanduser(root)), label, spellings))
    found.sort(key=lambda item: len(item[0]), reverse=True)
    return found


TRANSCRIPT_PROBE_BYTES = 65536
_dir_cwd: Dict[str, Optional[str]] = {}


def _first_cwd(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            head = handle.read(TRANSCRIPT_PROBE_BYTES)
    except OSError as exc:
        logger.debug("stats_project_transcript_unreadable", error=str(exc))
        return None
    for line in head.split(b"\n"):
        if b'"cwd"' not in line:
            continue
        try:
            value = json.loads(line).get("cwd")
        except (ValueError, AttributeError):
            continue
        if isinstance(value, str) and value:
            return value
    return None


def _transcript_folders(app_db: sqlite3.Connection) -> List[str]:
    rows = app_db.execute(
        "SELECT path FROM transcript_files WHERE family = 'claude' AND kind = 'conversation' "
        "AND status != 'gone' AND dataless = 0").fetchall()
    newest: Dict[str, str] = {}
    for (path,) in rows:
        newest.setdefault(os.path.dirname(path), path)
    for folder, path in newest.items():
        if folder not in _dir_cwd:
            _dir_cwd[folder] = _first_cwd(path)
    return [cwd for folder, cwd in _dir_cwd.items() if cwd and folder in newest]


def known_folders(app_db: Optional[sqlite3.Connection]) -> List[str]:
    paths: List[str] = []
    if app_db is not None:
        try:
            paths.extend(_transcript_folders(app_db))
        except sqlite3.Error as exc:
            logger.debug("stats_project_transcripts_unreadable", error=str(exc))
        for sql in _APP_DB_FOLDERS:
            try:
                paths.extend(row[0] for row in app_db.execute(sql))
            except sqlite3.Error as exc:
                logger.debug("stats_project_folders_unreadable", sql=sql[:40], error=str(exc))
    return [p for p in paths if isinstance(p, str) and p and not is_remote_root(p)]


def resolve(store) -> ProjectGroups:
    groups = ProjectGroups()
    try:
        app_db = connect(db_path_for(store.state_dir), create=False)
    except DatastoreUnreadableError as exc:
        logger.warning("stats_project_groups_app_db_unreadable", error=str(exc))
        app_db = None
    try:
        registered = _registered(app_db) if app_db is not None else []
        folders = known_folders(app_db)
    except sqlite3.Error as exc:
        logger.warning("stats_project_groups_failed", error=str(exc))
        registered, folders = [], []
    finally:
        if app_db is not None:
            app_db.close()
    for root, label, spellings in registered:
        group = project_key(root)
        groups.labels.setdefault(group, label)
        for path in spellings:
            groups.group.setdefault(project_key(path), group)
    for path in folders:
        real = os.path.realpath(os.path.expanduser(path))
        raw = project_key(real)
        groups.folders.setdefault(raw, PurePath(real).name or real)
        if raw in groups.group:
            continue
        for root, _label, _spellings in registered:
            if real == root or real.startswith(root.rstrip("/") + "/"):
                groups.group[raw] = project_key(root)
                break
    return groups


_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[float, ProjectGroups]] = {}


def groups_for(store, *, now: Optional[float] = None) -> ProjectGroups:
    clock = time.monotonic() if now is None else now
    key = str(store.state_dir)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and clock - hit[0] < CACHE_SECONDS:
            return hit[1]
    fresh = resolve(store)
    with _cache_lock:
        _cache[key] = (clock, fresh)
    return fresh


def forget() -> None:
    with _cache_lock:
        _cache.clear()
