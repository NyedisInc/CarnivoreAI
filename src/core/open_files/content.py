
from __future__ import annotations

from pathlib import Path
from contextlib import closing
from typing import Any, Dict, Optional

import structlog

from src.core import config_files, project_authority
from src.core.db import connect, DatastoreUnreadableError
from src.core.hosts.ddl import host_scope
from src.core.hosts.identity import is_remote_root
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
    if root == "absolute":
        return None
    folder = working_dir_for(db_path, session_uuid)
    return folder if root == "workdir" else None


class OpenRefused(ValueError):
    pass


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


def _scope_root_for(db_path: Path, path: Path) -> Optional[str]:
    view = project_authority.resolve_projects(db_path.parent, include_archived=True)
    if view.degraded:
        raise DatastoreUnreadableError(view.detail or "projects could not be read", db_path)
    roots = [project["root"] for project in view.projects if isinstance(project.get("root"), str)
             and not is_remote_root(project["root"])]
    with closing(connect(db_path, create=False)) as conn:
        scope_sql, scope_params = host_scope(conn)
        roots += [row["working_dir"] for row in conn.execute(
            "SELECT working_dir FROM sessions WHERE working_dir IS NOT NULL" + scope_sql, scope_params)]
    candidates: list[Path] = []
    for raw_root in roots:
        root = Path(raw_root)
        if not root.is_absolute():
            continue
        try:
            root = root.resolve()
        except (OSError, RuntimeError):
            continue
        if path.is_relative_to(root):
            candidates.append(root)
    if not candidates:
        return None
    readonly = [root for root in candidates if config_files.classify(root, path)[2]]
    return str(max(readonly or candidates, key=lambda root: len(root.parts)))


def checked_absolute_path(db_path: Path, raw: str) -> tuple[str, Optional[str]]:
    path_text = raw.strip()
    if len(path_text) >= 2 and path_text[0] == path_text[-1] and path_text[0] in ("'", '"'):
        path_text = path_text[1:-1]
    path_text = path_text.strip()
    if not path_text or "\0" in path_text or not (path_text.startswith("/") or path_text.startswith("~/")):
        raise OpenRefused("enter an absolute or ~/ file path")
    try:
        lexical = Path(path_text).expanduser()
        user_root = config_files.CLAUDE_HOME.resolve()
        if lexical.is_relative_to(user_root):
            config_files.resolve_safe_path("user", lexical.relative_to(user_root).as_posix(), None)
        path = Path(path_text).expanduser().resolve(strict=True)
        config_files._pinned_file(str(path))
        if not path.is_file():
            raise NothingToOpen("path is not a regular file")
        with path.open("rb") as handle:
            handle.read(1)
    except (OSError, RuntimeError) as exc:
        raise OpenRefused(f"could not open the file: {exc.strerror or exc}" if isinstance(exc, OSError) else str(exc)) from exc
    except config_files.ConfigFileError as exc:
        raise OpenRefused(str(exc)) from exc
    return str(path), _scope_root_for(db_path, path)


def _unviewable(row: OpenFile, reason: str, detail: str) -> Dict[str, Any]:
    return {"id": row.id, "viewable": False, "reason": reason, "detail": detail}


def read(db_path: Path, row: OpenFile) -> Dict[str, Any]:
    try:
        project_path = project_path_for(db_path, row.session_uuid, row.root)
    except SessionNotFound:
        return _unviewable(row, UNAVAILABLE, "the session this file was opened from is gone")
    try:
        result = config_files.read_file(row.root, row.path, project_path, _pinned_absolute=row.root == "absolute",
                                        _trusted_root=row.scope_root)
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
        expected_sha256=None if overwrite else expected_sha256, _pinned_absolute=row.root == "absolute",
        _trusted_root=row.scope_root,
    )
    logger.info("open_files_saved", file_id=row.id, overwrite=overwrite)
    return {"id": row.id, **result}
