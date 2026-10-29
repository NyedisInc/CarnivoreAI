"""API routes for saved Layouts: named groups of terminal sessions (issue #424).

Deliberately thin, in the ``session_groups_routes.py`` pattern: request and
response shape, auth, error translation and the connection dance. Every
rule about what a Layout IS lives in ``src/core/layouts/store.py``.

EVERY USER ACTION IS ONE ROUTE (decision D11, the API-first rule), so the
MCP wrapper (#152) is one thin adapter per route:

  GET    /layouts                         every Layout (200 even when unreadable)
  POST   /layouts                         create; idempotent on source_key
  PATCH  /layouts/{uuid}                  rename
  PUT    /layouts/{uuid}/shape            replace the shape (expected_revision)
  PUT    /layouts/{uuid}/style            set colour, gradient, animation (#821)
  POST   /layouts/{uuid}/members          add a member
  DELETE /layouts/{uuid}/members/{suuid}  remove a member
  DELETE /layouts/{uuid}                  delete; never touches a session
  PUT    /layouts/order                   drawer order
  PUT    /layouts/{uuid}/active           renew the in-memory active lease
  PUT    /layouts/{uuid}/members/{suuid}/broadcast  a member's broadcast toggle
  POST   /layouts/{uuid}/broadcast        send one line plus Enter to the toggled-on
                                          live members (``layouts/broadcast.py``)

ERRORS carry ``{"code", "detail"}`` so a client branches on the code, never
on prose: 400 ``layout_name_invalid`` / ``layout_shape_invalid`` /
``layout_too_few_members`` / ``layout_style_invalid``; 404
``layout_not_found``; 409 ``layout_name_taken`` / ``layout_limit`` /
``member_unresolved`` (with ``unresolved``) / ``layout_stale`` (with
``current``, the Layout as stored); 503 ``layouts_unavailable`` when the
write could not happen, never a cheerful 200 for a Layout that is not
there after a reload.

A write that landed publishes ``sessions.changed`` with reason ``layouts``
on ``/ws/events``, so every other browser re-reads at once. A lease renewal
changes no data and publishes nothing.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any, Callable, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core.layouts import style as style_store
from src.core.layouts import broadcast as layout_broadcast
from src.core.layouts import store as store
from src.core import resource_push, session_change_notice
from src.core.resource_push import topics as resource_topics
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.api import peer_auth
from src.core.federation import peer_layout_lease, peer_links
from src.core.layouts.lease import LEASES
from src.models.layouts import (
    AddMemberRequest,
    BroadcastMemberResult,
    BroadcastRequest,
    BroadcastResponse,
    CreateLayoutRequest,
    LayoutActiveResponse,
    LayoutMemberModel,
    LayoutModel,
    LayoutOrderRequest,
    LayoutsResponse,
    LayoutStyleRequest,
    LayoutWriteResponse,
    MemberBroadcastRequest,
    RenameLayoutRequest,
    ShapeRequest,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/layouts", tags=["layouts"])

NOTICE_REASON = "layouts"

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def to_model(layout: store.SavedLayout) -> LayoutModel:
    return LayoutModel(
        layout_uuid=layout.layout_uuid, name=layout.name, position=layout.position,
        shape=layout.shape, revision=layout.revision, source_key=layout.source_key,
        members=[_member(m) for m in layout.members],
        created_at=layout.created_at, updated_at=layout.updated_at,
        colour=layout.colour, gradient=layout.gradient, animation=layout.animation,
    )


def _member(member: store.LayoutMember) -> LayoutMemberModel:
    return LayoutMemberModel(session_row_id=member.session_row_id,
                             session_uuid=member.session_uuid, position=member.position,
                             broadcast=member.broadcast)


def _to_write(result: store.WriteResult) -> LayoutWriteResponse:
    return LayoutWriteResponse(
        layout=to_model(result.layout) if result.layout is not None else None,
        deleted=result.deleted,
        survivor=_member(result.survivor) if result.survivor is not None else None,
        created=result.created,
    )


def _error(status: int, code: str, detail: str, **extra: Any) -> HTTPException:
    body: Dict[str, Any] = {"code": code, "detail": detail}
    body.update(extra)
    return HTTPException(status_code=status, detail=body)


def _run(operation: Callable, *args: Any, **kwargs: Any) -> Any:
    with closing(connect(_db_path(), create=False)) as conn:
        return operation(conn, *args, **kwargs)


async def _write(request: Request, operation: Callable, *args: Any, **kwargs: Any) -> Any:
    try:
        result = await run_in_threadpool(_run, operation, *args, **kwargs)
    except store.LayoutNotFound as exc:
        raise _error(404, "layout_not_found", str(exc))
    except store.LayoutNameInvalid as exc:
        raise _error(400, "layout_name_invalid", str(exc))
    except store.LayoutShapeInvalid as exc:
        raise _error(400, "layout_shape_invalid", str(exc))
    except style_store.LayoutStyleInvalid as exc:
        raise _error(400, "layout_style_invalid", str(exc))
    except store.LayoutTooFewMembers as exc:
        raise _error(400, "layout_too_few_members", str(exc))
    except store.LayoutNameTaken as exc:
        raise _error(409, "layout_name_taken", str(exc))
    except store.LayoutLimitReached as exc:
        raise _error(409, "layout_limit", str(exc))
    except store.MemberUnresolved as exc:
        raise _error(409, "member_unresolved", str(exc), unresolved=exc.unresolved)
    except store.LayoutStale as exc:
        raise _error(409, "layout_stale", str(exc),
                     current=to_model(exc.current).model_dump(mode="json"))
    except (DatastoreUnreadableError, store.LayoutsUnavailable,
            layout_broadcast.BroadcastUnavailable) as exc:
        raise _error(503, "layouts_unavailable", str(exc))
    except OSError as exc:
        logger.warning("layouts_write_failed", error=str(exc))
        raise _error(503, "layouts_unavailable", str(exc))
    session_change_notice.publish(
        request.app.state, session_change_notice.build_structural_notice(NOTICE_REASON)
    )
    resource_push.notify(resource_topics.LAYOUTS)
    return result


@router.get("", response_model=LayoutsResponse, dependencies=[Depends(require_auth)])
async def list_layouts() -> LayoutsResponse:
    """Every Layout in drawer order, or an explicit CANNOT DETERMINE.

    Description: 200 in both outcomes, like the groups read: an unreadable
      Layout table must leave the drawer working.
    Output: LayoutsResponse.
    """
    if not _db_path().exists():
        return LayoutsResponse(status=STATUS_UNAVAILABLE, detail="datastore has not been created yet")
    try:
        layouts: List[store.SavedLayout] = await run_in_threadpool(_run, store.list_layouts)
    except (DatastoreUnreadableError, store.LayoutsUnavailable, OSError) as exc:
        logger.info("layouts_unavailable", reason=str(exc))
        return LayoutsResponse(status=STATUS_UNAVAILABLE, detail=str(exc))
    return LayoutsResponse(status=STATUS_OK, layouts=[to_model(l) for l in layouts])


@router.post("", response_model=LayoutWriteResponse, dependencies=[Depends(require_auth)])
async def create_layout(body: CreateLayoutRequest, request: Request) -> LayoutWriteResponse:
    """Create a Layout from a name and a shape; members are derived from the shape.

    Description: a repeated ``source_key`` answers the existing Layout with
      ``created`` false and changes nothing.
    Raises: HTTPException 400, 409 (name taken, limit, member unresolved), 503.
    Example: POST /api/v1/layouts {"name": "api + web", "shape": {...}}
    """
    result = await _write(request, store.create_layout, body.name, body.shape,
                          source_key=body.source_key)
    return _to_write(result)


@router.put("/order", response_model=LayoutsResponse, dependencies=[Depends(require_auth)])
async def reorder_layouts(body: LayoutOrderRequest, request: Request) -> LayoutsResponse:
    """Rewrite the drawer order from a full list of uuids.

    Raises: HTTPException 404 (a uuid naming no Layout), 503.
    """
    layouts = await _write(request, store.set_order, body.layout_uuids)
    return LayoutsResponse(status=STATUS_OK, layouts=[to_model(l) for l in layouts])


@router.patch("/{layout_uuid}", response_model=LayoutWriteResponse,
              dependencies=[Depends(require_auth)])
async def rename_layout(layout_uuid: str, body: RenameLayoutRequest,
                        request: Request) -> LayoutWriteResponse:
    """Rename a Layout. Shape, members and revision are untouched.

    Raises: HTTPException 400, 404, 409 (name taken), 503.
    """
    return _to_write(await _write(request, store.rename_layout, layout_uuid, body.name))


@router.put("/{layout_uuid}/style", response_model=LayoutWriteResponse,
            dependencies=[Depends(require_auth)])
async def set_layout_style(layout_uuid: str, body: LayoutStyleRequest,
                           request: Request) -> LayoutWriteResponse:
    """Set a Layout's colour, gradient and heading animation (issue #821).

    Description: the write behind the "colour" item in a Layout row's
      kebab - the SAME picker, palette and validator a hand-made group's
      colour already uses. Replaces the whole style in one row, so a
      picker can never leave half of an earlier choice behind. Name,
      shape, members and revision are untouched.
    Inputs: layout_uuid (str), body (LayoutStyleRequest).
    Output: LayoutWriteResponse - the Layout after the write.
    Raises: HTTPException 400 (a key the palette does not carry), 404, 503.
    Example: PUT /api/v1/layouts/<uuid>/style
      {"colour": "teal", "gradient": "tide", "animation": "shimmer"}
    """
    return _to_write(await _write(
        request, store.set_layout_style, layout_uuid,
        body.colour, body.gradient, body.animation,
    ))


@router.put("/{layout_uuid}/shape", response_model=LayoutWriteResponse,
            dependencies=[Depends(require_auth)])
async def set_layout_shape(layout_uuid: str, body: ShapeRequest,
                           request: Request) -> LayoutWriteResponse:
    """Replace a Layout's shape at ``expected_revision``.

    Description: a stale revision is a 409 ``layout_stale`` carrying the
      stored Layout (adopt it and replay once). A shape showing one session
      deletes the Layout and answers ``deleted`` with that ``survivor``.
    Raises: HTTPException 400, 404, 409 (stale, member unresolved), 503.
    """
    return _to_write(await _write(request, store.set_shape, layout_uuid, body.shape,
                                  body.expected_revision))


@router.post("/{layout_uuid}/members", response_model=LayoutWriteResponse,
             dependencies=[Depends(require_auth)])
async def add_layout_member(layout_uuid: str, body: AddMemberRequest,
                            request: Request) -> LayoutWriteResponse:
    """Add a session as the last tab of the Layout's first terminal component.

    Raises: HTTPException 404, 409 (stale, member unresolved), 503.
    """
    return _to_write(await _write(
        request, store.add_member, layout_uuid, session_uuid=body.session_uuid,
        session_row_id=body.session_row_id, expected_revision=body.expected_revision,
    ))


@router.delete("/{layout_uuid}/members/{session_uuid}", response_model=LayoutWriteResponse,
               dependencies=[Depends(require_auth)])
async def remove_layout_member(layout_uuid: str, session_uuid: str, request: Request,
                               expected_revision: int | None = None) -> LayoutWriteResponse:
    """Take a session off a Layout. The session keeps running.

    Description: at one member left the Layout is deleted and the answer is
      ``{"deleted": true, "survivor": {...}}``.
    Raises: HTTPException 404, 409 (stale, not a member), 503.
    """
    return _to_write(await _write(request, store.remove_member, layout_uuid, session_uuid,
                                  expected_revision=expected_revision))


@router.delete("/{layout_uuid}", response_model=LayoutWriteResponse,
               dependencies=[Depends(require_auth)])
async def delete_layout(layout_uuid: str, request: Request) -> LayoutWriteResponse:
    """Delete a Layout. NO SESSION IS KILLED, CLOSED OR DELETED.

    Raises: HTTPException 404, 503.
    """
    await _write(request, store.delete_layout, layout_uuid)
    LEASES.release(layout_uuid)
    return LayoutWriteResponse(layout=None, deleted=True)


@router.put("/{layout_uuid}/active", response_model=LayoutActiveResponse,
            dependencies=[Depends(require_auth)])
async def renew_layout_lease(layout_uuid: str) -> LayoutActiveResponse:
    """Mark a Layout open on this device for the next ``lease_seconds``.
    """
    try:
        await run_in_threadpool(_run, store.get_layout, layout_uuid)
    except store.LayoutNotFound as exc:
        raise _error(404, "layout_not_found", str(exc))
    except (DatastoreUnreadableError, store.LayoutsUnavailable, OSError) as exc:
        raise _error(503, "layouts_unavailable", str(exc))
    LEASES.renew(layout_uuid)
    await peer_layout_lease.forward_lease(layout_uuid, peer_auth.open_db, peer_links.LINKS)
    return LayoutActiveResponse(layout_uuid=layout_uuid, lease_seconds=int(LEASES.lease_seconds))


@router.put("/{layout_uuid}/members/{session_uuid}/broadcast", response_model=LayoutWriteResponse,
            dependencies=[Depends(require_auth)])
async def set_member_broadcast(layout_uuid: str, session_uuid: str, body: MemberBroadcastRequest,
                               request: Request) -> LayoutWriteResponse:
    """Turn one member's broadcast toggle on or off (issue #837).

    Description: Layout state, so every device and an MCP client see the
      same toggle; absent means on. Not a shape change: ``revision`` does
      not move. Publishes ``sessions.changed`` reason ``layouts``.
    Raises: HTTPException 404, 409 ``member_unresolved`` (not a member), 503.
    Example: PUT /api/v1/layouts/<uuid>/members/<session_uuid>/broadcast {"enabled": false}
    """
    return _to_write(await _write(request, layout_broadcast.set_member_broadcast,
                                  layout_uuid, session_uuid, body.enabled))


async def _live_listing(request: Request) -> List[Any]:
    from src.core import single_flight

    manager = request.app.state.session_manager
    flight = single_flight.flight_on(manager, single_flight.SESSION_LIST_FLIGHT_ATTR,
                                     single_flight.SESSION_LIST_FLIGHT_NAME)
    return await flight.run(manager.list_session_infos)


@router.post("/{layout_uuid}/broadcast", response_model=BroadcastResponse,
             dependencies=[Depends(require_auth)])
async def broadcast_to_layout(layout_uuid: str, body: BroadcastRequest,
                              request: Request) -> BroadcastResponse:
    """Send one line plus Enter to every live member whose toggle is on (issue #837).

    Description: one result per member, in member order: ``sent``,
      ``skipped_off``, ``skipped_not_live``, or ``failed`` with a ``code``
      (``pane_dialog_open``, ``paste_not_settled``, ``paste_unsupported``,
      ``send_failed``). A refused text sends nothing anywhere. The text is
      never logged, only its length. Changes no stored data, so it
      publishes nothing.
    Raises: HTTPException 400 ``broadcast_text_empty`` /
      ``broadcast_text_too_large`` / ``broadcast_text_control``; 404; 503.
    Example: POST /api/v1/layouts/<uuid>/broadcast {"text": "git status"}
    """
    try:
        text = layout_broadcast.check_text(body.text)
    except layout_broadcast.BroadcastRefused as exc:
        logger.info("layout_broadcast_refused", layout_uuid=layout_uuid, code=exc.code)
        raise _error(400, exc.code, str(exc))
    try:
        layout = await run_in_threadpool(_run, store.get_layout, layout_uuid)
    except store.LayoutNotFound as exc:
        raise _error(404, "layout_not_found", str(exc))
    except (DatastoreUnreadableError, store.LayoutsUnavailable, OSError) as exc:
        raise _error(503, "layouts_unavailable", str(exc))
    infos = await _live_listing(request)
    from src.api.layout_skills_routes import skill_rewriter
    outcomes = await layout_broadcast.broadcast(
        layout, text, infos=infos, backend_for=request.app.state.services.registry.get_backend,
        rewrite=await skill_rewriter(request, layout, infos))
    results = [BroadcastMemberResult(session_row_id=o.session_row_id, session_uuid=o.session_uuid,
                                     status=o.status, code=o.code) for o in outcomes]
    return BroadcastResponse(
        layout_uuid=layout_uuid, results=results,
        sent=sum(1 for o in outcomes if o.status == layout_broadcast.SENT),
        skipped=sum(1 for o in outcomes if o.status in (layout_broadcast.SKIPPED_OFF,
                                                         layout_broadcast.SKIPPED_NOT_LIVE)),
        failed=sum(1 for o in outcomes if o.status == layout_broadcast.FAILED),
    )
