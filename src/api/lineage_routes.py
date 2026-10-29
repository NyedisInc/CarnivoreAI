
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.config import settings
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.flow_data import spawn_links
from src.core.lineage import constants as K
from src.core.lineage import graph, milestones, timeline, view
from src.api.error_response import api_error

router = APIRouter(tags=["lineage"], dependencies=[Depends(require_auth)])


class Edge(BaseModel):
    """One stored edge: parent -> child of one kind, with how it is known."""

    parent_type: str
    parent_id: str
    child_type: str
    child_id: str
    edge_kind: str = Field(description="clear, fork, rewind, resume, switch, compact_continue, subagent or spawned_by")
    link_basis: str = Field(description="recorded, inferred_fork_pointer, inferred_unique_candidate or inferred_active_session")
    created_at: Optional[str] = None
    detail: Dict[str, Any] = Field(default_factory=dict, description="metadata of the link points (uuids, agent ids, tool_use ids), never text")


class Sibling(BaseModel):
    """A node sharing a parent with the asked one through the same kind (derived, not stored)."""

    node_type: str
    node_id: str
    via_parent_type: str
    via_parent_id: str
    edge_kind: str
    link_basis: str


class Milestone(BaseModel):
    """One moment of a conversation."""

    conversation_id: str
    kind: str = Field(description="compact, clear, fork, rewind, resume, restart, sleep, kill, save, remove or switch")
    at: Optional[str] = None
    session_uuid: Optional[str] = None
    jsonl_line: Optional[int] = None
    jsonl_offset: Optional[int] = None
    source: str = Field(description="pipeline, jsonl_scan, backfill or archive")
    detail: Dict[str, Any] = Field(default_factory=dict)


class TimelineEntry(BaseModel):
    """One conversation of a session, in the order lived: how it began (with the split point when it was cut
    from another conversation) and its milestones."""

    conversation_id: str
    current: bool
    level: Optional[str] = None
    began: Optional[Dict[str, Any]] = Field(None, description="kind, from_conversation, basis, at, split {conversation, message_uuid, line}")
    milestones: List[Dict[str, Any]] = Field(default_factory=list)


class Neighbourhood(BaseModel):
    """Everything linked to one node. ``conversations`` lists a session's held conversations, current first;
    ``levels`` maps ``type:id`` of the node and every neighbour to its tree level (human, subsession, agent, null)."""

    node: Dict[str, str]
    levels: Dict[str, Optional[str]] = Field(default_factory=dict)
    conversations: List[str] = Field(default_factory=list)
    parents: List[Edge] = Field(default_factory=list)
    children: List[Edge] = Field(default_factory=list)
    siblings: List[Sibling] = Field(default_factory=list)
    subagents: List[Edge] = Field(default_factory=list)
    milestones: List[Milestone] = Field(default_factory=list)
    timeline: List[TimelineEntry] = Field(default_factory=list, description="a session only: its conversations oldest first, current last")
    spawn_link: Optional[Dict[str, Any]] = Field(None, description="a session only: who agent_spawn'ed it (parent_id, parent_uuid, parent_kind session|external, task_message_id, spawned_at), else null (#1608)")
    spawn_children: List[Dict[str, Any]] = Field(default_factory=list, description="a session only: the agents it spawned through agent_spawn, oldest first (#1608)")


def _build(node_type: str, node_id: str) -> Optional[Dict[str, Any]]:
    path = db_path_for(settings.get_state_dir())
    if not path.exists():
        raise HTTPException(status_code=404, detail="no datastore yet")
    try:
        with closing(connect(path, create=False)) as conn:
            if not graph.ready(conn):
                raise HTTPException(status_code=503, detail="the datastore has no lineage graph yet (schema v49)")
            found = view.neighbourhood(conn, node_type, node_id)
            if found is None:
                return None
            owners = found["conversations"] if node_type == K.NODE_SESSION else (
                [node_id] if node_type == K.NODE_CONVERSATION else [])
            found["milestones"] = [{"conversation_id": conv, **m} for conv in owners
                                   for m in milestones.milestones_of(conn, conv)]
            if node_type == K.NODE_SESSION:
                found["timeline"] = timeline.session_timeline(conn, node_id) or []
                found["spawn_link"] = spawn_links.parent_of(child_uuid=node_id, conn=conn)
                found["spawn_children"] = spawn_links.children_of(parent_uuid=node_id, conn=conn)
            return found
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="_build") from exc


@router.get("/lineage/{node_type}/{node_id:path}", response_model=Neighbourhood)
async def lineage_of(node_type: str, node_id: str) -> Neighbourhood:
    """Parents, children, siblings, subagents and milestones of one node.

    Description: 400 for an unknown node type, 404 for a session that does not exist (a conversation or
      subagent with no edges answers empty lists), 503 when the datastore predates schema v49.
    """
    if node_type not in K.NODE_TYPES:
        raise HTTPException(status_code=400, detail=f"node_type must be one of {', '.join(K.NODE_TYPES)}")
    found = await run_in_threadpool(_build, node_type, node_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such session")
    return Neighbourhood(**found)
