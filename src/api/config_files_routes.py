from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
import structlog

from src.api.auth import require_auth
from src.core.work_admission import AdmissionRefused, WorkClass, admission
from src.core import (
    app_config_guard,
    config_files,
    config_files_create,
    config_files_find,
    config_files_ignore,
    config_files_tree_request,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/config-files", tags=["config-files"])


class ConfigFileWriteRequest(BaseModel):
    """Body for POST /config-files/write.

    Inputs (fields):
      root (str) - "user" or "workdir".
      path (str) - rel_path from a tree listing.
      content (str) - new file contents.
      project_path (str|None) - required when root != "user".
      acknowledge_executable (bool) - must be True to write a file
        config_files.py classifies as executable; the client sets this
        only after ``App.showConfirmModal()`` returned true.
      acknowledge_sensitive (bool) - must be True to write a file
        config_files.py classifies as sensitive (credentials/secret/key-
        shaped); the client sets this only after
        ``App.showConfirmModal()`` returned true.
    """
    root: str
    path: str
    content: str
    project_path: Optional[str] = None
    acknowledge_executable: bool = False
    acknowledge_sensitive: bool = False
    expected_sha256: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")


class ConfigFileCreateRequest(BaseModel):
    """Body for POST /config-files/create.
    """
    root: str
    path: str
    content: str = ""
    project_path: Optional[str] = None
    acknowledge_executable: bool = False
    acknowledge_sensitive: bool = False


class ConfigFileCreateResponse(BaseModel):
    ok: bool = True
    created: bool
    rel_path: str
    is_executable: bool
    is_sensitive: bool


class ConfigFileTreeResponse(BaseModel):
    root: str
    tree: list
    ignore_status: Optional[str] = None


def _list_tree(root: str, rel_path: str, project_path: Optional[str], levels: int, ignored: bool):
    tree = config_files.list_subtree(root, rel_path, project_path, levels)
    if not ignored:
        return tree, None
    root_dir = config_files.resolve_roots(project_path)[root]
    return tree, config_files_ignore.mark_ignored(root_dir, tree)


class ConfigFileReadResponse(BaseModel):
    content: str
    is_executable: bool
    is_sensitive: bool
    read_only: bool
    size: int
    sha256: str
    mtime_ns: int


class ConfigFileWriteResponse(BaseModel):
    ok: bool = True
    backed_up: bool
    is_executable: bool
    is_sensitive: bool
    sha256: Optional[str] = None
    mtime_ns: Optional[int] = None


@router.get("/tree", response_model=ConfigFileTreeResponse, dependencies=[Depends(require_auth)])
async def get_config_file_tree(
    root: str = Query(..., description='"user" or "workdir"'),
    project_path: Optional[str] = Query(None),
    path: Optional[str] = Query(
        None,
        description="directory to list, relative to the root; omit for the root itself",
    ),
    depth: Optional[int] = Query(
        None,
        description="levels of nodes to return; omit for the whole tree",
    ),
    ignored: Annotated[bool, Query(
        description="also mark each node's is_ignored from git check-ignore",
    )] = False,
):
    """
    Description: list the hide-list-filtered claude-config/project file
      tree for one root ("user" is also allow-listed;
      "workdir" is not). ``path`` and ``depth`` are both OPTIONAL and
      additive: send neither and this returns the whole tree exactly as
      it always has, which is what a client built before those
      parameters existed asks for and still gets.
    Inputs: root (str, query) - "user" or "workdir";
      project_path (str|None, query) - required for root != "user";
      path (str|None, query) - the directory to list, relative to the
        root, for expanding one node;
      depth (int|None, query) - how many levels of nodes to return;
      ignored (bool, query) - also ask git which entries it ignores
        (``config_files_ignore``); the answer's ``ignore_status`` says
        whether git could answer. Adds a flag to nodes the walk already
        produced and lists nothing new.
    Output: ConfigFileTreeResponse.
    Raises:
      HTTPException(400) - unknown/unavailable root, an out-of-range
        ``depth``, or a ``path`` that fails the containment/allow-list
        guard (translated from ValueError and
        config_files.ConfigFileError).
      HTTPException(503) - the requested directory exists but could not
        be read (translated from config_files.ConfigFileUnreadableError,
        which is checked FIRST since it subclasses ConfigFileError - a
        permissions problem is "could not evaluate", not "bad request",
        per this project's three-outcome rule; the client renders this
        as a distinct error row rather than folding it into "empty").
    """
    try:
        plan = config_files_tree_request.plan_tree_request(path, depth)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        tree, ignore_status = await admission.run(
            WorkClass.BULK_SCAN, _list_tree, root, plan.rel_path, project_path, plan.levels, ignored,
        )
    except AdmissionRefused as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except config_files.ConfigFileUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except config_files.ConfigFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ConfigFileTreeResponse(root=root, tree=tree, ignore_status=ignore_status)


class ConfigFileFindResponse(BaseModel):
    root: str
    tree: list
    truncated: bool
    ignore_status: Optional[str] = None


def _find(root: str, rel_path: str, project_path: Optional[str], q: str, ignored: bool):
    tree, truncated = config_files_find.find(root, rel_path, project_path, q)
    if not ignored:
        return tree, truncated, None
    root_dir = config_files.resolve_roots(project_path)[root]
    return tree, truncated, config_files_ignore.mark_ignored(root_dir, tree)


@router.get("/find", response_model=ConfigFileFindResponse, dependencies=[Depends(require_auth)])
async def find_config_files(
    root: str = Query(..., description='"user" or "workdir"'),
    q: str = Query(..., description="text a file or folder name must contain, any case"),
    project_path: Optional[str] = Query(None),
    path: Optional[str] = Query(None, description="directory to search, relative to the root"),
    ignored: Annotated[bool, Query(
        description="also mark each node's is_ignored from git check-ignore",
    )] = False,
):
    """
    Description: the file drawer's "find files": every entry under one root
      whose name contains ``q``, as a pruned tree (matches plus the folders
      leading to them). See ``config_files_find`` for the bounds and why this
      is not the tree walk.
    Inputs: root, q, project_path, path, ignored (query).
    Output: ConfigFileFindResponse.
    Raises: HTTPException(400) - unknown root, a refused or non-directory
      ``path``, or an empty/overlong ``q``.

    Off the event loop for the same reason as ``/tree``: the walk is
    thousands of directory reads.
    """
    try:
        tree, truncated, ignore_status = await admission.run(
            WorkClass.BULK_SCAN, _find, root, path or "", project_path, q, ignored,
        )
    except AdmissionRefused as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except config_files.ConfigFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ConfigFileFindResponse(root=root, tree=tree, truncated=truncated, ignore_status=ignore_status)


@router.get("/read", response_model=ConfigFileReadResponse, dependencies=[Depends(require_auth)])
async def read_config_file(
    root: str = Query(...),
    path: str = Query(...),
    project_path: Optional[str] = Query(None),
):
    """
    Description: read one browsable file's contents. Sensitive files
      (credentials/secret/key-shaped) are returned, not refused - the
      response's ``is_sensitive`` flag tells the client to mask the
      content until the user explicitly reveals it.
    Inputs: root (str, query); path (str, query) - rel_path from a tree
      listing; project_path (str|None, query).
    Output: ConfigFileReadResponse.
    Raises: HTTPException(400) - invalid path, hidden file, path
      traversal, oversized file, or binary/non-utf8 content (all
      translated from config_files.ConfigFileError - never a 500 for a
      client mistake).
    """
    try:
        result = config_files.read_file(root, path, project_path)
    except config_files.ConfigFileError as exc:
        logger.warning("config_files_read_rejected", root=root, path=path, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    return ConfigFileReadResponse(**result)


@router.post("/write", response_model=ConfigFileWriteResponse, dependencies=[Depends(require_auth)])
async def write_config_file(body: ConfigFileWriteRequest):
    """
    Description: write one browsable file. Always backs up the previous
      bytes first; validates JSON for .json files before writing;
      refuses executable files (hooks/, scripts/) without
      ``acknowledge_executable=True``; refuses sensitive files
      (credentials/secret/key-shaped) without
      ``acknowledge_sensitive=True``; refuses anything under a
      read-only root (plugins/) or outside the allowed roots entirely.
      Never logs ``body.content``.
    Inputs: body (ConfigFileWriteRequest).
    Output: ConfigFileWriteResponse.
    Raises:
      HTTPException(409) - the path IS this server's own config.json,
        answered with ``{"code": "app_config_protected"}``. A 409 and not
        a 403 because no credential makes this write allowed. The rule is
        a path comparison, so a PROJECT's own config.json is unaffected
        and still writable; see src/core/app_config_guard.py.
      HTTPException(409) - ``expected_sha256`` was given and the file on
        disk no longer hashes to it, answered with
        ``{"code": "file_changed_on_disk", "sha256": <current or null>}``;
        nothing is written.
      HTTPException(400) - any other rejection from
        config_files.write_file (bad path, malformed JSON, read-only,
        unacknowledged executable write, unacknowledged sensitive write) -
        translated from config_files.ConfigFileError.
    """
    logger.info(
        "config_files_write_request",
        root=body.root,
        path=body.path,
        acknowledge_executable=body.acknowledge_executable,
        acknowledge_sensitive=body.acknowledge_sensitive,
    )
    try:
        result = config_files.write_file(
            root_id=body.root,
            rel_path=body.path,
            content=body.content,
            project_path=body.project_path,
            acknowledge_executable=body.acknowledge_executable,
            acknowledge_sensitive=body.acknowledge_sensitive,
            expected_sha256=body.expected_sha256,
        )
    except config_files.FileChangedOnDiskError as exc:
        logger.info("config_files_write_stale", root=body.root, path=body.path)
        raise HTTPException(status_code=409, detail=exc.as_detail())
    except app_config_guard.AppConfigProtectedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": app_config_guard.APP_CONFIG_PROTECTED,
                "detail": str(exc),
            },
        )
    except config_files.ConfigFileError as exc:
        logger.warning("config_files_write_rejected", root=body.root, path=body.path, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    return ConfigFileWriteResponse(**result)


@router.post("/create", response_model=ConfigFileCreateResponse, dependencies=[Depends(require_auth)])
async def create_config_file(body: ConfigFileCreateRequest):
    """
    Description: create one NEW file under a browsable root. Refuses to
      overwrite anything that already exists at that path; requires the
      parent directory to exist (this endpoint never creates directories);
      validates JSON for a .json name; and applies the same executable /
      sensitive acknowledgement gates and the same read-only-root refusal
      as /write. Path safety is the SAME guard as every other endpoint
      here - config_files.resolve_safe_path, reached through
      config_files_create.create_file. Never logs ``body.content``.
    Inputs: body (ConfigFileCreateRequest).
    Output: ConfigFileCreateResponse.
    Raises: HTTPException(400) - any rejection from
      config_files_create.create_file (traversal, absolute path, existing
      name, missing parent, read-only root, malformed JSON, missing
      acknowledgement), translated from config_files.ConfigFileError.
    """
    logger.info(
        "config_files_create_request",
        root=body.root,
        path=body.path,
        acknowledge_executable=body.acknowledge_executable,
        acknowledge_sensitive=body.acknowledge_sensitive,
    )
    try:
        result = config_files_create.create_file(
            root_id=body.root,
            rel_path=body.path,
            content=body.content,
            project_path=body.project_path,
            acknowledge_executable=body.acknowledge_executable,
            acknowledge_sensitive=body.acknowledge_sensitive,
        )
    except config_files.ConfigFileError as exc:
        logger.warning("config_files_create_rejected", root=body.root, path=body.path, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    return ConfigFileCreateResponse(**result)
