
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core.companies import store
from src.core.new_project import landing_check, org_tree

router = APIRouter(tags=["projects"])


class LandingCheckRequest(BaseModel):
    """Body of the check: ``{"path": "~/…/Org/Acme/Globex/invoice-sync", "company_id": 13}``."""
    path: str = Field(..., description="The full folder the project would be created in (the chosen folder plus the name's slug)")
    company_id: Optional[int] = Field(None, ge=1, description="The company the form has chosen; null when none")


def _read_world() -> Dict[str, Any]:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        companies = store.list_companies(conn)
        projects = [{"name": r["display_name"], "root": r["root"]}
                    for r in conn.execute("SELECT display_name, root FROM projects WHERE COALESCE(host_key, 'local') = 'local'")]
    return {"companies": companies, "projects": projects}


@router.get("/projects/folder-tree", dependencies=[Depends(require_auth)])
async def get_folder_tree(depth: int = Query(org_tree.DEFAULT_DEPTH, ge=1, le=org_tree.MAX_DEPTH)) -> Dict[str, Any]:
    """The folders under the Org root, tagged with the project and the company that own each one.

    Inputs: depth (1 to 8 levels below the root). Output: ``{"root", "nodes", "truncated"}``. Raises: 503.
    """
    def build() -> Dict[str, Any]:
        world = _read_world()
        return org_tree.build_tree(org_tree.org_root(settings), [p["root"] for p in world["projects"]],
                                   world["companies"], depth=depth)

    return await asyncio.to_thread(build)


@router.post("/projects/landing-check", dependencies=[Depends(require_auth)])
async def post_landing_check(body: LandingCheckRequest) -> Dict[str, Any]:
    """Check the folder a new project would be created in; creates nothing. Output: ``{"ok", "path", "findings"}``. Raises: 503."""
    def check() -> Dict[str, Any]:
        world = _read_world()
        verdict = landing_check.check_landing(
            body.path, org_root=org_tree.org_root(settings), projects=world["projects"],
            companies=world["companies"], company_id=body.company_id)
        return verdict.as_dict()

    return await asyncio.to_thread(check)
