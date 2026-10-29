
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.core.descriptions.limits import LONG_DESCRIPTION_MAX, SHORT_DESCRIPTION_MAX


class CreateProjectRequest(BaseModel):
    """Request model for creating a new project."""
    name: str = Field(..., description="Project display name")
    path: str = Field(..., description="Project directory path")
    description: Optional[str] = Field(None, max_length=LONG_DESCRIPTION_MAX,
                                       description="Project (long) description, at most 2000 characters")


class CheckProjectRootRequest(BaseModel):
    """Request model for asking whether a folder may be a project root."""
    path: str = Field(..., description="Folder the project would live in")


class ProjectResponse(BaseModel):
    """Response model for a project.

    ``id`` and ``root`` were added by feat/db-is-authoritative. ``id`` is
    the ``projects`` table row id, which the launcher uses to attach a
    project's child sessions - previously it had to look that id up in a
    SECOND request (GET /projects/presence) keyed by raw path, and two
    config entries sharing a path therefore resolved to the same id and
    drew the same children twice.

    Both are Optional because the degraded config.json fallback has
    neither: a config entry has no row and therefore no id. ``None`` there
    is the honest answer and is rendered as "this project has no children
    we can prove", never as row 0.
    """
    id: Optional[int] = Field(None, description="projects table row id, null in config fallback")
    name: str = Field(..., description="Project display name")
    path: str = Field(..., description="Project directory path")
    description: Optional[str] = Field(None, description="Project description (its LONG description)")
    short_description: Optional[str] = Field(None, description="The project's one-line description, null when none")
    root: Optional[str] = Field(None, description="Normalised project root, the identity key")
    default_launch_profile: Optional[str] = Field(
        None,
        description=(
            "The launch profile id the launch picker preselects for this project "
            "(``projects.default_agent_type``), or None when the project has none"
        ),
    )
    work_at: Optional[str] = Field(
        None,
        description=(
            "MAX(sessions.last_work_at) across this project's sessions - "
            "the key GET /projects is ordered by. None means NO WORK HAS "
            "BEEN RECORDED, which is a third outcome and not a zero: such "
            "a project sorts below every project that has a value and is "
            "labelled as unrecorded rather than blended in with them. "
            "Never derived from last_opened_at - opening is not working"
        ),
    )
    archived_at: Optional[str] = Field(
        None,
        description=(
            "ISO-8601 stamp of when this project was ARCHIVED (retired "
            "from the default list), or None when it is live. Carried on "
            "every row so a client rendering an include_archived=true "
            "list can tell the two apart per row - the flag it sent says "
            "what it asked for, not what any given row is. Archiving a "
            "project archives its non-live sessions too; a running one stays"
        ),
    )
    sessions_archived: Optional[int] = Field(None, description="Archive route only: sessions the archive stamped now")
    sessions_live: Optional[int] = Field(None, description="Archive route only: running sessions left alone")
    sessions_restored: Optional[int] = Field(None, description="Unarchive route only: sessions the restore brought back")

    company_id: Optional[int] = Field(
        None, description="The company this project is filed under (``projects.company_id``), null when orphaned"
    )
    company_name: Optional[str] = Field(
        None, description="That company's name, null when orphaned or in the config fallback"
    )
    color: Optional[str] = Field(
        None, description="The project's color, a #rrggbb hex (``projects.color``; see src/core/project_colors/palette.py), null when none is picked; legacy color names were converted to hex at schema v98"
    )
    parent_project_id: Optional[int] = Field(
        None,
        description=(
            "The live project on the same host whose folder is the nearest one holding this project's folder, null when "
            "none. Derived from the roots on every LIST read (src/core/project_lineage/parents.py), never stored; a "
            "single-project write response does not compute it and leaves it null"
        ),
    )
    storage: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "The pack state of the project's folder (``project_storage``; docs/project-pack.md): state, sizes, "
            "packed_at, last_error, progress and, for a packed project, the cheap archive ``integrity`` verdict "
            "(status ok / missing / modified ...). Null means the project was never packed (not measured), never zero. "
            "Set on LIST reads only"
        ),
    )
    uid: Optional[str] = Field(
        None, description="The project's cross-machine identity (``projects.uid``, uuid4 hex), shared by every machine holding it; null before v80")
    pack_state: Optional[str] = Field(
        None,
        description=(
            "``home`` (this machine holds the project, or it is not on the Pack), ``replica`` (an active copy; ``home_install_id`` "
            "is its home) or ``moved_away`` (the source of a one-way migrate: nothing can start here); null before v80"
        ),
    )
    home_install_id: Optional[str] = Field(None, description="A replica's home machine (install id); null on a home project")
    home_label: Optional[str] = Field(None, description="That machine's label, null when unset")
    moved_to_install_id: Optional[str] = Field(None, description="A moved-away project's new home (install id); null otherwise")
    moved_to_label: Optional[str] = Field(None, description="That machine's label, for the words ``moved to <machine>``; null otherwise")
    air_gap: Optional[bool] = Field(None, description="Never touch GitHub for this project; Carnivore carries everything (null before v80)")
    has_image: bool = Field(False, description="An uploaded hero image is stored for this project")
    image_rev: Optional[str] = Field(None, description="Changes on every re-upload; the client sends it as ?rev=")


class SetProjectCompanyRequest(BaseModel):
    """Request model for ``PUT /projects/{project_name}/company``: file a project under a company or orphan it."""
    company_id: Optional[int] = Field(None, description="The company id, or null to orphan the project")


MAX_COMPANY_BATCH = 50


class SetProjectsCompanyRequest(BaseModel):
    """Request model for ``PUT /projects/company``: file many projects under one company, or orphan them all."""
    project_ids: List[int] = Field(..., min_length=1, max_length=MAX_COMPANY_BATCH,
                                   description="Project row ids (archived ones included), 1 to 50, no duplicates")
    company_id: Optional[int] = Field(None, description="The company id, or null to orphan every listed project")


class ProjectCompanyResult(BaseModel):
    """One project's outcome in a batch filing: ``{"project_id": 4, "ok": true, "name": "trader", "error": null}``."""
    project_id: int
    ok: bool
    name: Optional[str] = Field(None, description="The project's display name once filed; null when it failed")
    error: Optional[str] = Field(None, description="Why this project was not filed; null when ok")


class SetProjectsCompanyResponse(BaseModel):
    """Per-project results of a batch filing, in request order, plus the counts."""
    company_id: Optional[int]
    filed: int
    failed: int
    results: List[ProjectCompanyResult]


class UpdateProjectRequest(BaseModel):
    """Request model for updating a project's display name, description, default launch profile and/or color.

    Both fields are optional - clients send only what they want to change.
    Display name only - the folder on disk is never touched.
    """
    new_name: Optional[str] = Field(None, description="New display name (omit to keep current)")
    description: Optional[str] = Field(
        None, max_length=LONG_DESCRIPTION_MAX,
        description="New (long) description, at most 2000 characters (omit to keep current; empty string clears)",
    )
    short_description: Optional[str] = Field(
        None, max_length=SHORT_DESCRIPTION_MAX,
        description="New one-line description, at most 120 characters (omit to keep current; empty string clears)",
    )
    default_launch_profile: Optional[str] = Field(
        None,
        description=(
            "Launch profile id the picker preselects for this project (omit to keep current; "
            "empty string clears). Must be a configured launch profile id."
        ),
    )
    color: Optional[str] = Field(
        None,
        description=(
            "The project's color as a #rrggbb hex, or a legacy theme key (orange, green, cyan, yellow, coral, "
            "violet, green-bright, yellow-bright). Omit to keep current; an empty string removes the color (a project has none until one is picked); any other value is a 422."
        ),
    )


class CloneProjectRequest(BaseModel):
    """Request model for cloning a GitHub repo into a new project.

    The server runs ``gh repo clone <repo_url> <parent_dir>/<repo_name>``,
    then registers the result as a project (display name = ``project_name``
    if supplied, else the repo basename). The parent directory is created
    if it doesn't exist; the target ``<parent_dir>/<repo_name>`` must NOT
    exist (server returns 409 otherwise).
    """
    repo_url: str = Field(
        ...,
        description=(
            "GitHub repo URL - accepts https://github.com/owner/repo, "
            "https://github.com/owner/repo.git, git@github.com:owner/repo.git, "
            "github.com/owner/repo, or owner/repo (gh CLI shorthand)."
        ),
    )
    parent_dir: Optional[str] = Field(
        default=None,
        description=(
            "Directory on the server in which the cloned folder will be created. "
            "Omitted: the configured projects folder (``default_working_dir``)."
        ),
    )
    description: Optional[str] = Field(None, description="Project description")
    project_name: Optional[str] = Field(
        None,
        description="Override auto-detected repo name as the project display name.",
    )


class ProjectMoveRequest(BaseModel):
    """Body of ``POST /projects/{project_name}/move`` (Joe (ccsliinc), 2026-10-07).

    ``move_folder`` false re-points only: the folder is already at ``new_root``
    (moved on another Mac and delivered by iCloud). True renames the folder
    here first. ``apply`` false answers the plan and changes nothing.
    """
    new_root: str = Field(..., description="The project's new folder (canonicalised like a new project's)")
    move_folder: bool = Field(False, description="Rename the folder on this Mac before re-pointing")
    apply: bool = Field(False, description="Run the plan; false answers the plan only")
    create_parents: bool = Field(
        False, description="With move_folder, create the new folder's missing parents (listed in the plan)")
    plan_fingerprint: Optional[str] = Field(
        None, description="Required with apply: the fingerprint of the plan that was read")


class ProjectMoveResponse(BaseModel):
    """The plan for a project move, and what was done when it was applied.

    ``checks`` holds every preflight check (``id``, ``ok``, ``message``); ``ok``
    is true only when all pass, and every check runs even after one fails.
    ``new_root`` is the stored long spelling of ``new_root_typed``.
    ``fingerprint`` is what an apply must quote as ``plan_fingerprint``. ``done`` is null for a plan and carries the
    applied counts after a run.
    """
    project_id: int
    project_name: str
    old_root: str
    new_root: Optional[str] = None
    new_root_typed: str = ""
    move_folder: bool
    create_parents: bool = False
    folders_to_create: List[str] = Field(default_factory=list)
    applied: bool = False
    ok: bool
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    child_projects: List[Dict[str, Any]] = Field(default_factory=list)
    sessions: List[Dict[str, Any]] = Field(default_factory=list)
    conversation_index_rows: int = 0
    skill_installs: Dict[str, int] = Field(default_factory=dict)
    transcript_moves: List[Dict[str, Any]] = Field(default_factory=list)
    informational: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    done: Optional[Dict[str, Any]] = None


class SetAirGapRequest(BaseModel):
    """Body of ``PUT /projects/{project_name}/air-gap``."""
    air_gap: bool = Field(..., description="True: never contact GitHub for this project (the carried rung and tar only)")


class AddReplicaRequest(BaseModel):
    """Body of ``POST /projects/{project_name}/replicas``: make an ACTIVE copy of the project on another paired machine."""
    machine: str = Field(..., min_length=1, max_length=200, description="The paired machine: its label, host key or install id")
    root: Optional[str] = Field(None, max_length=4096, description="The folder on that machine; omitted: under its projects folder")
    transport: str = Field("git", pattern="^(git|carried)$", description="How code reaches it: git (the remote) or carried (over the link)")
