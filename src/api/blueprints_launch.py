"""Previewing and launching a blueprint, one member at a time (issue #759).

A LAUNCH IS SEQUENTIAL, ON PURPOSE. Two creates racing each other claim
tmux names without a lock between them (``session_manager.create_session``
claims, then registers), so members are brought up one after another, each
with its own label. Per member, in order:

  1. family   the agent family resolves against the configured wrappers
              (an unknown wrapper id is refused, never silently claude).
  2. folder   the existing folder is resolved, or the git worktree is made
              (``src/core/project_worktree.py``: argv only, contained).
  3. project  the folder is registered as a launcher project if it is not
              one (the catalog's project-scope gate installs only into a
              known project), or reused when it is.
  4. skills   any missing harness skill root under the member's folder is
              created first (THIS LAUNCH ONLY, never the catalog's general
              install path - ``create_member_roots``, contained to the
              folder, symlinks refused); then each missing catalog skill
              goes through THE catalog install route itself
              (``catalog_install_routes.run_install``) at project scope:
              the same signature, digest and consent gates, the same
              consent body. There is no second install path, so there is
              no second place consent could be skipped.
  5. session  the create route itself (``session_crud_routes.create_session``)
              with the member's label and opening prompt.

A FAILED STEP ENDS THAT MEMBER, NEVER THE LAUNCH. Its outcome names the
step and the code; the members after it still launch. Nothing is rolled
back: a session that started stays started, which is the honest answer for
a pane that is already running an agent. ``members`` in the request
relaunches a subset, and a relaunch reuses the worktree and project the
first attempt made.

THE LAUNCHED MEMBERS BECOME A LAYOUT (two or more), named after the
blueprint and uniquified, through the Layouts store (slice A, #745).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException, Request

from src.api.catalog_consent import carries_scripts, preview_body
from src.api.catalog_install_support import fetch_and_stage
from src.api.catalog_routes import refuse_empty
from src.api.catalog_views import find_item, latest_version
from src.config import settings
from src.core.layouts import store as layouts_store
from src.core import project_worktree
from src.core import blueprints_shape
from src.core import resource_push
from src.core.resource_push import topics as resource_topics
from src.config.agent_command import profiles_for
from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.launch_profiles.resolve import LaunchProfileNotFound, LaunchRequest, pick_profile
from src.core.db import connect, db_path_for
from src.core.project_authority import MODE_DB, resolve_projects
from src.core.skill_manager.root_create import RootCreateRefused, ensure_skill_roots
from src.core.skills.digest import hash_file
from src.core.skills.installer import discard_staging
from src.core.skills.kinds import manifest_name
from src.core.skills.ledger_types import SCOPE_PROJECT
from src.models.blueprints import PROMPT_FAMILIES, BlueprintSession, BlueprintSpec
from src.models.blueprints_launch import (
    FolderView, LaunchedSession, MemberOutcome, MemberPreview, Problem, ProjectView,
    SkillView, WorktreeView,
)
from src.models.catalog import review_instructions_details, review_writes_instructions
from src.models.catalog_api import InstallConsent, InstallRequest

logger = structlog.get_logger()


class StepFailed(Exception):
    """One member step could not go ahead. Carries the Problem."""

    def __init__(self, step: str, code: str, detail: str) -> None:
        super().__init__(detail)
        self.problem = Problem(step=step, code=code, detail=detail)


def worktree_root() -> str:
    return project_worktree.read_root(settings.auth_config_file)




def resolve_family(member: BlueprintSession) -> str:
    try:
        auth = settings.load_auth_config()
        block = getattr(auth, "launch_profiles", None)
        profiles = profiles_for(tuple(block.profiles) if block is not None else None, auth.agents)
    except (OSError, ValueError) as exc:
        raise StepFailed("family", "config_unavailable",
                         f"the agent configuration could not be read: {exc}") from None
    try:
        bare = member.family.lower() in AGENT_FAMILY_BY_NAME
        harness = pick_profile(LaunchRequest(profiles=profiles, agent_type=member.family, explicit=not bare)).harness
    except LaunchProfileNotFound:
        raise StepFailed("family", "family_unknown",
                         f"{member.family!r} is not an agent family or a launch profile") from None
    if member.opening_prompt is not None and harness not in PROMPT_FAMILIES:
        raise StepFailed("family", "prompt_family",
                         f"an opening prompt is for claude and codex; {member.family!r} launches "
                         f"{harness}")
    return harness




def _inside(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def _existing_folder(raw: str) -> str:
    expanded = os.path.expanduser(raw)
    if not os.path.isabs(expanded):
        raise StepFailed("folder", "folder_invalid", "a folder path is absolute or starts with ~")
    real = os.path.realpath(expanded)
    if real in {os.path.realpath(d) for d in project_worktree.SYSTEM_DIRS}:
        raise StepFailed("folder", "folder_invalid", f"{real!r} is a system directory")
    state = os.path.realpath(settings.get_state_dir())
    if real == os.path.realpath(os.path.expanduser("~")) or _inside(state, real):
        raise StepFailed("folder", "folder_invalid",
                         f"{real!r} is the home directory or holds this app's state")
    if not os.path.isdir(real):
        raise StepFailed("folder", "folder_invalid", f"{real!r} is not a directory")
    return real


async def plan_folder(member: BlueprintSession, root: str) -> Tuple[FolderView, Optional[Any]]:
    folder = member.folder
    if folder.mode == "existing":
        return FolderView(mode="existing", path=_existing_folder(folder.path)), None
    try:
        plan = await project_worktree.plan_worktree(
            folder.repo_path, folder.base_branch, folder.branch, root=root)
    except project_worktree.WorktreeRefused as exc:
        raise StepFailed("folder", exc.code, exc.detail) from None
    except project_worktree.WorktreeTimeout as exc:
        raise StepFailed("folder", "worktree_timeout", str(exc)) from None
    except project_worktree.GitUnavailable as exc:
        raise StepFailed("folder", "git_unavailable", str(exc)) from None
    view = FolderView(mode="worktree", path=plan.path, worktree=WorktreeView(
        repo_path=plan.repo, base_branch=plan.base_branch, branch=plan.branch,
        path=plan.path, create=not plan.reuse, branch_exists=plan.branch_exists))
    return view, plan


async def make_folder(plan: Any, root: str) -> None:
    try:
        await project_worktree.create_worktree(plan, root=root)
    except project_worktree.WorktreeRefused as exc:
        raise StepFailed("folder", exc.code, exc.detail) from None
    except project_worktree.WorktreeTimeout as exc:
        raise StepFailed("folder", "worktree_timeout", str(exc)) from None
    except project_worktree.GitUnavailable as exc:
        raise StepFailed("folder", "git_unavailable", str(exc)) from None
    except OSError as exc:
        raise StepFailed("folder", "worktree_failed", f"the worktree folder: {exc.strerror}") from None




def find_project(folder: str) -> Optional[Dict[str, Any]]:
    """The launcher project at this folder (archived included), or None.

    Raises: StepFailed ``projects_unavailable`` - the list could not be read.
    """
    view = resolve_projects(settings.get_state_dir(), include_archived=True)
    if view.mode != MODE_DB:
        raise StepFailed("project", "projects_unavailable", "the project list could not be read")
    for row in view.projects:
        for spelling in (row.get("root"), row.get("path")):
            if spelling and os.path.realpath(os.path.expanduser(str(spelling))) == folder:
                return row
    return None


def ensure_project(folder: str, name_hint: Optional[str] = None) -> ProjectView:
    from src.core.project_writes import ProjectNameConflict, ProjectRootConflict, ProjectRootRefused, create_project

    found = find_project(folder)
    if found is not None:
        if found.get("archived_at"):
            raise StepFailed("project", "project_archived",
                             f"the project at {folder!r} is archived; unarchive it first")
        return ProjectView(known=True, name=found.get("name"))
    base = name_hint or os.path.basename(folder) or "project"
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        for n in range(1, 50):
            name = base if n == 1 else f"{base} {n}"
            try:
                row = create_project(conn, name=name, path=folder)
            except ProjectNameConflict:
                continue
            except (ProjectRootConflict, ProjectRootRefused) as exc:
                raise StepFailed("project", "project_register_failed", str(exc)) from None
            logger.info("blueprint_project_registered", name=row["display_name"])
            return ProjectView(known=True, name=row["display_name"])
    raise StepFailed("project", "project_register_failed", f"no free project name for {base!r}")




async def catalog_snapshot(request: Request) -> Optional[Any]:
    try:
        snapshot = await request.app.state.services.catalog.index_cache.get()
        refuse_empty(snapshot)
    except HTTPException:
        return None
    return snapshot


def installed_in(request: Request, item_id: str, folder: str) -> bool:
    with request.app.state.services.catalog.ledger() as ledger:
        return ledger.find(item_id, SCOPE_PROJECT, folder) is not None


def roots_missing(request: Request, folder: str) -> List[str]:
    targets = request.app.state.services.install_roots.targets_for("skill", SCOPE_PROJECT, folder)
    return [str(t.leaf_dir) for t in targets if not os.path.isdir(t.leaf_dir)]


def create_member_roots(request: Request, folder: str) -> List[str]:
    try:
        return ensure_skill_roots(request.app.state.services.install_roots, folder)
    except RootCreateRefused as exc:
        raise StepFailed("skills", exc.code, exc.detail) from None


async def consent_sheet(request: Request, item: Any, version: Any) -> Optional[Dict[str, Any]]:
    try:
        staging, staged = await fetch_and_stage(request, item, version, allow_scripts=True)
    except HTTPException:
        return None
    try:
        body_sha, _size = await asyncio.to_thread(hash_file, staged.path / manifest_name(item.kind))
        return preview_body(request, item=item, version=version, staged=staged,
                            plan_token=None, body_sha=body_sha).model_dump(mode="json")
    finally:
        await asyncio.to_thread(discard_staging, staging)


async def preview_skills(request: Request, snapshot: Optional[Any], folder: Optional[str],
                         skill_ids: List[str]) -> List[SkillView]:
    views: List[SkillView] = []
    for item_id in skill_ids:
        if snapshot is None:
            views.append(SkillView(item_id=item_id, state="catalog_unavailable"))
            continue
        item, untrusted = find_item(snapshot, item_id)
        version = latest_version(item) if item is not None else None
        if item is None or version is None:
            views.append(SkillView(item_id=item_id, state="unknown"))
            continue
        if untrusted:
            views.append(SkillView(item_id=item_id, state="untrusted", version=version.v))
            continue
        if folder is not None and await asyncio.to_thread(installed_in, request, item_id, folder):
            views.append(SkillView(item_id=item_id, state="installed", version=version.v))
            continue
        needs = carries_scripts(version)
        sheet = await consent_sheet(request, item, version) if needs else None
        details, more = review_instructions_details(version.review)
        views.append(SkillView(item_id=item_id, state="to_install", version=version.v,
                               needs_consent=needs, consent_sheet=sheet,
                               instructions_write=review_writes_instructions(version.review),
                               instructions_details=details, instructions_more=more))
    return views


async def install_skills(request: Request, folder: str, skill_ids: List[str],
                         consents: Dict[str, InstallConsent]) -> List[SkillView]:
    from src.api.catalog_install_routes import run_install

    views: List[SkillView] = []
    for item_id in skill_ids:
        if await asyncio.to_thread(installed_in, request, item_id, folder):
            views.append(SkillView(item_id=item_id, state="already_present"))
            continue
        body = InstallRequest(item_id=item_id, scope=SCOPE_PROJECT, project_path=folder,
                              consent=consents.get(item_id))
        try:
            row = await run_install(request, body, blueprint=True)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
            code = str(detail.get("code") or f"http_{exc.status_code}")
            views.append(SkillView(item_id=item_id, state="refused", code=code,
                                   needs_consent=code == "consent_required",
                                   detail=str(detail.get("detail") or code), refusal=detail))
            continue
        views.append(SkillView(item_id=item_id, state="installed", version=row.version))
    return views




def _row_identity(request: Request, session: Any) -> Tuple[Optional[int], Optional[str]]:
    from src.core.session_store import identity_for_instance, identity_for_live_name

    name = getattr(session, "tmux_session", None)
    if not name:
        return None, None
    socket = request.app.state.session_manager.tmux_socket_name()
    epoch = getattr(session, "tmux_created_epoch", None)
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        identity = identity_for_instance(conn, socket=socket, name=name, epoch=epoch)
        if identity is None:
            identity = identity_for_live_name(conn, socket=socket, name=name)
        if identity is None:
            return None, None
        found = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?",
                             (int(identity["id"]),)).fetchone()
    return int(identity["id"]), (str(found[0]) if found else None)


async def create_member_session(request: Request, member: BlueprintSession, folder: str,
                                cols: Optional[int], rows: Optional[int]) -> LaunchedSession:
    from src.api.session_crud_routes import create_session
    from src.core.session_label import sanitize_tmux_name
    from src.models import CreateSessionRequest

    body = CreateSessionRequest(
        working_dir=folder, project_name=sanitize_tmux_name(member.label), label=member.label,
        agent_type=member.family, model=member.model, opening_prompt=member.opening_prompt,
        cols=cols, rows=rows)
    try:
        session = await create_session(request, body)
    except HTTPException as exc:
        raise StepFailed("session", f"create_{exc.status_code}", str(exc.detail)) from None
    row_id, session_uuid = await asyncio.to_thread(_row_identity, request, session)
    if member.theme and getattr(session, "tmux_session", None):
        request.app.state.session_manager.set_pinned_theme(session.tmux_session, member.theme)
    from src.api.blueprints_settings import apply_settings
    await apply_settings(request, member, session_uuid, getattr(session, "tmux_session", None))
    return LaunchedSession(id=session.id, tmux_session=getattr(session, "tmux_session", None),
                           session_row_id=row_id, session_uuid=session_uuid)




def layout_name(spec: BlueprintSpec) -> str:
    return spec.name[: layouts_store.NAME_MAX].strip()


def find_layout(spec: BlueprintSpec) -> Optional[layouts_store.SavedLayout]:
    want = layouts_store.fold_name(layout_name(spec))
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        for saved in layouts_store.list_layouts(conn):
            if layouts_store.fold_name(saved.name) == want:
                return saved
    return None


def save_layout(spec: BlueprintSpec, launched: Dict[int, int],
                update: Optional[layouts_store.SavedLayout] = None) -> layouts_store.SavedLayout:
    shape = blueprints_shape.materialize(spec.shape_template, launched, len(spec.sessions))
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        if update is not None:
            written = layouts_store.set_shape(conn, update.layout_uuid, shape, update.revision)
            if written.layout is None:
                raise layouts_store.LayoutTooFewMembers("the updated layout kept fewer than two sessions")
            created = written.layout
        else:
            created = layouts_store.create_layout(conn, layout_name(spec), shape).layout
    resource_push.notify(resource_topics.LAYOUTS)
    return created


async def preview_member(request: Request, index: int, member: BlueprintSession, root: str,
                         snapshot: Optional[Any]) -> MemberPreview:
    problems: List[Problem] = []
    family_name = None
    if member.host_key:
        from src.api.blueprints_peer_member import check_supported, peer_problem

        try:
            check_supported(member)
            problems.extend(await peer_problem(member.host_key))
        except StepFailed as exc:
            problems.append(exc.problem)
        return MemberPreview(index=index, label=member.label, family=member.family,
                             folder=FolderView(mode=member.folder.mode, path=getattr(member.folder, "path", None)),
                             opening_prompt=member.opening_prompt is not None, problems=problems)
    try:
        family_name = resolve_family(member)
    except StepFailed as exc:
        problems.append(exc.problem)
    folder = FolderView(mode=member.folder.mode)
    project = None
    missing: List[str] = []
    try:
        folder, _plan = await plan_folder(member, root)
    except StepFailed as exc:
        problems.append(exc.problem)
    if folder.path is not None:
        try:
            found = await asyncio.to_thread(find_project, folder.path)
            if found is not None and found.get("archived_at"):
                problems.append(Problem(step="project", code="project_archived",
                                        detail="the project at this folder is archived"))
            project = ProjectView(known=found is not None,
                                  name=found.get("name") if found else None)
        except StepFailed as exc:
            problems.append(exc.problem)
        if member.skills:
            probe = folder.worktree.repo_path if folder.worktree and folder.worktree.create else folder.path
            missing = await asyncio.to_thread(roots_missing, request, probe)
    installed_at = folder.path if folder.worktree is None or not folder.worktree.create else None
    skills = await preview_skills(request, snapshot, installed_at, member.skills)
    return MemberPreview(index=index, label=member.label, family=member.family,
                         family_name=family_name, folder=folder, project=project, skills=skills,
                         skill_roots_to_create=missing,
                         opening_prompt=member.opening_prompt is not None, problems=problems)


async def launch_member(request: Request, index: int, member: BlueprintSession, root: str,
                        consents: Dict[str, InstallConsent], cols: Optional[int],
                        rows: Optional[int], existing: Optional[Tuple[LaunchedSession, bool]] = None,
                        ) -> MemberOutcome:
    """Run the five steps for one member; a failed step ends it with an outcome.

    ``existing`` is ``blueprints_reuse.LiveSessions.match``'s answer: a member that is
    already running is ``reused`` (nothing created, its theme untouched); one that is
    asleep is ``woken`` through the wake route, and otherwise left as it is.
    """
    folder = FolderView(mode=member.folder.mode)
    project = None
    skills: List[SkillView] = []
    if existing is not None:
        reused, asleep = existing
        folder = FolderView(mode=member.folder.mode, path=getattr(member.folder, "path", None))
        if not asleep:
            return MemberOutcome(index=index, label=member.label, state="reused", folder=folder,
                                 session=reused)
        from src.api.blueprints_reuse import wake_member

        try:
            woken = await wake_member(request, reused)
        except StepFailed as exc:
            return MemberOutcome(index=index, label=member.label, state="failed", folder=folder,
                                 problem=exc.problem)
        return MemberOutcome(index=index, label=member.label, state="woken", folder=folder,
                             session=woken)
    try:
        if member.host_key:
            from src.api.blueprints_peer_member import create_peer_member

            peer_session = await create_peer_member(member, cols, rows)
            folder = FolderView(mode="existing", path=member.folder.path)
            return MemberOutcome(index=index, label=member.label, state="launched", folder=folder,
                                 session=peer_session)
        resolve_family(member)
        folder, plan = await plan_folder(member, root)
        if plan is not None:
            await make_folder(plan, root)
        hint = (f"{os.path.basename(folder.worktree.repo_path)} ({folder.worktree.branch})"
                if folder.worktree is not None else None)
        project = await asyncio.to_thread(ensure_project, folder.path, hint)
        if member.skills:
            await asyncio.to_thread(create_member_roots, request, folder.path)
            skills = await install_skills(request, folder.path, member.skills, consents)
            refused = [s for s in skills if s.state == "refused"]
            if refused:
                raise StepFailed("skills", refused[0].code or "skill_refused",
                                 f"{len(refused)} skill(s) could not be installed; the session "
                                 "was not started so its opening prompt does not run without them")
        session = await create_member_session(request, member, folder.path, cols, rows)
    except StepFailed as exc:
        logger.info("blueprint_member_failed", index=index, step=exc.problem.step,
                    code=exc.problem.code)
        return MemberOutcome(index=index, label=member.label, state="failed", folder=folder,
                             project=project, skills=skills, problem=exc.problem)
    return MemberOutcome(index=index, label=member.label, state="launched", folder=folder,
                         project=project, skills=skills, session=session)
