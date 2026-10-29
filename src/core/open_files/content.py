
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import config_files
from src.core.open_files.open_list import OpenFile
from src.core.open_files.session_folder import SessionNotFound, working_dir_for

logger = structlog.get_logger(__name__)

TOO_LARGE = "too_large"
NOT_TEXT = "not_text"
GONE = "gone"
UNAVAILABLE = "unavailable"


class RowNotEditable(ValueError):
    pass


def project_path_for(db_path: Path, session_uuid: str, root: str) -> Optional[str]:
    folder = working_dir_for(db_path, session_uuid)
    return folder if root == "workdir" else None


class OpenRefused(ValueError):
    """A file cannot be opened as a row: a bad path, a root a diff cannot name, or no file there."""


class NothingToOpen(OpenRefused):
    pass


def _plain_relative(path: str) -> str:
    raw = path.strip()
    parts = raw.split("/")
    if not raw or "\0" in raw or raw.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise OpenRefused("path must be relative, without '..'")
    return raw


def checked_path(db_path: Path, kind: str, root: str, path: str, session_uuid: str) -> str:
    project_path = project_path_for(db_path, session_uuid, root)
    if kind == "diff":
        if root != "workdir":
            raise OpenRefused("a diff names a path in the session's folder")
        return _plain_relative(path)
    try:
        resolved = config_files.resolve_safe_path(root, path, project_path)
    except config_files.ConfigFileError as exc:
        raise OpenRefused(str(exc)) from exc
    if not resolved.is_file():
        raise NothingToOpen("not a file")
    return path.strip().strip("/")


def _unviewable(row: OpenFile, reason: str, detail: str) -> Dict[str, Any]:
    return {"id": row.id, "viewable": False, "reason": reason, "detail": detail}


def read(db_path: Path, row: OpenFile) -> Dict[str, Any]:
    try:
        project_path = project_path_for(db_path, row.session_uuid, row.root)
    except SessionNotFound:
        return _unviewable(row, UNAVAILABLE, "the session this file was opened from is gone")
    try:
        result = config_files.read_file(row.root, row.path, project_path)
    except config_files.FileTooLargeError as exc:
        return _unviewable(row, TOO_LARGE, str(exc))
    except config_files.FileNotTextError as exc:
        return _unviewable(row, NOT_TEXT, str(exc))
    except config_files.NotAFileError as exc:
        return _unviewable(row, GONE, str(exc))
    except config_files.ConfigFileError as exc:
        logger.info("open_files_read_unavailable", file_id=row.id, root=row.root, error=str(exc))
        return _unviewable(row, UNAVAILABLE, str(exc))
    return {"id": row.id, "viewable": True, **result}


def write(db_path: Path, row: OpenFile, content: str, *, expected_sha256: Optional[str], overwrite: bool,
          acknowledge_executable: bool, acknowledge_sensitive: bool) -> Dict[str, Any]:
    if row.kind != "file":
        raise RowNotEditable("a diff is read only")
    if not overwrite and expected_sha256 is None:
        raise RowNotEditable("a save must name the revision it was based on")
    project_path = project_path_for(db_path, row.session_uuid, row.root)
    result = config_files.write_file(
        root_id=row.root, rel_path=row.path, content=content, project_path=project_path,
        acknowledge_executable=acknowledge_executable, acknowledge_sensitive=acknowledge_sensitive,
        expected_sha256=None if overwrite else expected_sha256,
    )
    logger.info("open_files_saved", file_id=row.id, overwrite=overwrite)
    return {"id": row.id, **result}
