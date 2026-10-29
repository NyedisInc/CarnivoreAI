
from __future__ import annotations

import contextlib
import sqlite3
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Union

import structlog
from fastapi import Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from src.cplugs.huddle import client_writes, item_marker, completed_view, old_routes, focus, held, lane, lineage, lists_read, owner_read, push_delta, question_cancel, swarm_tell, progress, reply, review, schedule, scheduled, service, slim, steps, send_queue, sending
from src.cplugs.huddle.groups import UNSET
from src.cplugs.huddle.rules import ALL_LIST, JOE, OPEN, TaskManagerError, check_list_key
from src.cplugs.sdk import CplugContext, CplugSchemaError, cplug_context, cplug_router
from src.cplugs.sdk.session_tasks import tasks_for, watch_and_reader

logger = structlog.get_logger()
router = cplug_router("huddle")
Ctx = Depends(cplug_context("huddle"))


class AddItemRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    text: str
    note: str = ""
    kind: str = ""
    group: Optional[StrictInt] = None
    state: Optional[str] = None
    review_description: Optional[str] = None
    review_summary: Optional[str] = None
    review_link: Optional[str] = None
    review_where: Optional[str] = None
    review_action: Optional[str] = None
    title: Optional[str] = None
    fire_at: Optional[str] = None
    repeat: Optional[Union[Dict[str, Any], str]] = None


class UpdateItemRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    expected_revision: Optional[StrictInt] = None
    text: Optional[str] = None
    note: Optional[str] = None
    approved: Optional[StrictBool] = None
    state: Optional[str] = None
    kind: Optional[str] = None
    review_description: Optional[str] = None
    review_summary: Optional[str] = None
    review_link: Optional[str] = None
    review_where: Optional[str] = None
    review_action: Optional[str] = None
    review_checks: Optional[List[str]] = None
    title: Optional[str] = None
    fire_at: Optional[str] = None
    repeat: Optional[Union[Dict[str, Any], str]] = None
    paused: Optional[StrictBool] = None
    marker: Optional[str] = None
    flag_color: Optional[str] = None
    flag_reason: Optional[str] = None
    github_issue: Optional[str] = None


class OrderRequest(BaseModel):
    """The whole list's new drag order, top first."""

    model_config = ConfigDict(extra="forbid")
    ids: List[StrictInt]
    expected_revision: StrictInt


class MessageRequest(BaseModel):
    """One reply on an item's thread: ``text`` and/or ``files`` (ids of files uploaded to this item; no text is allowed with files)."""

    model_config = ConfigDict(extra="forbid")
    text: str = ""
    files: List[str] = []
    client_id: Optional[str] = None
    retry_age_s: Optional[float] = Field(None, ge=0, le=client_writes.MAX_RETRY_AGE_S)
    ack_through: Optional[StrictInt] = Field(None, ge=0)
    kind: Literal["reply", "comment"] = "reply"


class FocusRequest(BaseModel):
    """Point at rows of one list (``items``, opening ``open``), or ``clear`` the focus."""

    model_config = ConfigDict(extra="forbid")
    list: Optional[str] = None
    items: List[StrictInt] = []
    open: Optional[StrictInt] = None
    clear: StrictBool = False


class MoveRequest(BaseModel):
    """The list an item moves to: ``all`` or a live project's id; ``group`` (when sent) a group of that list, null ungrouped."""

    model_config = ConfigDict(extra="forbid")
    list: str
    group: Optional[StrictInt] = None


class GroupCreateRequest(BaseModel):
    """A new named group of one list."""

    model_config = ConfigDict(extra="forbid")
    name: str


class GroupUpdateRequest(BaseModel):
    """A group change; every field optional. ``position`` is its 0-based place among the list's groups."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    position: Optional[StrictInt] = None
    folded: Optional[StrictBool] = None


class GroupFoldManyRequest(BaseModel):
    """Fold (true) or unfold (false) every named group in ``ids`` at once."""

    model_config = ConfigDict(extra="forbid")
    ids: List[StrictInt]
    folded: StrictBool


class ItemGroupRequest(BaseModel):
    """Which group an item sits in (null: ungrouped) and its 0-based place there (absent: the bottom)."""

    model_config = ConfigDict(extra="forbid")
    group: Optional[StrictInt]
    index: Optional[StrictInt] = None
    expected_revision: Optional[StrictInt] = None


class SendManyRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    lists: List[str]
    targets: Dict[str, str] = {}
    queue: bool = False


class SendTargetRequest(BaseModel):
    """The agent a list's tell goes to: a candidate's session id, or null to go back to the derived default."""

    model_config = ConfigDict(extra="forbid")
    target: Optional[str] = None


class SendRequest(BaseModel):
    """Which session to tell; absent takes the list's default (the last huddle caller), never an arbitrary one."""

    model_config = ConfigDict(extra="forbid")
    target: Optional[str] = None


def refusal(exc: TaskManagerError) -> HTTPException:
    body: Dict[str, Any] = {"code": exc.code, "detail": str(exc)}
    current = getattr(exc, "current", None)
    if current is not None:
        body["current"] = current
    reason = getattr(exc, "reason", None)
    if reason is not None:
        body["reason"] = reason
    blocking = getattr(exc, "blocking", None)
    if blocking is not None:
        body["blocking"] = blocking
    return HTTPException(status_code=exc.status, detail=body)


@contextlib.contextmanager
def mapped_errors() -> Iterator[None]:
    try:
        yield
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    except (CplugSchemaError, sqlite3.Error, OSError) as exc:
        logger.warning("task_manager_store_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail={"code": "huddle_unavailable", "detail": str(exc)}) from exc


async def run_store(call: Callable[[], Any]) -> Any:
    with mapped_errors():
        return await run_in_threadpool(call)


async def known_list(ctx: CplugContext, key: str) -> tuple[str, Optional[str]]:
    try:
        check_list_key(key)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    if key == ALL_LIST:
        return key, None
    names = await run_in_threadpool(service.project_names, ctx)
    if key not in names:
        raise HTTPException(status_code=404, detail={"code": "task_list_unknown", "detail": f"no project {key}"})
    return key, names[key]


@router.get("/lists")
async def get_lists(include_swarm: bool = Query(False), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    marker = push_delta.marker()
    body = await run_store(lambda: lists_read.build_lists(ctx, hide_swarm=lane.hides_swarm(None, include_swarm)))
    return {**body, **marker}


@router.get("/aggregate")
async def get_aggregate(threads: bool = Query(False), hide_completed: bool = Query(False), include_swarm: bool = Query(False),
                        live_only: bool = Query(False), ctx: CplugContext = Ctx) -> JSONResponse:
    """Every list that holds items as a group, in each list's own priority order.
    """
    marker = push_delta.marker()
    body = await run_store(lambda: service.store(ctx).aggregate(hide_swarm=lane.hides_swarm(None, include_swarm), live_only=live_only))
    names = await run_in_threadpool(service.project_names, ctx)
    groups = service.aggregate_groups(body, names)
    groups = groups if threads else slim.slim_groups(groups)
    await owner_read.annotate_tagged(ctx, [item for group in groups for item in group["items"]])
    return JSONResponse({"cursor": body["cursor"], "groups": completed_view.apply_groups(groups) if hide_completed else groups, **marker})


@router.get("/items/{item_id}")
async def get_item(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One live item with its whole thread (the aggregate's slim threads are completed from it). 404 ``task_manager_not_found``."""
    return await run_store(lambda: service.store(ctx).item(item_id))


@router.get("/scheduled")
async def get_scheduled(list_key: Optional[str] = Query(None, alias="list"), paused: Optional[bool] = None,
                        ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Every item that carries a schedule, across all lists (``scheduled.py``, the one rule the Automations tab and ``task_manager_schedules_list`` share).

    Inputs: list (a project id, ``all`` or ``agent:<id>``; absent = every list); paused (true/false; absent = both).
    Output: {cursor, groups (the aggregate's shape, scheduled items only), schedules (one row per item, soonest first)}.
    """
    try:
        return await scheduled.build(ctx, list_key, paused)
    except TaskManagerError as exc:
        raise refusal(exc) from exc


@router.get("/lists/{key}")
async def get_list(key: str, hide_completed: bool = Query(False), include_swarm: bool = Query(False), live_only: bool = Query(False),
                   ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One list's items in drag order, each with its thread; hide_completed sends completed items as placeholders (``completed_view.py``).

    live_only - true leaves out the completed items and their threads and adds ``done_count``; they come from ``GET /lists/{key}/done``.
    """
    try:
        check_list_key(key)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    marker = push_delta.marker()
    body = await run_store(lambda: service.store(ctx).list_items(key, hide_swarm=lane.hides_swarm(key, include_swarm), live_only=live_only))
    return {**(completed_view.apply_body(body) if hide_completed else body), **marker}


@router.post("/lists/{key}/items")
async def add_item(key: str, body: AddItemRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    key, _name = await known_list(ctx, key)
    return await run_store(lambda: service.store(ctx).add(
        key, body.text, actor=JOE, note=body.note, kind=body.kind, group=body.group,
        review_fields=body.model_dump(include=set(review.FIELDS)), title=body.title,
        fire_at=body.fire_at, repeat=body.repeat, state=body.state))


@router.put("/lists/{key}/order")
async def put_order(key: str, body: OrderRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Set a list's drag order (409 when it moved since it was read)."""
    try:
        check_list_key(key)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    return await run_store(lambda: service.store(ctx).reorder(
        key, body.ids, actor=JOE, expected_revision=body.expected_revision))


@router.post("/lists/{key}/remove-completed")
async def remove_completed(key: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    try:
        check_list_key(key)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    return await run_store(lambda: service.store(ctx).remove_completed(key, actor=JOE))


@router.get("/changes")
async def get_changes(ctx: CplugContext = Ctx, since: int = Query(0, ge=0),
                      list_key: Optional[str] = Query(None, alias="list"), include_swarm: bool = Query(False)) -> Dict[str, Any]:
    return await run_store(lambda: service.store(ctx).changes(since, list_key, hide_swarm=lane.hides_swarm(list_key, include_swarm)))


async def decide_card(ctx: CplugContext, item: Dict[str, Any], decision: str, owner_message_ref: str = "",
                      note: str = "") -> None:
    try:
        await reply.decide_card(ctx, item, decision, owner_message_ref, note)
    except TaskManagerError as exc:
        raise refusal(exc) from exc


@router.patch("/items/{item_id}")
async def patch_item(item_id: int, body: UpdateItemRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    item = await run_store(lambda: service.store(ctx).update(
        item_id, actor=JOE, expected_revision=body.expected_revision, text=body.text, note=body.note,
        approve=body.approved, state=body.state, kind=body.kind,
        review_fields=body.model_dump(include=set(review.FIELDS)), title=body.title, fire_at=body.fire_at,
        repeat=body.repeat, paused=body.paused, marker=item_marker.from_args(body.marker, body.flag_color),
        github_issue_url=body.github_issue, review_checks=body.review_checks))
    if body.approved is True:
        try:
            await decide_card(ctx, item, "approve")
        except HTTPException:
            await run_store(lambda: service.store(ctx).update(item_id, actor=JOE, state=OPEN,
                                                              decided=lineage.Decided(lineage.CARNIVORE, lineage.SWARM_REFUSED)))
            raise
    return item


class ReviewCheckRequest(BaseModel):
    """Tick (true) or untick (false) one review check."""

    model_config = ConfigDict(extra="forbid")
    checked: StrictBool


@router.patch("/items/{item_id}/review-checks/{check_id}")
async def patch_review_check(item_id: int, check_id: str, body: ReviewCheckRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Output: the item, its ``review_checks`` list updated. 404 ``task_manager_not_found`` for an unknown item or check. The change
    rides the list topic's push; it tells no session and reads nothing.
    """
    with mapped_errors():
        return await run_store(lambda: service.store(ctx).tick_review_check(item_id, check_id, body.checked, actor=JOE))


@router.post("/items/{item_id}/run-now")
async def run_item_now(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Output: the item; its ``start_trigger`` shows the outcome (``last_error`` when the session could not be told).
    409/400 ``task_manager_invalid`` for an approved or back-burner item.
    """
    try:
        return await schedule.run_now(item_id)
    except TaskManagerError as exc:
        raise refusal(exc) from exc


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    return await run_store(lambda: service.store(ctx).delete(item_id, actor=JOE))


@router.post("/items/{item_id}/move")
async def move_item(item_id: int, body: MoveRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    A ``group`` in the body (null included) files it in that group of the target list; the same list is then allowed.
    """
    key, _name = await known_list(ctx, body.list)
    group = body.group if "group" in body.model_fields_set else UNSET
    return await run_store(lambda: service.store(ctx).move(item_id, key, actor=JOE, group=group))


@router.post("/lists/{key}/groups")
async def create_group(key: str, body: GroupCreateRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Output: the group with ``created`` (false: a live group of that name already existed and is answered).
    """
    key, _name = await known_list(ctx, key)
    return await run_store(lambda: service.groups(ctx).create(key, body.name, actor=JOE))


@router.patch("/groups/{group_id}")
async def patch_group(group_id: int, body: GroupUpdateRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Rename a group, move it among its list's groups, or fold it (a view flag). Output: the group."""
    return await run_store(lambda: service.groups(ctx).update(
        group_id, actor=JOE, name=body.name, position=body.position, folded=body.folded))


@router.post("/groups/fold")
async def fold_groups(body: GroupFoldManyRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Output: ``{folded, updated: [ids], missing: [ids]}``; an id that names no live group is listed in ``missing``.
    """
    return await run_store(lambda: service.groups(ctx).fold_many(body.ids, body.folded, actor=JOE))


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Remove a group; its items become ungrouped (never deleted). Output: {group, list, ungrouped: [ids]}."""
    return await run_store(lambda: service.groups(ctx).remove(group_id, actor=JOE))


@router.post("/items/{item_id}/group")
async def put_item_group(item_id: int, body: ItemGroupRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    return await run_store(lambda: service.groups(ctx).set_group(
        item_id, body.group, actor=JOE, index=body.index, expected_revision=body.expected_revision))


@router.post("/items/{item_id}/messages")
async def post_message(item_id: int, body: MessageRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    The one function behind it is ``reply.post_reply``, which the review board's round also calls (``docs/reviewboard.md``, slice 5).
    """
    with mapped_errors():
        store = service.store(ctx)
        return await client_writes.once(
            f"reply:{item_id}", client_writes.check_id(body.client_id), body.retry_age_s,
            run=lambda: reply.post_reply(ctx, item_id, body.text, file_ids=body.files, ack_through=body.ack_through, comment=body.kind == "comment"),
            recover=lambda since: run_store(lambda: client_writes.find_reply(store, item_id, body.text, body.files, since, body.kind)),
            ref_of=client_writes.reply_ref, replay=lambda ref: run_store(lambda: client_writes.replay_reply(store, ref)))


@router.post("/items/{item_id}/answered")
async def post_answered(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Output: the item (its status leaves ``question``). Idempotent; adds no message.
    """
    item = await run_store(lambda: service.store(ctx).mark_answered(item_id, actor=JOE))
    await decide_card(ctx, item, "answer")
    return item


@router.post("/items/{item_id}/cancel-question")
async def post_cancel_question(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Output: the item. 400 ``task_manager_invalid`` when no question is open. Leaves one note on the thread for the session.
    """
    item = await run_store(lambda: question_cancel.cancel(service.store(ctx), item_id))
    await decide_card(ctx, item, "answer")
    await send_queue.queue_owner_write(ctx, item)
    return item


class SeenRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    message: Optional[StrictInt] = None
    through: Optional[StrictInt] = Field(None, ge=0)


@router.post("/items/{item_id}/seen")
async def post_seen(item_id: int, body: Optional[SeenRequest] = None, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    message = body.message if body is not None else None
    return await run_store(lambda: service.store(ctx).mark_seen(item_id, message, body.through if body is not None else None))


@router.get("/steps")
async def get_steps(request: Request, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The steps strip's data (``steps.py``, docs/task-manager.md section 56): each working item's claiming session checklist.

    Description: reads the session tasks service (a transcript fold, one ``stat`` when nothing moved) and takes a lease on
      the session tasks watch under ``steps.WATCH_KEY``, which names ``session_tasks:huddle`` when the answer moves (push, no poll).
    Output: {lists: {list key: {items: {item id: {tasks, counts}}}}}; lists with nothing to show, codex sessions and all-complete checklists are left out.
    """
    watch, reader = watch_and_reader(request.app.state)

    async def load() -> Any:
        claims = await run_store(lambda: service.store(ctx).working_claims())
        infos = await ctx.sessions.list()
        keys = await ctx.sessions.durable_keys(infos)
        return steps.Steps(**await steps.build(claims, infos, keys, lambda info: tasks_for(info, reader)))

    return (await watch.read(steps.WATCH_KEY, load)).model_dump()


@router.get("/progress")
async def get_progress(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Every item's live worker lines. Output: {progress: {item id: [{worker, phase, note, age_s, stale}]}}; empty after a restart until a worker reports."""
    return {"progress": progress.snapshot(ctx)}


@router.get("/focus")
async def get_focus(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The rows Claude is pointing at (``huddle_focus``). Output: {focus: {seq, list, items, open, at} | None}."""
    return {"focus": focus.current(ctx)}


@router.post("/focus")
async def post_focus(body: FocusRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Point every open Task Manager view at rows of one list, or clear the focus.
    """
    if body.clear:
        return focus.clear(ctx)
    if body.list is None:
        raise HTTPException(status_code=400, detail={"code": "task_manager_invalid", "detail": "list is required unless clear"})
    key, _name = await known_list(ctx, body.list)
    return await run_store(lambda: focus.set_focus(ctx, key, body.items, body.open))


@router.get("/lists/{key}/sessions")
async def get_sessions(key: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The agent sessions "tell claude" may message for this list, the default target and why.

    Output: {list, sessions, default, reason} - ``default`` is the session that last
      called the Task Manager tools on this list (any list for "all"), else a project's only
      agent session, else None (``reason`` "pick": the picker must choose).
    """
    key, _name = await known_list(ctx, key)
    rows = await service.candidate_rows(ctx, key)
    return await run_store(lambda: service.send_choice(ctx, rows, key))


@router.put("/lists/{key}/send-target")
@router.put("/lists/{key}/tell-target", **old_routes.retired("PUT", "/lists/{key}/tell-target"))
async def set_send_target(key: str, body: SendTargetRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Pick the agent (a claude or codex session) this list's tell goes to, for every window; null forgets the pick.

    Description: tells are per LIST, so the pick is per list (``send_pick.py``): the queue pop-up's per-entry agent
      dropdown and the add box's agent select both set it. The target must be one of the list's candidates
      (``GET .../sessions``); it is stored by the session's stable key and becomes that list's default (reason
      ``picked``). The list's topic is notified, so every window re-reads it.
    Output: the new ``GET .../sessions`` body {list, sessions, default, reason}. Errors: 404 ``task_manager_no_session`` when
      the target is not a candidate of this list.
    """
    key, _name = await known_list(ctx, key)
    rows = await service.candidate_rows(ctx, key)
    chosen = next((r for r in rows if r["id"] == body.target), None) if body.target else None
    if body.target and chosen is None:
        raise HTTPException(status_code=404, detail={
            "code": "task_manager_no_session", "detail": "that session is not a claude or codex session of this list"})
    await run_store(lambda: service.store(ctx).set_send_pick(key, chosen["key"] if chosen else None))
    return await run_store(lambda: service.send_choice(ctx, rows, key))


@router.post("/lists/{key}/send")
@router.post("/lists/{key}/tell", **old_routes.retired("POST", "/lists/{key}/tell"))
async def send_claude(key: str, body: SendRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    key, name = await known_list(ctx, key)
    rows = await service.candidate_rows(ctx, key)
    if not rows and await swarm_tell.wake_if_asleep(ctx, key):
        rows = await service.candidate_rows(ctx, key)
    if not rows:
        raise HTTPException(status_code=404, detail={
            "code": "task_manager_no_session", "detail": "no claude or codex session of this list to send to"})
    choice = await run_store(lambda: service.send_choice(ctx, rows, key))
    target, reason = (body.target, "chosen") if body.target else (choice["default"], choice["reason"])
    if target is None:
        raise HTTPException(status_code=409, detail={
            "code": "task_manager_pick_session", "detail": "several sessions could take this; pick one",
            "sessions": rows})
    if target not in {r["id"] for r in rows}:
        raise HTTPException(status_code=404, detail={
            "code": "task_manager_no_session", "detail": "that session is not a claude or codex session of this list"})
    aggregate = key == service.ALL_LIST
    await send_queue.before_immediate(ctx, key, target)
    try:
        told = await sending.paste_send(ctx, run_store, key, name, rows, target, reason, aggregate=aggregate)
    except HTTPException as exc:
        outcome = sending.held_or_refused(ctx, run_store, key, name, rows, target, reason, exc, aggregate=aggregate)
        if outcome["status"] != sending.HELD:
            raise
        return outcome
    held.clear(ctx, key)
    return told


@router.get("/held")
async def get_held() -> Dict[str, Any]:
    """
    Output: {held: [{list, target, label, state: held | expired | gone | not_sent, code, reason, since, deadline}]}.
      Pushed on the ``held`` topic, so every window re-reads it.
    """
    return {"held": held.snapshot()}


@router.delete("/held/{key}")
async def delete_held(key: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Cancel a held tell, or dismiss a not-sent notice, of one list. The items stay waiting to send.

    Output: {cleared: bool, held: [...]} (the remaining entries).
    """
    cleared = held.clear(ctx, key)
    return {"cleared": cleared, "held": held.snapshot()}


@router.post("/send")
@router.post("/tell", **old_routes.retired("POST", "/tell"))
async def send_lists(body: SendManyRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Tell claude about SEVERAL lists in one press, each list into its OWN target session (docs/task-manager.md section 20).
    """
    keys = list(dict.fromkeys(body.lists))
    if not keys:
        raise HTTPException(status_code=400, detail={"code": "task_manager_invalid", "detail": "lists is required"})
    named = [await known_list(ctx, key) for key in keys]
    if body.queue:
        results = await send_queue.queue_untold(ctx, [key for key, _name in named])
        return {"results": results, "queue": send_queue.state(ctx)}
    infos = await ctx.sessions.list()
    results = [await sending.send_one_of_many(ctx, run_store, key, name, infos, body.targets.get(key),
                                              lambda target, key=key: send_queue.before_immediate(ctx, key, target)) for key, name in named]
    return {"results": results}


from src.cplugs.huddle import routes_actors, routes_artifacts, routes_ask, routes_closed, routes_closure_ops, routes_done, routes_files, routes_fork, routes_inbox, routes_lineage, routes_nudge, routes_schedule_offer, routes_sent, routes_send_queue, routes_wait  # noqa: E402,F401
from src.cplugs.huddle.roles import routes_roles  # noqa: E402,F401
