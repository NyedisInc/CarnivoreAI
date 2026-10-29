
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api import peer_auth, project_replica_routes as replica_routes, projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core.companies import accounts as company_accounts
from src.core.db import transaction
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.identity import home, replicas
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.transport import blobs, bundles, gh_helper, github_account, ladder, publish, sync

logger = structlog.get_logger()
router = APIRouter()
pack_capabilities.register("pack.transport")

CAP_TRANSPORT = "pack.transport"


class SyncBody(BaseModel):
    """Which machine to carry to (omitted: every replica carried by Carnivore) and whether to resend everything."""

    model_config = ConfigDict(extra="forbid")

    machine: Optional[str] = Field(default=None, max_length=200)
    full: bool = False


class GithubAccountBody(BaseModel):
    """The gh account the project uses; null clears the pointer."""

    model_config = ConfigDict(extra="forbid")

    account: Optional[str] = Field(default=None, max_length=64)


class PublishBody(BaseModel):
    """Answers to the card. There is NO visibility field: the repo is always private."""

    model_config = ConfigDict(extra="forbid")

    owner: Optional[str] = Field(default=None, max_length=64)
    account: Optional[str] = Field(default=None, max_length=64)


def _open():
    return projects_service.open_db_or_503(settings)


def _live_project(conn: Any, name: str) -> Dict[str, Any]:
    project = projects_service.resolve_target(conn, name)
    if project.get("pack_state") == home.MOVED_AWAY:
        raise home.ProjectMovedAway(project["display_name"], home.machine_label(conn, project.get("moved_to_install_id")), project["root"])
    return project


def _company_pointer(conn: Any, project: Dict[str, Any], key: str) -> Optional[str]:
    if project.get("company_id") is None:
        return None
    try:
        return company_accounts.get_accounts(conn, project["company_id"]).get(key)
    except Exception as exc:  # noqa: BLE001
        logger.info("pack_company_pointer_unreadable", error=type(exc).__name__)
        return None


def _root_state(project: Dict[str, Any]) -> Dict[str, Any]:
    root = project["root"]
    is_repo = os.path.isdir(root) and bundles.is_repo(root)
    return {"is_repo": is_repo, "origin": bundles.origin_url(root) if is_repo else None}


def _resolution(conn: Any, project: Dict[str, Any], origin: Optional[str]) -> github_account.Resolution:
    return github_account.resolve(air_gap=bool(project.get("air_gap")), project_account=project.get("github_account"),
                                  company_account=_company_pointer(conn, project, "github_login"), origin_url=origin)


def _account_view(project: Dict[str, Any], res: github_account.Resolution) -> Dict[str, Any]:
    return {"project_uid": project["uid"], "name": project["display_name"], "air_gap": bool(project.get("air_gap")),
            "account": res.account, "source": res.source, "needs_card": res.needs_card}


@router.post("/projects/{project_name}/sync", dependencies=[Depends(require_auth)])
async def sync_project(project_name: str, body: SyncBody) -> Dict[str, Any]:
    """Carry the project's new branches and tags to its replicas (or to its home, from a replica) as a git bundle.

    Description: rung 2 of the transport ladder. The receiver stores them under ``refs/carnivore/<this install>/...`` and never
      touches its own branches. Omitting ``machine`` sends to every replica carried by Carnivore (every replica when the
      project is air-gapped); ``full`` resends everything. Per-machine failures are reported, not raised.
    Inputs: project_name; body (SyncBody). Output: {project_uid, results: [{machine, sent, refs?, reason?, error?}]}.
    Raises: HTTPException 404 unknown project/machine/replica, 409 ``project_moved_away`` or ``not_a_repo``.
    Example: POST /api/v1/projects/ledgerbot/sync {"machine": "hosta"}
    """
    def read() -> Dict[str, Any]:
        with closing(_open()) as conn:
            project = _live_project(conn, project_name)
            if project["pack_state"] == home.REPLICA:
                targets = [{"install_id": project["home_install_id"], "rung": ladder.RUNG_CARRIED}]
            else:
                targets = [{"install_id": r["install_id"], "rung": r["transport_rung"]} for r in replicas.list_replicas(conn, project["uid"])]
            return {"project": project, "targets": targets, "git": _root_state(project)}

    found = await run_in_threadpool(read)
    project = found["project"]
    if not found["git"]["is_repo"]:
        raise HTTPException(409, {"code": "not_a_repo", "detail": "the project folder is not a git repository, so there are no commits to carry"})
    targets: List[Dict[str, Any]] = found["targets"]
    if body.machine:
        peer = await run_in_threadpool(replica_routes.find_peer, body.machine)
        targets = [t for t in targets if t["install_id"] == peer.peer_install_id]
        if not targets:
            raise HTTPException(404, {"code": "unknown_replica", "detail": f"{peer.label} holds no replica of {project['display_name']!r} and is not its home"})
    else:
        targets = [t for t in targets if t["rung"] == ladder.RUNG_CARRIED or project.get("air_gap")]
    with closing(peer_auth.open_db()) as peer_conn:
        labels = {p.peer_install_id: str(p.label) for p in peer_hosts.list_peers(peer_conn)}
    results: List[Dict[str, Any]] = []
    for target in targets:
        results.append(await carry_to(project, target["install_id"], labels.get(target["install_id"], target["install_id"]), body.full))
    return {"project_uid": project["uid"], "results": results}


async def carry_to(project: Dict[str, Any], install_id: str, label: str, full: bool) -> Dict[str, Any]:
    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    if client is None:
        return {"machine": label, "sent": False, "error": "machine_unreachable"}
    if CAP_TRANSPORT not in links.capabilities(install_id):
        return {"machine": label, "sent": False, "error": "runs_older_carnivore"}
    try:
        answer = await sync.carry_bundle(
            repo=project["root"], project_uid=project["uid"], peer_install_id=install_id, request=blobs.request_via(client),
            open_db=_open, outbox=str(Path(settings.get_state_dir()) / "pack" / "outbox"), air_gap=bool(project.get("air_gap")), full=full)
    except (bundles.BundleError, blobs.BlobError) as exc:
        return {"machine": label, "sent": False, "error": exc.code}
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError) as exc:
        logger.info("pack_sync_unreachable", machine=label, error=type(exc).__name__)
        return {"machine": label, "sent": False, "error": "machine_unreachable"}
    logger.info("pack_sync_done", project_uid=project["uid"], machine=label, sent=answer.get("sent"))
    return {"machine": label, **answer}


@router.get("/projects/{project_name}/github-account", dependencies=[Depends(require_auth)])
async def get_github_account(project_name: str) -> Dict[str, Any]:
    """Which gh account this project uses and where that came from (project, company, remote_owner, none or air_gap).
    """
    def read() -> Dict[str, Any]:
        with closing(_open()) as conn:
            project = projects_service.resolve_target(conn, project_name)
            air_gap = bool(project.get("air_gap"))
            state = _root_state(project)
            res = _resolution(conn, project, state["origin"] if not air_gap else None)
            out = _account_view(project, res)
            try:
                choice = ladder.choose_rung(purpose=ladder.PURPOSE_SPAN, air_gap=air_gap, has_git=state["is_repo"], has_remote=state["origin"] is not None)
                out["rung"], out["rung_reason"] = choice.rung, choice.reason
            except ladder.RungUnavailable as exc:
                out["rung"], out["rung_reason"] = "none", exc.detail
            out["logged_in"] = [] if air_gap else github_account.logged_in_accounts()
            return out

    return await run_in_threadpool(read)


@router.put("/projects/{project_name}/github-account", dependencies=[Depends(require_auth)])
async def put_github_account(project_name: str, body: GithubAccountBody) -> Dict[str, Any]:
    def write() -> Dict[str, Any]:
        with closing(_open()) as conn:
            project = _live_project(conn, project_name)
            if project.get("air_gap"):
                raise HTTPException(409, {"code": "air_gap", "detail": "air-gap is on for this project; it never contacts GitHub"})
            chosen = body.account
            if chosen is not None:
                if not github_account.valid_account(chosen):
                    raise HTTPException(422, {"code": "bad_account", "detail": "that is not a GitHub account name"})
                match = next((a for a in github_account.logged_in_accounts() if a.lower() == chosen.lower()), None)
                if match is None:
                    raise HTTPException(422, {"code": "account_not_logged_in", "detail": f"gh is not logged in as {chosen} on this computer"})
                chosen = match
            with transaction(conn):
                github_account.store_project_account(conn, project["id"], chosen)
            project = projects_service.resolve_target(conn, project_name)
            helper = "skipped"
            if chosen and project["pack_state"] == home.REPLICA and _root_state(project)["is_repo"]:
                try:
                    gh_helper.install(project["root"], chosen, air_gap=False)
                    helper = "installed"
                except (github_account.AccountError, RuntimeError) as exc:
                    helper = getattr(exc, "code", None) or str(exc)
            home.notify_changed()
            return {**_account_view(project, _resolution(conn, project, None)), "helper": helper}

    return await run_in_threadpool(write)


def _card(conn: Any, project: Dict[str, Any], owner: Optional[str], account: Optional[str]) -> Dict[str, Any]:
    state = _root_state(project) if not project.get("air_gap") else {"origin": None}
    res = _resolution(conn, project, state["origin"])
    if account and github_account.valid_account(account):
        res = github_account.Resolution(account, github_account.SOURCE_PROJECT)
    return publish.card(display_name=project["display_name"], air_gap=bool(project.get("air_gap")), has_remote=state["origin"] is not None,
                        owner_pointer=owner or _company_pointer(conn, project, "github"), account=res)


@router.get("/projects/{project_name}/publish-repo", dependencies=[Depends(require_auth)])
async def get_publish_card(project_name: str) -> Dict[str, Any]:
    """
    Output: {name, private: true, owner, account, account_source, asks: [owner|account], offered, reason}.
    Example: GET /api/v1/projects/notes/publish-repo
    """
    def read() -> Dict[str, Any]:
        with closing(_open()) as conn:
            project = _live_project(conn, project_name)
            return _card(conn, project, None, None)

    return await run_in_threadpool(read)


@router.post("/projects/{project_name}/publish-repo", dependencies=[Depends(require_auth)])
async def post_publish_repo(project_name: str, body: PublishBody) -> Dict[str, Any]:
    """Create a PRIVATE GitHub repo for a project with no remote, push its first commit and remember the account.
    """
    def run() -> Dict[str, Any]:
        with closing(_open()) as conn:
            project = _live_project(conn, project_name)
            card = _card(conn, project, body.owner, body.account)
            if not card["offered"]:
                raise HTTPException(409, {"code": card["reason"], "detail": "a private repo is not offered for this project"})
            if card["asks"]:
                raise HTTPException(409, {"code": "needs_answer", "detail": "the card still needs an owner and an account", "card": card})
            try:
                made = publish.publish(project["root"], name=card["name"], owner=card["owner"], account=card["account"], air_gap=False)
            except publish.PublishRefused as exc:
                raise HTTPException(409, {"code": exc.code, "detail": exc.detail, "files": exc.files}) from exc
            except github_account.AccountError as exc:
                raise HTTPException(409, {"code": exc.code, "detail": exc.detail}) from exc
            with transaction(conn):
                github_account.store_project_account(conn, project["id"], card["account"])
            home.notify_changed()
            return made

    return await run_in_threadpool(run)
