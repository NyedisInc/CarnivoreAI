"""
STATUS CODES. 400 ``open_file_path_refused`` (traversal, absolute, an unavailable root, a diff naming ``user``),
``open_file_is_diff`` (a diff row has no content route), ``open_file_refused`` (any other refusal of the editor's
guards on a save: read-only root, unacknowledged executable or sensitive write, malformed JSON). 404
``open_file_session_not_found``, ``open_file_not_found`` (no such row, or no regular file at the path). 409
``file_changed_on_disk`` (``{sha256}`` is the file's revision now, null when it is gone; nothing was written),
``app_config_protected`` (this server's own config.json), ``open_file_unavailable`` (the row's session is gone). 503 the
datastore. 422 a malformed body.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.config import settings
from src.core import app_config_guard, config_files, row_looks
from src.core.db import DatastoreUnreadableError, db_path_for
from src.core.open_files import content, open_list
from src.core.open_files.session_folder import SessionNotFound
from src.models.open_files import (
    OpenFileContent,
    OpenFileInfo,
    OpenFileList,
    OpenFileRequest,
    OpenFileResponse,
    SaveOpenFileRequest,
    SaveOpenFileResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["open-files"], dependencies=[Depends(require_auth)])


def _db_path() -> Path:
    return db_path_for(settings.get_state_dir())


def _refused(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _info(row: open_list.OpenFile) -> OpenFileInfo:
    return OpenFileInfo(id=row.id, kind=row.kind, root=row.root, path=row.path, session_uuid=row.session_uuid,
                        title=row.title, opened_at=row.opened_at, seq=row.seq)


def _row(file_id: str) -> open_list.OpenFile:
    row = open_list.get(file_id)
    if row is None:
        raise _refused(404, "open_file_not_found", "no such open file")
    return row


@router.get("/files/open", response_model=OpenFileList)
async def list_open_files(session_uuid: Optional[str] = Query(None, max_length=64)) -> OpenFileList:
    """Every open file row, oldest first, optionally one session's. Inputs: session_uuid. Output: OpenFileList."""
    return OpenFileList(files=[_info(row) for row in open_list.listing(session_uuid)])


@router.post("/files/open", response_model=OpenFileResponse)
async def open_file(body: OpenFileRequest) -> OpenFileResponse:
    """Open a file (or its diff) as a row from one session, reusing that file's row. Output: OpenFileResponse.

    Errors: 400 open_file_path_refused; 404 open_file_session_not_found, open_file_not_found; 503 datastore.
    """
    try:
        path = await run_in_threadpool(content.checked_path, _db_path(), body.kind, body.root, body.path, body.session_uuid)
    except SessionNotFound as exc:
        raise _refused(404, "open_file_session_not_found", "no session on this computer has that id") from exc
    except content.NothingToOpen as exc:
        raise _refused(404, "open_file_not_found", str(exc)) from exc
    except content.OpenRefused as exc:
        logger.info("open_file_refused", root=body.root, kind=body.kind, error=str(exc))
        raise _refused(400, "open_file_path_refused", str(exc)) from exc
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    row, reused = open_list.open_file(body.kind, body.root, path, body.session_uuid)
    row_looks.apply_on_open(row.id, body.color, body.icon)
    logger.info("open_file_row_opened", file_id=row.id, kind=row.kind, root=row.root, reused=reused)
    return OpenFileResponse(file=_info(row), reused=reused)


@router.delete("/files/open/{file_id}", status_code=204)
async def close_open_file(file_id: str) -> Response:
    """Close one file row (its screen goes with it on every window). Errors: 404 open_file_not_found."""
    if not open_list.close(file_id):
        raise _refused(404, "open_file_not_found", "no such open file")
    logger.info("open_file_row_closed", file_id=file_id)
    return Response(status_code=204)


@router.get("/files/open/{file_id}/content", response_model=OpenFileContent, response_model_exclude_none=True)
async def read_open_file(file_id: str) -> OpenFileContent:
    """The file behind a row with its revision, or why it cannot be shown. Errors: 400 open_file_is_diff; 404; 503."""
    row = _row(file_id)
    if row.kind != "file":
        raise _refused(400, "open_file_is_diff", "a diff reads through the session's git-diff route")
    try:
        result = await run_in_threadpool(content.read, _db_path(), row)
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return OpenFileContent(**result)


@router.put("/files/open/{file_id}/content", response_model=SaveOpenFileResponse)
async def save_open_file(file_id: str, body: SaveOpenFileRequest) -> SaveOpenFileResponse:
    """Save a row's file, refusing a stale save (409 file_changed_on_disk) unless ``overwrite``. Errors: see module."""
    row = _row(file_id)
    try:
        result = await run_in_threadpool(
            lambda: content.write(_db_path(), row, body.content, expected_sha256=body.expected_sha256,
                                  overwrite=body.overwrite, acknowledge_executable=body.acknowledge_executable,
                                  acknowledge_sensitive=body.acknowledge_sensitive))
    except content.RowNotEditable as exc:
        raise _refused(400, "open_file_is_diff", str(exc)) from exc
    except SessionNotFound as exc:
        raise _refused(409, "open_file_unavailable", "the session this file was opened from is gone") from exc
    except config_files.FileChangedOnDiskError as exc:
        logger.info("open_file_save_stale", file_id=row.id)
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except app_config_guard.AppConfigProtectedError as exc:
        raise HTTPException(status_code=409, detail={"code": app_config_guard.APP_CONFIG_PROTECTED, "detail": str(exc)}) from exc
    except config_files.ConfigFileError as exc:
        logger.info("open_file_save_refused", file_id=row.id, error=str(exc))
        raise _refused(400, "open_file_refused", str(exc)) from exc
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SaveOpenFileResponse(**result)
