"""API routes for user-defined session-sidebar groups.

Deliberately thin: request/response shape, auth, error translation, and
the datastore connection dance. Every rule about what a group IS lives
in ``src/core/session_group_store.py``, and this module never re-decides
one.

Mounted under ``/api/v1`` from ``src/main.py`` alongside the other
routers. Its own routes are a separate module rather than more lines in
``src/api/routes.py`` because that file is already 2687 lines, well past
the project's 500-line budget, and adding to it makes an existing
problem worse.

THREE OUTCOMES ON EVERY READ, and it is the whole reason ``status``
exists on the response instead of the route just returning a list:

  'ok'          the tables were read. ``groups`` reflects them, and an
                empty list genuinely means this install has no groups.
  'unavailable' the datastore is absent, predates v8, or would not open.
                ``groups`` is ``[]`` AND ``status`` says why. A client
                that renders this as "no groups" is drawing a conclusion
                nobody measured, so the client is required to read the
                field - see client/js/session-sidebar-group-store.js,
                which refuses to draw group chrome at all in this state
                rather than drawing an empty group list.

A 200 with an empty list and a 200 with ``status='unavailable'`` are the
same HTTP status on purpose: the sidebar must keep working - ungrouped -
when groups cannot be read, and turning that into a 503 would make an
unreadable group table break the session list itself. The distinction
lives in the body, where the client can act on it, rather than in a
status code that would take the panel down.

WRITES ARE THE OPPOSITE. A write that could not happen returns 503, not
a cheerful 200, because a silently-dropped assignment is a group the
user watched themselves make that is not there after a reload.
"""

from __future__ import annotations

from contextlib import closing
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.core import icon_registry
from src.core import session_change_notice
from src.core import session_group_store as store
from src.core import session_group_style as style_store
from src.core.db import DatastoreUnreadableError, connect, db_path_for

logger = structlog.get_logger()

router = APIRouter(prefix="/session-groups", tags=["session-groups"])

STATUS_OK = "ok"

# CANNOT DETERMINE
STATUS_UNAVAILABLE = "unavailable"


class SessionGroupModel(BaseModel):
    """One group as the sidebar receives it.

    ``members`` carries tmux names, which is the key the sidebar's rows,
    its pin set and its manual order all already use.
    """

    group_uuid: str = Field(..., description="Stable public identity")
    name: str = Field(..., description="User's label, already trimmed")
    position: int = Field(..., description="Sort key, ascending")
    members: List[str] = Field(
        default_factory=list, description="tmux names filed in this group"
    )
    member_session_uuids: List[str] = Field(
        default_factory=list,
        description=(
            "The durable key of every member, in the group's stored order: "
            "sessions.session_uuid for a session, or `layout:<uuid>` for a "
            "saved Layout (issue #831). THE COMPLETE MEMBERSHIP: an "
            "imported conversation has no tmux name, and a Layout never "
            "has one either, so both appear here and not in `members`."
        ),
    )
    colour: str = Field(
        ..., description="Palette key the drawer paints this group's heading with"
    )
    gradient: Optional[str] = Field(
        default=None, description="Gradient key, or null for a flat colour"
    )
    animation: str = Field(default="none", description="'none' | 'shimmer' | 'pulse'")
    style_source: str = Field(
        ...,
        description=(
            "'stored' (picked, or given at create) or 'derived' (no style was "
            "ever written; the colour is a stable hash of the group uuid)"
        ),
    )
    icon: Optional[str] = Field(default=None, description="Icon registry id, or null")


class SessionGroupsResponse(BaseModel):
    """Every group, plus an explicit verdict about whether that is known.

    ``status='unavailable'`` with ``groups=[]`` is NOT the same claim as
    ``status='ok'`` with ``groups=[]``, and the client is required to
    tell them apart.
    """

    status: str = Field(..., description="'ok' | 'unavailable'")
    groups: List[SessionGroupModel] = Field(default_factory=list)
    detail: Optional[str] = Field(
        default=None, description="Why, whenever status != 'ok'"
    )


class CreateGroupRequest(BaseModel):
    name: str = Field(..., description="Label, trimmed and bounded server-side")


class RenameGroupRequest(BaseModel):
    name: str


class AssignRequest(BaseModel):
    """Move one session, or one saved Layout, into a group, or out of every group.

    ``group_uuid=None`` means ungrouped, which is expressed as the
    ABSENCE of a membership row rather than as a row naming a sentinel
    group. This one body is what the drag, the row menu and the keyboard
    picker all send, so the three cannot drift apart in what a move
    means.

    EXACTLY ONE OF ``tmux_name`` / ``layout_uuid`` (issue #831): a saved
    Layout has no tmux name to resolve, so it is filed by its own uuid
    instead - see ``src/core/session_group_membership.py``'s
    ``assign_layout``. Both present or both absent is a 400, checked in
    the route below rather than a validator, so the message names both
    fields plainly.
    """

    tmux_name: Optional[str] = None
    layout_uuid: Optional[str] = None
    group_uuid: Optional[str] = None


class MemberOrderRequest(BaseModel):
    """The WHOLE desired order WITHIN one group, by durable key.

    Same contract as ``ReorderRequest`` one level down, and by
    ``session_uuid`` rather than tmux name for the reason the v24 re-key
    exists: two sessions can share a name, and an imported one has none.
    A uuid that is not a member of this group is IGNORED - reordering is
    not filing, and a reorder that could also assign would let a drag
    inside one group silently steal a row out of another.
    """

    session_uuids: List[str]


class StyleRequest(BaseModel):
    """A group's WHOLE style, replacing the previous one (issue #694).

    Keys, never colours: the server validates each against
    ``src/core/session_group_style.py`` and the drawer's stylesheet
    resolves them to theme tokens. An unknown key is a 400.
    """

    colour: str = Field(..., description="One of session_group_style.COLOURS, or a custom #rrggbb hex")
    gradient: Optional[str] = Field(
        default=None, description="One of session_group_style.GRADIENTS, or null"
    )
    animation: str = Field(
        default="none", description="One of session_group_style.ANIMATIONS"
    )


class ReorderRequest(BaseModel):
    """The WHOLE desired group order, not a move-one-step delta.

    A delta lets the client and the database disagree about the result of
    a sequence of moves; a full list cannot.
    """

    group_uuids: List[str]


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def _read_groups() -> List[store.SessionGroup]:
    with closing(connect(_db_path(), create=False)) as conn:
        return store.list_groups(conn)


def _to_models(groups: List[store.SessionGroup]) -> List[SessionGroupModel]:
    out: List[SessionGroupModel] = []
    for g in groups:
        style = g.style or style_store.resolve(None, g.group_uuid)
        out.append(
            SessionGroupModel(
                group_uuid=g.group_uuid,
                name=g.name,
                position=g.position,
                members=list(g.members),
                member_session_uuids=list(g.member_session_uuids),
                colour=style.colour,
                gradient=style.gradient,
                animation=style.animation,
                style_source=style.source,
                icon=style.icon,
            )
        )
    return out


@router.get("", response_model=SessionGroupsResponse, dependencies=[Depends(require_auth)])
async def list_session_groups() -> SessionGroupsResponse:
    """Every group and its membership, or an explicit CANNOT DETERMINE.

    Description: THE READ THE SIDEBAR MAKES ON EVERY POLL. Returns 200 in
      both outcomes on purpose - see the module docblock. An unreadable
      group table must leave the conversation list working, and a 503
      here would take the whole panel down over a feature the user may
      not even be using.
    Inputs: none.
    Output: SessionGroupsResponse.
    """
    path = _db_path()
    if not path.exists():
        return SessionGroupsResponse(
            status=STATUS_UNAVAILABLE,
            groups=[],
            detail="datastore has not been created yet",
        )
    try:
        groups = await run_in_threadpool(_read_groups)
    except (DatastoreUnreadableError, store.GroupsUnavailable) as exc:
        logger.info("session_groups_unavailable", reason=str(exc))
        return SessionGroupsResponse(
            status=STATUS_UNAVAILABLE, groups=[], detail=str(exc)
        )
    except OSError as exc:
        logger.warning("session_groups_read_failed", error=str(exc))
        return SessionGroupsResponse(
            status=STATUS_UNAVAILABLE, groups=[], detail=str(exc)
        )
    return SessionGroupsResponse(status=STATUS_OK, groups=_to_models(groups))


async def _write(request: Request, operation, *args, **kwargs):
    """Run one store write on a worker thread, translate its failures, announce it.

    Description: THE ONE PLACE EVERY WRITE'S ERRORS ARE MAPPED, so a new
      endpoint cannot invent a different status code for the same
      condition. Unlike the read above, an unavailable datastore is a
      503: a write that could not happen must never answer 200, because
      a silently-dropped assignment is a group the user watched
      themselves make that is gone after a reload.
      A write that landed publishes ``sessions.changed`` with reason
      ``groups`` on ``/ws/events``, so every other browser re-reads the
      groups at once instead of at its next name change (issue #645).
    Inputs: request (Request) - for the app's event hub.
      operation (callable) - takes a live connection first.
      args, kwargs - passed through after the connection.
    Output: whatever ``operation`` returns.
    Raises: HTTPException - 400 invalid name or unknown icon id
      (``code: unknown_icon``), 404 no such group,
      409 group limit reached OR a tmux name with no stored session,
      503 datastore or icon registry unavailable.
    """

    def _run():
        with closing(connect(_db_path(), create=False)) as conn:
            return operation(conn, *args, **kwargs)

    try:
        result = await run_in_threadpool(_run)
    except style_store.GroupIconUnknown as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})
    except icon_registry.IconRegistryUnavailable as exc:
        detail = {"code": icon_registry.UNAVAILABLE_CODE, "message": str(exc)}
        raise HTTPException(status_code=503, detail=detail)
    except store.GroupNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except store.GroupNameInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except store.GroupLimitReached as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except store.SessionNotStored as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (DatastoreUnreadableError, store.GroupsUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except store.SessionGroupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        logger.warning("session_groups_write_failed", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))
    session_change_notice.publish(
        request.app.state, session_change_notice.build_structural_notice("groups")
    )
    return result


@router.post("", response_model=SessionGroupsResponse, dependencies=[Depends(require_auth)])
async def create_session_group(body: CreateGroupRequest, request: Request) -> SessionGroupsResponse:
    """Create a group and return the whole list.

    Description: returns the FULL list rather than just the new group, so
      the client re-renders from one authoritative payload instead of
      splicing a row into a list it already held and hoping the two
      agree. Every write endpoint here does the same.
    Raises: HTTPException 400 (bad name), 409 (limit), 503.
    """
    await _write(request, store.create_group, body.name)
    return await list_session_groups()


@router.patch(
    "/{group_uuid}",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def rename_session_group(
    group_uuid: str, body: RenameGroupRequest, request: Request
) -> SessionGroupsResponse:
    """Rename a group. Membership and position are untouched.

    Raises: HTTPException 400 (bad name), 404, 503.
    """
    await _write(request, store.rename_group, group_uuid, body.name)
    return await list_session_groups()


@router.put(
    "/{group_uuid}/style",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def set_session_group_style(
    group_uuid: str, body: StyleRequest, request: Request
) -> SessionGroupsResponse:
    """Set a group's colour, gradient and heading animation (issue #694).

    Description: the write behind the "colour" item in a group's kebab in
      the agents drawer. Replaces the whole style in one row, so a picker
      can never leave half of an earlier choice behind. Name, membership
      and position are untouched.
    Inputs: group_uuid (str), body (StyleRequest).
    Output: SessionGroupsResponse - the whole list, like every group write.
    Raises: HTTPException 400 (a key the palette does not carry), 404, 503.
    Example: PUT /api/v1/session-groups/<uuid>/style
      {"colour": "teal", "gradient": "tide", "animation": "shimmer"}
    """
    await _write(
        request, store.set_group_style, group_uuid,
        body.colour, body.gradient, body.animation,
    )
    return await list_session_groups()


class DeleteGroupResponse(SessionGroupsResponse):

    freed: int = Field(
        default=0, description="Memberships cleared; those sessions are ungrouped"
    )


@router.delete(
    "/{group_uuid}",
    response_model=DeleteGroupResponse,
    dependencies=[Depends(require_auth)],
)
async def delete_session_group(group_uuid: str, request: Request) -> DeleteGroupResponse:
    """Delete a group. ITS CONVERSATIONS ARE NOT DELETED.

    Description: the members become ungrouped and render in OTHER from
      the next paint. See ``session_group_store.delete_group`` - the
      membership rows go with the group both explicitly and by
      ``ON DELETE CASCADE``, and neither table holds a reference to a
      conversation that could cascade into one.
    Raises: HTTPException 404, 503.
    """
    freed = await _write(request, store.delete_group, group_uuid)
    listed = await list_session_groups()
    return DeleteGroupResponse(
        status=listed.status,
        groups=listed.groups,
        detail=listed.detail,
        freed=int(freed),
    )


@router.post(
    "/assign",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def assign_session_group(body: AssignRequest, request: Request) -> SessionGroupsResponse:
    """File one session - or one saved Layout - into a group, or return it to ungrouped.

    Description: the single write behind ALL THREE ways to move a
      session - the pointer drag, the row menu's group picker, and the
      keyboard picker - so they cannot come to mean different things.
      A tmux name this datastore holds NO sessions row for is a 409, not
      a silent success: since v24 the membership is keyed on
      ``sessions.session_uuid``, so a name with no row behind it has no
      durable identity to be filed under. Answering 200 would show the
      user a group he made that is gone after a reload.

      A LAYOUT (issue #831) TAKES THE SAME ROUTE under ``layout_uuid``
      instead of ``tmux_name`` - a saved Layout is not a session and has
      no tmux name to resolve, so it is filed by its own uuid through
      ``store.assign_layout``.
    Raises: HTTPException 400 (empty/both/neither of tmux_name and
      layout_uuid), 404 (no such group), 409 (the name resolves to no
      stored session), 503.
    """
    if bool(body.tmux_name) == bool(body.layout_uuid):
        raise HTTPException(
            status_code=400,
            detail="exactly one of tmux_name or layout_uuid is required",
        )
    if body.layout_uuid:
        await _write(request, store.assign_layout, body.layout_uuid, body.group_uuid)
    else:
        await _write(request, store.assign, body.tmux_name, body.group_uuid)
    return await list_session_groups()


@router.post(
    "/{group_uuid}/order",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def reorder_group_members(
    group_uuid: str, body: MemberOrderRequest, request: Request
) -> SessionGroupsResponse:
    """Rewrite the order of the conversations INSIDE one group.

    Description: durable, shared and stored, unlike the per-device
      fallback sort it replaces for grouped rows. Takes the whole order
      rather than a move-one-step delta for the same reason the group
      order does - a delta lets the client and the database disagree
      about the result of a sequence of moves.
    Raises: HTTPException 404 (no such group), 503.
    """
    await _write(request, store.set_member_order, group_uuid, body.session_uuids)
    return await list_session_groups()


@router.post(
    "/order",
    response_model=SessionGroupsResponse,
    dependencies=[Depends(require_auth)],
)
async def reorder_session_groups(body: ReorderRequest, request: Request) -> SessionGroupsResponse:
    """Rewrite the group order from a full list of uuids.

    Raises: HTTPException 404 (a uuid naming no group), 503.
    """
    await _write(request, store.set_group_order, body.group_uuids)
    return await list_session_groups()
