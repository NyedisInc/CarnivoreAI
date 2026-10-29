
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProjectPackRequest(BaseModel):
    """Plan (``apply`` false, the default) or run a pack. Apply must quote the plan's ``plan_fingerprint``."""

    apply: bool = Field(False, description="Run the pack; false answers the plan only and changes nothing")
    plan_fingerprint: Optional[str] = Field(None, description="Required with apply: the fingerprint of the plan read")
    accept_local_only: bool = Field(
        False, description="Allow a git repo with no remote (or a branch no remote has): the archive will be the only copy")


class ProjectUnpackRequest(BaseModel):
    """Plan (``apply`` false, the default) or run an unpack. Apply must quote the plan's ``plan_fingerprint``."""

    apply: bool = Field(False, description="Run the unpack; false answers the plan only and changes nothing")
    plan_fingerprint: Optional[str] = Field(None, description="Required with apply: the fingerprint of the plan read")


class ProjectPackResponse(BaseModel):
    """A pack or unpack plan, and the job when it was started.

    ``checks`` holds every preflight check (``id``, ``ok``, ``message``); ``ok`` is true only when all pass.
    ``warnings`` carries the modified-archive warning on an unpack plan. ``fingerprint`` is what an apply must
    quote. ``job`` is set (HTTP 202) once an apply started; follow it through ``GET /projects/{name}/storage``.
    """

    kind: str
    project: Dict[str, Any]
    ok: bool
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    sizes: Dict[str, Any] = Field(default_factory=dict)
    largest_folders: List[Dict[str, Any]] = Field(default_factory=list)
    repos: List[Dict[str, Any]] = Field(default_factory=list)
    children: List[Dict[str, Any]] = Field(default_factory=list)
    local_only: List[str] = Field(default_factory=list)
    integrity: Optional[Dict[str, Any]] = None
    fingerprint: str = ""
    job: Optional[Dict[str, Any]] = None


class ProjectStorageResponse(BaseModel):
    """``GET /projects/{name}/storage``: the project's pack state, or ``storage`` null when it was never packed."""

    project_id: int
    project_name: str
    storage: Optional[Dict[str, Any]] = None


class ProjectVerifyResponse(BaseModel):
    """``POST /projects/{name}/storage/verify``: the full checksum verdict on the packed archive."""

    project_id: int
    project_name: str
    integrity: Optional[Dict[str, Any]] = None
    storage: Optional[Dict[str, Any]] = None
