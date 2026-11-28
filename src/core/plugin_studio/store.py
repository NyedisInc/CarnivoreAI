
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.core import config_writer
from src.core.plugin_studio.errors import StudioActionError, WorkspaceNotFoundError
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS

INDEX_DIR_NAME = "plugin-studio"
INDEX_FILE_NAME = "workspaces.json"
WORKSPACES_DIR_NAME = "workspaces"
INDEX_SCHEMA = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def studio_root(state_dir: Path) -> Path:
    return Path(state_dir) / INDEX_DIR_NAME


def workspaces_dir(state_dir: Path) -> Path:
    return studio_root(state_dir) / WORKSPACES_DIR_NAME


def index_path(state_dir: Path) -> Path:
    return studio_root(state_dir) / INDEX_FILE_NAME


def ensure_index(state_dir: Path) -> Path:
    root = studio_root(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    path = index_path(state_dir)
    try:
        config_writer.create_if_absent(
            path,
            {"schema": INDEX_SCHEMA, "workspaces": {}},
            file_mode=0o600,
        )
    except OSError as exc:
        raise StudioActionError(
            503,
            "studio_store_unwritable",
            f"Could not initialize Plugin Studio index: {type(exc).__name__}",
        ) from exc
    return path


def _read_doc(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"schema": INDEX_SCHEMA, "workspaces": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StudioActionError(
            503,
            "studio_store_unreadable",
            f"Plugin Studio index could not be read: {type(exc).__name__}",
        ) from exc
    if not isinstance(raw, dict):
        return {"schema": INDEX_SCHEMA, "workspaces": {}}
    workspaces = raw.get("workspaces")
    if not isinstance(workspaces, dict):
        raw["workspaces"] = {}
    return raw


def _commit_doc(
    state_dir: Path,
    mutate: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    path = ensure_index(state_dir)
    try:
        outcome = config_writer.commit(path, mutate, file_mode=0o600)
    except (OSError, ValueError, RuntimeError) as exc:
        raise StudioActionError(
            503,
            "studio_store_unwritable",
            f"Plugin Studio index could not be written: {type(exc).__name__}",
        ) from exc
    return copy.deepcopy(outcome.data)


def list_workspaces(state_dir: Path) -> List[Dict[str, Any]]:
    doc = _read_doc(index_path(state_dir))
    rows = [copy.deepcopy(v) for v in doc.get("workspaces", {}).values() if isinstance(v, dict)]
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return rows


def get_workspace(state_dir: Path, studio_id: str) -> Dict[str, Any]:
    doc = _read_doc(index_path(state_dir))
    row = doc.get("workspaces", {}).get(studio_id)
    if not isinstance(row, dict):
        raise WorkspaceNotFoundError(studio_id)
    return copy.deepcopy(row)


def upsert_workspace(state_dir: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    studio_id = str(record["studio_id"])

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        next_doc = copy.deepcopy(doc)
        if not isinstance(next_doc.get("workspaces"), dict):
            next_doc["workspaces"] = {}
        next_doc["schema"] = INDEX_SCHEMA
        next_doc["workspaces"][studio_id] = copy.deepcopy(record)
        return next_doc

    updated = _commit_doc(state_dir, _mutate)
    return copy.deepcopy(updated["workspaces"][studio_id])


def update_workspace(
    state_dir: Path,
    studio_id: str,
    mutate_row: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    _ = get_workspace(state_dir, studio_id)

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        next_doc = copy.deepcopy(doc)
        rows = next_doc.setdefault("workspaces", {})
        current = rows.get(studio_id)
        if not isinstance(current, dict):
            return next_doc
        updated_row = mutate_row(copy.deepcopy(current))
        updated_row["updated_at"] = utc_now_iso()
        rows[studio_id] = updated_row
        return next_doc

    updated = _commit_doc(state_dir, _mutate)
    row = updated.get("workspaces", {}).get(studio_id)
    if not isinstance(row, dict):
        raise WorkspaceNotFoundError(studio_id)
    return copy.deepcopy(row)


def remove_workspace(state_dir: Path, studio_id: str) -> Dict[str, Any]:
    removed = get_workspace(state_dir, studio_id)

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        next_doc = copy.deepcopy(doc)
        rows = next_doc.get("workspaces")
        if isinstance(rows, dict):
            rows.pop(studio_id, None)
        return next_doc

    _commit_doc(state_dir, _mutate)
    return removed


def contained_workspace_folder(state_dir: Path, raw_folder: str) -> Path:
    base_root = workspaces_dir(state_dir)
    if not base_root.exists():
        raise StudioActionError(404, "studio_workspace_folder_missing", "Workspace folder root does not exist.")
    root_real = Path(os.path.realpath(base_root))
    candidate = Path(raw_folder)
    if candidate.is_symlink() or not candidate.is_dir():
        raise StudioActionError(404, "studio_workspace_folder_missing", "Workspace folder is missing on disk.")
    folder_real = Path(os.path.realpath(candidate))
    if not folder_real.is_relative_to(root_real) or folder_real == root_real:
        raise StudioActionError(
            403,
            "studio_workspace_escape",
            "Workspace folder escapes Plugin Studio containment.",
        )
    return folder_real


def list_workspace_files(folder: Path) -> List[Dict[str, Any]]:
    if not folder.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in DEV_SKIP_DIRS)
        for fname in sorted(filenames):
            if fname == ".DS_Store" or fname.startswith("._") or fname.endswith((".pyc", ".pyo")):
                continue
            full = Path(dirpath) / fname
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if os.path.islink(full):
                continue
            out.append({
                "path": full.relative_to(folder).as_posix(),
                "size": st.st_size,
                "executable": bool(st.st_mode & 0o100),
            })
    return out
