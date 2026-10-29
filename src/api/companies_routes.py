
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core.companies import accounts, hero_art_gen, hero_images, lineage, store
from src.core.project_colors.color_math import oklch_hue_of
from src.core.project_colors.palette import is_hex_color
from src.models.projects import (
    ProjectCompanyResult,
    ProjectResponse,
    SetProjectCompanyRequest,
    SetProjectsCompanyRequest,
    SetProjectsCompanyResponse,
)

logger = structlog.get_logger()
router = APIRouter(tags=["companies"])


class CompanyResponse(BaseModel):
    """One company: ``{"id": 1, "name": "Acme", "project_count": 3, "has_image": false, "image_rev": null}``."""
    id: int
    name: str
    project_count: int = Field(0, description="Projects filed under this company, archived ones included")
    has_image: bool = Field(False, description="An uploaded hero image is stored for this company")
    image_rev: Optional[str] = Field(None, description="Changes on every re-upload; the client sends it as ?rev=")
    hue: Optional[int] = Field(None, description="The chosen base hue of the company's color family, 0-359; null is the default")
    parent_id: Optional[int] = Field(None, description="The company this one sits under; null is a top-level company")
    hq_project_id: Optional[int] = Field(None, description="The company agent's HQ project id; null when none is set")


class CompanyNameRequest(BaseModel):
    """Body of POST: the company's name (trimmed by the server, 1 to 80 characters) and, optionally, its parent company."""
    name: str
    parent_id: Optional[int] = Field(None, ge=1, description="Create it under this company; omit or null for the top level")


class CompanyPatchRequest(BaseModel):
    """Body of PATCH, any subset: ``{"name": "Acme"}``, ``{"hue": 145}``, ``{"hue": null}`` (back to the default),
    ``{"parent_id": 2}`` / ``{"parent_id": null}`` (top level), ``{"hq_project_id": 9}`` / ``{"hq_project_id": null}``."""
    model_config = {"extra": "forbid"}
    name: Optional[str] = None
    hue: Optional[int] = Field(None, ge=0, le=359)
    color: Optional[str] = Field(None, description="A #rrggbb pick from the shared color picker; stored as its OKLCH hue (not with hue)")
    parent_id: Optional[int] = Field(None, ge=1)
    hq_project_id: Optional[int] = Field(None, ge=1)


class CompaniesResponse(BaseModel):
    """``{"companies": [{"id", "name", "project_count"}]}``, A-Z case-insensitive."""
    companies: List[CompanyResponse]


class DeleteCompanyResponse(BaseModel):
    """``{"deleted": true, "orphaned": 2, "children_moved": 1}``: projects left with no company, child companies moved up."""
    deleted: bool = True
    orphaned: int
    children_moved: int = 0


class AccountsBody(BaseModel):
    """The pointers: ``{"github": "acme", "aws": "123456789012", "gcp": "acme-prod"}``; an empty or missing field is no pointer."""
    model_config = {"extra": "forbid"}
    github: Optional[str] = None
    github_login: Optional[str] = None
    aws: Optional[str] = None
    gcp: Optional[str] = None


def _not_found(exc: Exception) -> HTTPException:
    what = "Company" if isinstance(exc, store.CompanyNotFound) else "Project"
    return HTTPException(status_code=404, detail=f"{what} '{exc}' not found")


def _with_image(company: dict) -> dict:
    company.update(hero_images.fields(hero_images.COMPANY, company["id"]))
    return company


def _attach_art(companies: list) -> None:
    hero_images.attach(hero_images.COMPANY, companies)
    hero_art_gen.schedule_missing(hero_images.COMPANY, companies)


@router.get("/companies", response_model=CompaniesResponse, dependencies=[Depends(require_auth)])
async def list_companies() -> dict:
    """Every company A-Z with its project count; an empty list before any exists or when the datastore is down."""
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    db_file = db_path_for(settings.get_state_dir())
    try:
        with closing(connect(db_file, create=False)) as conn:
            companies = store.list_companies(conn)
        await asyncio.to_thread(_attach_art, companies)
        return {"companies": companies}
    except DatastoreUnreadableError as exc:
        logger.warning("companies_list_datastore_unreadable", error=str(exc))
        return {"companies": []}


@router.post("/companies", response_model=CompanyResponse, status_code=201, dependencies=[Depends(require_auth)])
async def create_company(body: CompanyNameRequest) -> dict:
    """Create a company, top level or under ``parent_id``.

    Raises: 422 empty or over 80 characters or deeper than four levels, 404 unknown parent, 409 a company already has that
    name, 503.
    """
    projects_service.guard_writable(settings)
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            return _with_image(store.create_company(conn, body.name, parent_id=body.parent_id))
    except store.CompanyNameInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.CompanyNameConflict as exc:
        raise HTTPException(status_code=409, detail=f"A company named '{exc}' already exists")
    except store.CompanyNotFound as exc:
        raise _not_found(exc)
    except lineage.CompanyLineageRefused as exc:
        raise _lineage_refused(exc)


def _lineage_refused(exc: lineage.CompanyLineageRefused) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, lineage.CompanyParentCycle) else 422, detail=str(exc))


@router.patch("/companies/{company_id}", response_model=CompanyResponse, dependencies=[Depends(require_auth)])
async def rename_company(company_id: int, body: CompanyPatchRequest) -> dict:
    """Rename a company, choose its color family's hue, move it under a parent and/or set its HQ project.

    Raises: 422 invalid or empty body or a tree deeper than four levels, 404 unknown company, parent or project, 409 duplicate
    name or a parent cycle, 503.
    """
    projects_service.guard_writable(settings)
    sent = body.model_fields_set
    if not sent or ("name" in sent and body.name is None):
        raise HTTPException(status_code=422, detail="send a name, a hue, a color, a parent_id or an hq_project_id")
    if "color" in sent:
        if "hue" in sent:
            raise HTTPException(status_code=422, detail="send a hue or a color, not both")
        if body.color is not None and not is_hex_color(body.color):
            raise HTTPException(status_code=422, detail="color must be a #rrggbb hex")
        body.hue = None if body.color is None else oklch_hue_of(body.color)
        sent = sent | {"hue"}
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            company = store.get_company(conn, company_id)
            if "name" in sent:
                company = store.rename_company(conn, company_id, body.name)
            if "hue" in sent:
                company = store.set_company_hue(conn, company_id, body.hue)
            if "parent_id" in sent:
                company = store.set_parent(conn, company_id, body.parent_id)
            if "hq_project_id" in sent:
                company = store.set_hq_project(conn, company_id, body.hq_project_id)
            return _with_image(company)
    except store.CompanyNameInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (store.CompanyNotFound, store.ProjectNotFound) as exc:
        raise _not_found(exc)
    except store.CompanyNameConflict as exc:
        raise HTTPException(status_code=409, detail=f"A company named '{exc}' already exists")
    except lineage.CompanyLineageRefused as exc:
        raise _lineage_refused(exc)


@router.delete("/companies/{company_id}", response_model=DeleteCompanyResponse, dependencies=[Depends(require_auth)])
async def delete_company(company_id: int) -> DeleteCompanyResponse:
    """Delete a company; its projects become orphaned and its child companies move up to its parent. Raises: 404, 503."""
    projects_service.guard_writable(settings)
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            counts = store.delete_company(conn, company_id)
        hero_images.remove(hero_images.COMPANY, company_id)
        return DeleteCompanyResponse(**counts)
    except store.CompanyNotFound as exc:
        raise _not_found(exc)


@router.get("/companies/{company_id}/accounts", response_model=AccountsBody, dependencies=[Depends(require_auth)])
async def get_company_accounts(company_id: int) -> dict:
    """The company's account pointers (an empty object when none are set). Raises: 404 unknown company, 503."""
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            return accounts.get_accounts(conn, company_id)
    except store.CompanyNotFound as exc:
        raise _not_found(exc)


@router.put("/companies/{company_id}/accounts", response_model=AccountsBody, dependencies=[Depends(require_auth)])
async def put_company_accounts(company_id: int, body: AccountsBody) -> dict:
    """Replace the company's account pointers; a field left out is cleared. Pointers only: a value that looks like a secret is refused.

    Raises: 422 a secret-shaped, multi-line or over-long value (names the field, never the value), 404 unknown company, 503.
    """
    projects_service.guard_writable(settings)
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            return accounts.set_accounts(conn, company_id, body.model_dump())
    except accounts.AccountsInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.CompanyNotFound as exc:
        raise _not_found(exc)


@router.put("/projects/company", response_model=SetProjectsCompanyResponse, dependencies=[Depends(require_auth)])
async def set_projects_company(body: SetProjectsCompanyRequest) -> SetProjectsCompanyResponse:
    """File many projects (archived ones included) under one company, or orphan them all, reporting each one.

    Inputs: body - ``project_ids`` (1 to 50 distinct row ids), ``company_id`` (int, or null to orphan).
    Output: per-project results in request order; a project that no longer exists fails alone (``ok`` false, ``error``).
    Raises: 404 unknown company (nothing changed), 422 duplicate ids, 503.
    """
    if len(set(body.project_ids)) != len(body.project_ids):
        raise HTTPException(status_code=422, detail="project_ids must not repeat a project")
    projects_service.guard_writable(settings)
    results: List[ProjectCompanyResult] = []
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            for project_id in body.project_ids:
                try:
                    store.assign_project(conn, project_id, body.company_id)
                except store.ProjectNotFound:
                    results.append(ProjectCompanyResult(project_id=project_id, ok=False, error="no project with this id"))
                    continue
                name = conn.execute("SELECT display_name FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
                results.append(ProjectCompanyResult(project_id=project_id, ok=True, name=name))
    except store.CompanyNotFound as exc:
        raise _not_found(exc)
    filed = sum(1 for r in results if r.ok)
    return SetProjectsCompanyResponse(company_id=body.company_id, filed=filed, failed=len(results) - filed, results=results)


@router.put(
    "/projects/{project_name}/company", response_model=ProjectResponse, dependencies=[Depends(require_auth)]
)
async def set_project_company(project_name: str, body: SetProjectCompanyRequest) -> ProjectResponse:
    """File a project under a company, or orphan it with ``company_id: null``.

    Returns the updated project (with ``company_id`` and ``company_name``).
    Raises: 404 unknown project or company, 409 ambiguous project name, 503.
    """
    from src.core.project_writes import list_projects_ordered

    projects_service.guard_writable(settings)
    try:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            target = projects_service.resolve_target(conn, project_name)
            store.assign_project(conn, target["id"], body.company_id)
            row = next(r for r in list_projects_ordered(conn, include_archived=True) if r["id"] == target["id"])
    except (store.CompanyNotFound, store.ProjectNotFound) as exc:
        raise _not_found(exc)
    return ProjectResponse(
        id=row["id"],
        name=row["display_name"],
        path=row["raw_path"],
        description=row["description"],
        root=row["root"],
        default_launch_profile=row["default_agent_type"],
        work_at=row.get("work_at"),
        archived_at=row.get("archived_at"),
        company_id=row["company_id"],
        company_name=row["company_name"],
        color=row.get("color"),
        **hero_images.fields(hero_images.PROJECT, row["id"]),
    )
