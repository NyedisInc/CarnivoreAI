
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool

from src.api import peer_auth
from src.config import settings
from src.core.federation import peer_fanout, peer_merge
from src.models.project_history import ProjectHistoryResponse
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()


def _read_rows(state_dir: Any, *, include_automated: bool, include_conversations: bool) -> Optional[Tuple[List[dict], List[dict]]]:
    from src.core import session_store
    from src.core.companies import hero_art_gen, hero_images
    from src.core.companies.store import attach_company_names
    from src.core.db import connect, db_path_for, table_exists
    from src.core.pack.identity.home import attach_machine_labels

    db_path = db_path_for(state_dir)
    if not db_path.exists():
        return None
    with closing(connect(db_path, create=False)) as conn:
        projects = (
            [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY id").fetchall()]
            if table_exists(conn, "projects")
            else []
        )
        attach_company_names(conn, projects)
        attach_machine_labels(conn, projects)
        hero_images.attach(hero_images.PROJECT, projects)
        _attach_storage(conn, projects)
        hero_art_gen.schedule_missing(hero_images.PROJECT, projects)
        rows = session_store.list_sessions(
            conn,
            include_archived=True,
            include_lineage=include_conversations,
            include_automated=include_automated,
        )
    return projects, rows


def _attach_storage(conn, projects: list) -> None:
    from src.core.project_pack import jobs
    from src.core.project_pack.view import storage_by_project

    found = storage_by_project(conn, {p["id"]: p["root"] for p in projects}, jobs.progress_of)
    for project in projects:
        project["storage"] = found.get(project["id"])


def _live_ids(request: Request) -> Dict[str, str]:
    manager = getattr(request.app.state, "session_manager", None)
    registry = getattr(manager, "_registry", None)
    backends = getattr(registry, "backends", None) or {}
    out: Dict[str, str] = {}
    for sid, backend in list(backends.items()):
        name = getattr(backend, "tmux_session", None)
        if isinstance(name, str) and name and name not in out:
            out[name] = sid
    return out


def _peer_query(request: Request) -> List[Tuple[str, str]]:
    return [(k, v) for k, v in request.query_params.multi_items() if k not in ("offset", "project")]


def _theme_reader() -> Any:
    from src.core.sessions.theme_dotfile import read_project_theme

    def read(project: Mapping[str, Any]) -> Optional[str]:
        root = project.get("root")
        return read_project_theme(root) if root else None

    return read


@router.get(
    "/projects/history",
    response_model=ProjectHistoryResponse,
    dependencies=[Depends(peer_auth.require_peer_sessions)],
)
async def get_projects_history(
    request: Request,
    q: Optional[str] = Query(None, description="Search project name and folder, session title, tmux name, agent and conversation id"),
    state: Optional[str] = Query(None, description="Comma list of running, asleep, closed, removed, unknown; empty is all"),
    agent: Optional[str] = Query(None, description="Comma list of agent families ('unknown' for none); empty is all"),
    since: Optional[str] = Query(None, description="ISO date or datetime; sessions last active at or after it"),
    until: Optional[str] = Query(None, description="ISO date or datetime; sessions last active at or before it"),
    project_state: str = Query("all", description="all, active or archived projects"),
    include_empty: bool = Query(True, description="List projects with no matching session too"),
    project: Optional[str] = Query(None, description="One group only: a project id, or 'none' for sessions with no project"),
    sort: str = Query("recent", description="recent (newest activity first), name, or oldest"),
    offset: int = Query(0, description="Groups to skip"),
    limit: int = Query(25, description="Groups per page, 1 to 100"),
    session_limit: int = Query(10, description="Sessions returned per group, 1 to 500; session_total says how many match"),
    include_automated: bool = Query(
        False,
        description="Include kind='automated' rows (scheduler runs, headless probes). Off by default: lists are the user's own.",
    ),
    include_conversations: bool = Query(
        False, description="Include past-conversation rows (a /clear or compact inside one tmux session)"
    ),
) -> ProjectHistoryResponse:
    """One page of every project with its session history.

    Description: groups are projects (plus a last "no project" group for
      sessions whose project is unknown); see ``src/core/project_history/
      query.py`` for the exact filter rule. ``has_transcript`` says whether
      a closed row's conversation can be resumed from the live transcript
      corpus. ``live_session_id`` is the app id a running row can be
      opened under.
    Inputs: the query parameters above.
    Output: ProjectHistoryResponse. ``state='no_datastore'`` with no groups
      when this install has no ``cloude.db`` - never rendered as "no projects".
    Raises: HTTPException 400 - a parameter could not be understood (the
      detail names it). HTTPException 503 - the datastore is unreadable.
      A paired Mac's groups ride beside the local page as ``peer_groups`` (first page and no one-group drill-down
      only), fetched at request time with each session tagged with its machine; one it cannot reach is named in
      ``peer_unavailable``. A caller holding a peer token gets THIS Mac's own rows alone and nothing fans out.
    Example: GET /api/v1/projects/history?state=running,asleep&include_empty=false
    """
    from src.api.session_record_payload import _family_name_for_row
    from src.core.db import DatastoreUnreadableError
    from src.core.project_history import HistoryQuery, HistoryQueryError, build_history, transcript_uuid_index
    from src.core.project_history.query import RowFacts

    try:
        parsed = HistoryQuery.parse(
            q=q, state=state, agent=agent, since=since, until=until,
            project_state=project_state, include_empty=include_empty, project=project,
            sort=sort, offset=offset, limit=limit, session_limit=session_limit,
        )
    except HistoryQueryError as exc:
        raise api_error(400, "invalid_request", exc, step="get_projects_history") from exc

    try:
        read = await run_in_threadpool(
            _read_rows,
            settings.get_state_dir(),
            include_automated=include_automated,
            include_conversations=include_conversations,
        )
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="get_projects_history") from exc
    if read is None:
        return ProjectHistoryResponse(state="no_datastore")
    projects, rows = read
    from_peer = peer_fanout.is_peer_call(request)
    if from_peer:
        rows = [r for r in rows if (r.get("host_key") or "local") == "local"]
    peer_call = None if from_peer or offset or project else asyncio.create_task(
        peer_fanout.ask_peers("/projects/history?" + urlencode(_peer_query(request)), peer_auth.open_db))

    transcripts = await run_in_threadpool(transcript_uuid_index)
    live = _live_ids(request)

    def live_id_of(row: Mapping[str, Any]) -> Optional[str]:
        if (row.get("host_key") or "local") != "local":
            return None
        return live.get(row.get("tmux_name") or "")

    facts = RowFacts(
        family_of=_family_name_for_row,
        live_id_of=live_id_of,
        transcripts=transcripts,
        theme_of=_theme_reader(),
    )
    result = await run_in_threadpool(build_history, projects, rows, parsed, facts)
    logger.debug(
        "projects_history_served",
        total=result["total"],
        offset=parsed.offset,
        returned=len(result["groups"]),
    )
    if peer_call is not None:
        held = peer_merge.Held(
            {r["claude_session_uuid"] for r in rows if r.get("claude_session_uuid")},
            {(r.get("host_key"), r.get("tmux_name")) for r in rows if (r.get("host_key") or "local") != "local"},
        )
        result = peer_merge.merge_history(result, await peer_call, held)
    return ProjectHistoryResponse(state="ok", **result)
