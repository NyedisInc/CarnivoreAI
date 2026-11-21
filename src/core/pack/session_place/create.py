
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import pydantic
import structlog

from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.core.pack.jobs import boot, gitio
from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import decide as decide_mod
from src.core.pack.session_place.plan import OTHER_FAMILY, clean, clip, family_of
from src.core.pack.session_place.types import PlaceRequest, SessionPlacement, Starter
from src.core.pack.session_place.wire import CREATE_PATH, PeerCreateAnswer, PeerCreateBody
from src.core.pack.transport import blobs, bundles

logger = structlog.get_logger()

PEER_TIMEOUT_S = 45.0
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:@-]{1,200}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_POSTURES = ("ask", "accept_edits", "skip_all", "unknown")

LocalCreate = Callable[[Any], Awaitable[Any]]


class PlacementRefused(JobError):

    def __init__(self, placement: SessionPlacement) -> None:
        super().__init__(placement.code or "requirement_unmet", placement.reason, 409)
        self.placement = placement


@dataclass
class PlacedSession:

    session: Any
    placement: Dict[str, Any] = field(default_factory=dict)


def local_only_reason(body: Any) -> Optional[str]:
    if getattr(body, "worktree", None) is not None:
        return "a new worktree stays on this computer"
    for name, words in (("project_parent_dir", "a new project folder"), ("account_id", "a chosen account"), ("opening_prompt", "an opening prompt"),
                        ("story_ref", "a story reference"), ("copy_templates", "copied templates")):
        if getattr(body, name, None):
            return f"{words} stays on this computer"
    if getattr(body, "host_key", None) not in (None, "", "local"):
        return "a computer was chosen by hand"
    if getattr(body, "auto_start_claude", True) is False:
        return "a session without an agent stays on this computer"
    if family_of(getattr(body, "agent_type", None))[0] == OTHER_FAMILY:
        return "an agent of another kind stays on this computer"
    return None


def _outside_project(working_dir: Optional[str], root: str) -> bool:
    if not working_dir:
        return False
    folder, base = os.path.realpath(working_dir), os.path.realpath(root)
    if folder != base and not folder.startswith(base.rstrip(os.sep) + os.sep):
        return True
    current = folder
    while current != base and current != os.path.dirname(current):
        if os.path.isfile(os.path.join(current, ".git")):
            return True
        current = os.path.dirname(current)
    return False


def dirty_files(root: str) -> List[str]:
    index = gitio.out(gitio.run(["rev-parse", "--path-format=absolute", "--git-path", "index"], cwd=root, timeout=30.0)).strip()
    with tempfile.TemporaryDirectory(prefix="carnivore-index-") as scratch:
        env = {}
        if os.path.isfile(index):
            shutil.copyfile(index, os.path.join(scratch, "index"))
            env = {"GIT_INDEX_FILE": os.path.join(scratch, "index")}
        changed = gitio.out(gitio.run(["diff", "--name-only", "--no-ext-diff", "--no-textconv", "HEAD"], cwd=root, env=env, timeout=60.0)).splitlines()
        untracked = gitio.out(gitio.run(["ls-files", "--others", "--exclude-standard", "--full-name"], cwd=root, env=env, timeout=60.0)).splitlines()
    return sorted({line for line in [*changed, *untracked] if line.strip()})


def _git_facts(root: str) -> Tuple[str, str, int]:
    try:
        head = gitio.out(gitio.run(["rev-parse", "HEAD"], cwd=root, timeout=30.0)).strip()
        dirty = dirty_files(root)
        branch = bundles.carry_branch(root)
    except JobError as exc:
        if exc.code == "git_timeout":
            raise
        raise JobError("not_a_repo", "the project folder has no commit to start from", 409) from exc
    except (bundles.BundleError, OSError) as exc:
        raise JobError("not_a_repo", "the project folder has no commit to start from", 409) from exc
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise JobError("not_a_repo", "the project folder has no commit to start from", 409)
    return head, branch, len(dirty)


def _project(name: str) -> Dict[str, Any]:
    from src.core.project_writes import ProjectNotFound, resolve_by_name

    try:
        with closing(boot.engine()._open_db()) as conn:  # noqa: SLF001
            return dict(resolve_by_name(conn, name))
    except ProjectNotFound as exc:
        raise JobError("project_unknown", f"no project named {name[:64]}", 404) from exc


def _peer(install_id: str) -> peer_hosts.PeerRow:
    from src.api import peer_auth

    with closing(peer_auth.open_db()) as conn:
        for row in peer_hosts.list_peers(conn):
            if row.peer_install_id == install_id:
                return row
    raise JobError("unreachable", "that computer is not paired", 502)


async def _carry(project: Dict[str, Any], install_id: str, label: str) -> Dict[str, Any]:
    from src.api.project_transport_routes import carry_to

    return await carry_to(project, install_id, label, False)


def _refusal(status: int, body: Any) -> JobError:
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    text = detail.get("detail") if isinstance(detail, dict) else detail
    return JobError(str(code) if code and _SAFE_CODE.match(str(code)) else f"http_{status}", clean(text), status)


async def _post(install_id: str, label: str, body: PeerCreateBody) -> PeerCreateAnswer:
    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    if client is None:
        raise JobError("unreachable", f"{label} is not connected", 502)
    request = blobs.request_via(client, PEER_TIMEOUT_S)
    status, answer = 0, None
    for attempt in (1, 2):
        try:
            status, answer = await request("POST", CREATE_PATH, json=body.model_dump(exclude_none=True))
            break
        except (asyncio.TimeoutError, PeerUnreachable) as exc:
            if attempt == 2 or (isinstance(exc, PeerUnreachable) and exc.hard):
                raise JobError("unreachable", f"{label} did not answer", 502) from exc
        except (PeerRefused, OSError) as exc:
            raise JobError("unreachable", f"{label} did not answer", 502) from exc
    if status != 200:
        raise _refusal(status, answer)
    try:
        got = PeerCreateAnswer.model_validate(answer)
    except pydantic.ValidationError as exc:
        raise JobError("bad_answer", f"{label} answered something this computer could not read", 502) from exc
    if not _SAFE_NAME.match(got.tmux_name):
        raise JobError("bad_answer", f"{label} answered a session name this computer will not use", 502)
    return got


def _posture(starter: Starter) -> str:
    return starter.posture if starter.posture in _POSTURES else "unknown"


async def _start_remote(plan: SessionPlacement, project: Dict[str, Any], req: PlaceRequest, starter: Starter, body: Any, rid: str) -> Dict[str, Any]:
    if not plan.install_id or not plan.label:
        raise JobError("bad_answer", "the placement named no computer", 502)
    head, branch, dirty = await asyncio.to_thread(_git_facts, project["root"])
    try:
        sent = PeerCreateBody(request_id=rid, project_uid=plan.project_uid or project["uid"], home_head=head, branch=branch, family=req.family,
                              profile_name=req.profile_name, posture=_posture(starter), model=body.model or starter.model, account_key=starter.account_key,
                              label=(body.label or "")[:120], cols=body.cols, rows=body.rows)
    except pydantic.ValidationError as exc:
        raise JobError("bad_request", "this session's settings do not fit a create on another computer", 422) from exc
    peer = await asyncio.to_thread(_peer, plan.install_id)
    carried = await _carry(project, plan.install_id, plan.label)
    if carried.get("error"):
        code = str(carried["error"])
        raise JobError("unreachable" if code == "machine_unreachable" else (code if _SAFE_CODE.match(code) else "carry_failed"),
                       f"{plan.label} could not receive the project's commits", 502)
    got = await _post(plan.install_id, plan.label, sent)
    wire_id = f"{REMOTE_ID_PREFIX}{peer.key}:{got.tmux_name}"
    session = {"id": wire_id, "session_uuid": got.session_uuid, "tmux_session": got.tmux_name, "working_dir": clean(got.working_dir),
               "host_key": peer.key, "host_label": peer.label, "label": body.label, "agent_type": req.family,
               **({"epoch": got.epoch} if got.epoch is not None else {})}
    block = {**plan.wire(), "request_id": rid, "reasons": [plan.reason], "left_behind": dirty,
             "work_lives": clean(f"{plan.label} keeps this session's work until it pushes or you move it back"),
             "started_at": {"head": head[:12], "branch": clean(branch)}, "account": clean(got.account_label), "account_how": clean(got.account_how, 64),
             "profile_used": clean(got.profile_used), "note": clean(got.copy_note) if got.copy_note else None, "replayed": False}
    return {"session": session, "block": block, "answer": got}


def _record(rid: str, plan: SessionPlacement, starter: Starter, *, decision: str, session_id: Optional[str], session_uuid: Optional[str], reason: str) -> None:
    try:
        boot.engine().store.placement_put(rid, project_uid=plan.project_uid, install_id=plan.install_id or "", label=plan.label or "", decision=decision,
                                          session_id=session_id, session_uuid=session_uuid, reason=reason, starter_kind=starter.kind)
    except (JobError, sqlite3.Error) as exc:
        logger.warning("session_place_record_failed", request_id=rid, error=type(exc).__name__)


def _replay(row: Dict[str, Any]) -> PlacedSession:
    block = {"decision": "remote", "computer": row.get("install_id"), "label": row.get("label"), "reason": row.get("reason") or "", "code": None,
             "request_id": row["request_id"], "reasons": [row.get("reason") or ""], "left_behind": None,
             "work_lives": clean(f"{row.get('label')} keeps this session's work until it pushes or you move it back"), "replayed": True}
    return PlacedSession({"id": row["session_id"], "session_uuid": row.get("session_uuid"), "host_label": row.get("label")}, block)


async def _here(reasons: List[str], reason: str, local_create: LocalCreate, body: Any, rid: str, plan: SessionPlacement, starter: Starter) -> PlacedSession:
    session = await local_create(body)
    sid = getattr(session, "id", None) or (session.get("id") if isinstance(session, dict) else None)
    await asyncio.to_thread(_record, rid, plan, starter, decision="here", session_id=sid, session_uuid=None, reason=reason)
    block = {"decision": "here", "computer": None, "label": None, "reason": reason, "code": None, "request_id": rid, "reasons": reasons,
             "left_behind": None, "work_lives": None, "replayed": False}
    return PlacedSession(session, block)


async def create_placed(app: Any, req: PlaceRequest, starter: Starter, body: Any, *, local_create: LocalCreate, request_id: Optional[str] = None,
                        approved: Optional[SessionPlacement] = None) -> PlacedSession:
    rid = request_id or uuid.uuid4().hex
    store = boot.engine().store
    prior = await asyncio.to_thread(store.placement_get, rid)
    if prior and prior.get("decision") == "remote" and prior.get("session_id"):
        return _replay(prior)
    stays = local_only_reason(body)
    first = approved if approved is not None else await decide_mod.decide(app, req)
    revoked = await decide_mod.still_allowed(req, approved.install_id) if approved is not None and approved.decision == "remote" and approved.install_id else ""
    if revoked:
        first = SessionPlacement("here", clip(f"{approved.label or 'that computer'}: {revoked}"), project_uid=approved.project_uid,
                                 project_name=approved.project_name)
    if stays is not None:
        first = SessionPlacement("here", clip(stays), project_uid=first.project_uid, project_name=first.project_name)
    if first.decision == "refused":
        raise PlacementRefused(first)
    project = await asyncio.to_thread(_project, first.project_name) if first.decision == "remote" else {}
    if first.decision == "remote" and await asyncio.to_thread(_outside_project, req.working_dir, str(project["root"])):
        first = SessionPlacement("here", clip("a worktree of the project stays on this computer"), project_uid=first.project_uid, project_name=first.project_name)
    current, failed, reasons, last = first, [], [], ("", "")
    for attempt in (1, 2):
        if current.decision != "remote":
            break
        try:
            done = await _start_remote(current, project, req, starter, body, rid)
        except JobError as exc:
            logger.info("session_place_refused", computer=current.label, code=exc.code, attempt=attempt)
            last = (str(current.label), exc.detail or exc.code)
            reasons += [current.reason, clip(f"{last[0]} refused: {last[1]}")]
            failed.append(current.install_id)
            if approved is not None or attempt == 2:
                current = SessionPlacement("here", "", project_uid=first.project_uid)
                break
            current = await decide_mod.decide(app, req, exclude=failed)
            if current.decision == "refused":
                current = SessionPlacement("here", current.reason, project_uid=first.project_uid)
            continue
        block, answer = done["block"], done["answer"]
        await asyncio.to_thread(_record, rid, current, starter, decision="remote", session_id=done["session"]["id"], session_uuid=answer.session_uuid,
                                reason=block["reason"])
        block["reasons"] = reasons + block["reasons"]
        return PlacedSession(done["session"], block)
    if not failed:
        return await _here([first.reason], first.reason, local_create, body, rid, first, starter)
    if current.reason:
        reasons.append(current.reason)
    return await _here(reasons, clip(f"{last[0]} refused ({last[1]})"), local_create, body, rid, first, starter)
