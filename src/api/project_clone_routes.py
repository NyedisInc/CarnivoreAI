
import asyncio
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path
from src.api import projects_service
from src.config import settings
from src.models import CloneProjectRequest, ProjectResponse
from typing import Optional

from src.api.auth import require_auth

logger = structlog.get_logger()
router = APIRouter()


def _extract_repo_name(url: str) -> Optional[str]:
    if not url:
        return None
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "@" in url and ":" in url and "://" not in url:
        url = url.split(":", 1)[1]
    if "://" in url:
        url = url.split("://", 1)[1]
    if url.lower().startswith("github.com/"):
        url = url[len("github.com/"):]
    parts = [p for p in url.split("/") if p]
    if len(parts) < 2:
        return None
    name = parts[-1]
    if not name or any(ch in name for ch in ("..", "/", "\\", "\x00")) or name.strip() != name:
        return None
    return name


@router.post(
    "/projects/clone",
    response_model=ProjectResponse,
    status_code=201,
    dependencies=[Depends(require_auth)],
)
async def clone_project_from_github(body: CloneProjectRequest):
    """Clone a GitHub repo via ``gh repo clone`` and register it as a project.

    Steps:
      1. Verify the ``gh`` CLI is on PATH (else 503).
      2. Parse the repo basename from ``body.repo_url`` (else 400).
      3. Resolve target = ``<parent_dir>/<repo_name>``; refuse if it exists (409).
      4. Refuse if a project with the same display name already exists (409).
      5. Run ``gh repo clone <url> <target>`` with a 5-minute bounded timeout.
         No shell - args are passed as a vector to ``create_subprocess_exec``.
      6. Translate gh's exit/stderr into typed HTTP errors:
            auth/network → 401, not-found → 404, other → 500.
      7. Persist the new project (display name = body.project_name or repo basename).
    """
    try:
        gh_check = await asyncio.create_subprocess_exec(
            "gh", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await gh_check.communicate()
        if gh_check.returncode != 0:
            raise HTTPException(
                status_code=503,
                detail=(
                    "gh CLI not available on server. Install with "
                    "`brew install gh` and run `gh auth login`."
                ),
            )
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                "gh CLI not found on server. Install with `brew install gh` "
                "and run `gh auth login`."
            ),
        )

    repo_name = _extract_repo_name(body.repo_url)
    if not repo_name:
        raise HTTPException(
            status_code=400,
            detail=f"Could not extract repository name from URL: {body.repo_url}",
        )
    project_name = body.project_name or repo_name

    try:
        parent = Path(body.parent_dir).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parent_dir: {body.parent_dir} ({e})",
        )
    target = parent / repo_name

    # already exists
    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Target directory already exists: {target}",
        )

    # already exists
    _clone_view = projects_service.guard_writable(settings)
    if any(p["name"] == project_name for p in _clone_view.projects):
        raise HTTPException(
            status_code=409,
            detail=f"A project named '{project_name}' already exists",
        )

    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create parent directory {parent}: {e}",
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "repo", "clone", body.repo_url, str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="gh CLI not found")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        logger.warning("gh_clone_timeout", repo_url=body.repo_url)
        raise HTTPException(status_code=504, detail="git clone timed out after 5 minutes")

    if proc.returncode != 0:
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        lower = err.lower()
        logger.warning(
            "gh_clone_failed",
            repo_url=body.repo_url,
            returncode=proc.returncode,
            stderr=err[:500],
        )
        if (
            "authentication" in lower
            or "permission denied" in lower
            or "could not resolve host" in lower
            or "denied" in lower
            or "ssh: " in lower
        ):
            raise HTTPException(
                status_code=401,
                detail=f"gh clone failed (auth/network): {err[:500]}",
            )
        if "not found" in lower or "could not find" in lower or "repository not found" in lower:
            raise HTTPException(
                status_code=404,
                detail=f"Repository not found: {body.repo_url}",
            )
        raise HTTPException(
            status_code=500,
            detail=f"gh clone failed: {err[:500]}",
        )

    from contextlib import closing as _closing

    from src.core.project_writes import (
        ProjectNameConflict as _NameConflict,
        ProjectRootConflict as _RootConflict,
        ProjectRootRefused as _RootRefused,
        create_project as _db_create_project,
    )

    try:
        with _closing(projects_service.open_db_or_503(settings)) as _conn:
            row = _db_create_project(
                _conn,
                name=project_name,
                path=str(target),
                description=body.description,
            )
    except (_NameConflict, _RootConflict, _RootRefused) as e:
        logger.warning(
            "project_save_collision_after_clone", name=project_name, error=str(e)
        )
        raise HTTPException(status_code=409, detail=str(e))


    logger.info(
        "project_cloned_from_github",
        name=row["display_name"],
        path=row["raw_path"],
        repo_url=body.repo_url,
    )

    return ProjectResponse(
        id=row["id"],
        name=row["display_name"],
        path=row["raw_path"],
        description=row["description"],
        root=row["root"],
    )
