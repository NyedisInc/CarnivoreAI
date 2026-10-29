
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any, Optional

from src.cplugs.huddle import actor_log, answers as answers_wire, artifacts, batch, inbox, inbox_filing, mcp_artifact, mcp_inbox, callers, changes_view, files, flags, focus, fork as forks, from_project, github_issue, groups, held, item_marker, item_owner, kinds, lane, lean_read, lifecycle, owner_read, own_list, progress, reply_paths, review, review_checks, rich_ask, rules, schedule, scheduled, service, steer, structured, perceived_ask, title as titles, triggers, your_items
from src.cplugs.huddle import child_hold, mcp_file_remove, mcp_wait, owner_guards, question_toasts, reply_return, review_lock, schedule_offer, state_request, waits
from src.cplugs.huddle.roles import dnd_gate, mcp_lead, mcp_tags, mcp_roles, service as roles_service
from src.cplugs.huddle.rules import CLAUDE, JOE, QUESTION, TaskManagerError, TaskManagerNotFound
from src.cplugs.huddle.guide_rev import TASK_MANAGER_GUIDE_CHANGELOG, TASK_MANAGER_GUIDE_REV, guide_answer
from src.cplugs.sdk import register_guide, stale_extensions, CplugContext, AgentCaller, ToolError, ToolSpec, tool_result as _sdk_tool_result


register_guide("huddle", TASK_MANAGER_GUIDE_REV, TASK_MANAGER_GUIDE_CHANGELOG)


def tool_result(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return _sdk_tool_result(payload)
    stale = stale_extensions("huddle", TASK_MANAGER_GUIDE_REV)
    extra = {"stale_extensions": stale} if stale else {}
    return _sdk_tool_result({**payload, "guide_rev": TASK_MANAGER_GUIDE_REV, **extra})


_LIST_SCHEMA = {"type": "string", "description": "all, a project id from projects_list, agent:<id> (a Swarm agent's own thread), or mine (your session's list)."}
_KIND_SCHEMA = {"type": "string", "enum": list(rules.KINDS) + [""],
                "description": "question (needs the owner's call), done, waiting, or info. Empty string clears."}
_ITEM_SCHEMA = {"type": "integer", "description": "An item id from task_manager_tasks_list or task_manager_changes (not its number)."}
_NOTIFY_SCHEMA = {"notify": {"type": "boolean", "description": "reply, on an info only. true marks the item unread and badges his tab; it asks nothing. Default false."}}
_ACTION_SCHEMA = {"type": "string", "enum": list(review.ACTIONS),
                  "description": "What the owner must do: tick (check and tick), push (tick to push), answer, read, none."}
_REVIEW_SCHEMAS = {
    "review_description": {"type": "string", "maxLength": review.MAX_DESCRIPTION, "description": "What to review; renders markdown. '' clears."},
    "review_summary": {"type": "string", "maxLength": review.MAX_SUMMARY,
                       "description": "ONE plain line (about 140 characters) above the folded description; set it when review_description is long. '' clears."},
    "review_link": {"type": "string", "maxLength": review.MAX_LINK, "description": "An in-app path starting with / or an http(s) URL, only if one helps. '' clears."},
    "review_where": {"type": "string", "maxLength": review.MAX_WHERE, "description": "A short place name like 'Settings, Huddle tab', not a click path. '' clears."},
    "review_action": {**_ACTION_SCHEMA, "description": "What the owner owes: tick, push, answer, read, none. Unset: tick. '' clears."},
}
_REVIEW_CHECKS_SCHEMA = {
    review_checks.FIELD: {"type": "array", "items": {"type": "string"}, "description": "With review: a checklist the owner ticks. Replaces the list; [] clears."},
}
_TITLE_SCHEMA = {
    titles.FIELD: {"type": "string", "maxLength": titles.MAX_TITLE,
                   "description": f"A short descriptive title (at most {titles.MAX_TITLE} characters) the row shows in place of the text. Any item. '' clears."},
}
_PERCEIVED_ASK_SCHEMA = {
    perceived_ask.FIELD: {"type": "string", "maxLength": perceived_ask.MAX_PERCEIVED_ASK,
                          "description": f"One line (at most {perceived_ask.MAX_PERCEIVED_ASK} characters): what you understood the owner to want. Any item. '' clears."},
}
_MARKER_SCHEMA = {
    item_marker.FIELD: {"type": "string", "enum": [*item_marker.MARKERS, ""],
                        "description": "Mark the task for the owner with one solid shape (one per task, last write wins; it shows in the row's margin). '' clears. Replaces flag_color."},
}
_LEGACY_FLAG_ARGS = frozenset({"flag_color", "flag_reason"})
_GITHUB_ISSUE_SCHEMA = {
    github_issue.FIELD: {"type": "string", "maxLength": github_issue.MAX_URL,
                         "description": "The GitHub issue this item tracks: a full https://github.com/<owner>/<repo>/issues/<number> URL. '' clears."},
}
_FIRE_AT_SCHEMA = {
    "fire_at": {"type": "string", "maxLength": 40,
                "description": "Send to the item's session when it is due: ISO 8601 WITH a UTC offset, in the future, e.g. 2026-10-06T15:00:00-04:00; the offset fixes the instant, whatever the app's configured time zone. '' cancels."},
}
FORMAT_HINT = ("Markdown renders: **bold**, *italic*, `code`, ``` fences (drawn as a command area with a copy button), - or 1. lists (one nested level), # and ## headings, "
               "[text](https://...) links, pipe tables. HTML shows as text.")
FORMAT_USE = ("FORMAT DATA: use a pipe table (| a | b |, |---|---|) to compare things or list rows; a ```kv fence of key: value lines "
              "for a few labeled facts (branch, status, count). Prose and short lists otherwise.")
TYPED_HINT = ("Typed question {id, type, prompt, required?, help?}: type yes_no (labels [yes, no]? recommend {value: true or false, reason}?), "
              "single or multi (options [{id, label, recommended?, reason?}], other?: true adds a free-text box, multi: min?, max?; a single may carry command {text, lang?} or a string: a copyable command area above the options, which then draw as pills, e.g. a handoff command with pills ran it, failed, skip), "
              "rank (options, recommend {order: [every option id], reason}?), short_text or long_text (placeholder?, max_length?, recommend {text, reason}?). "
              "Name ids (i54, fold): the answer comes back keyed by them. Mark a recommendation with a reason whenever you have one. "
              "A form is fully answered by the owner's submit; if he types in the item's chat instead, that reply answers the newest open form provisionally (the item goes to working) and arrives with answers_to and freeform true, no answers: read his words and ask anew if needed. "
              "A submit arrives as his next message with answers_to (the question's message id) and answers {question id: {value | choice | choices | order | text, prompt, recommended?, note?, skipped?}}; its text is the same in words.")
_TYPED_QUESTION = {
    "type": "object", "required": ["type", "prompt"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9_-]{1,32}$"},
        "type": {"type": "string", "enum": list(rich_ask.TYPES)},
        "prompt": {"type": "string", "maxLength": structured.MAX_QUESTION},
        "required": {"type": "boolean"}, "help": {"type": "string", "maxLength": rich_ask.MAX_HELP},
        "labels": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
        "options": {"type": "array", "minItems": rich_ask.MIN_OPTIONS, "maxItems": rich_ask.MAX_OPTIONS, "items": {
            "type": "object", "required": ["label"], "properties": {
                "id": {"type": "string", "pattern": "^[a-z0-9_-]{1,32}$"}, "label": {"type": "string", "maxLength": rich_ask.MAX_LABEL},
                "recommended": {"type": "boolean"}, "reason": {"type": "string", "maxLength": rich_ask.MAX_REASON}}}},
        "other": {"type": "boolean"}, "min": {"type": "integer", "minimum": 0}, "max": {"type": "integer", "minimum": 0},
        "max_length": {"type": "integer", "minimum": 1, "maximum": rich_ask.MAX_LONG}, "placeholder": {"type": "string"},
        "recommend": {"type": "object"},
        "command": {"anyOf": [{"type": "string", "maxLength": rich_ask.MAX_COMMAND}, {
            "type": "object", "required": ["text"], "properties": {
                "text": {"type": "string", "maxLength": rich_ask.MAX_COMMAND}, "lang": {"type": "string", "maxLength": rich_ask.MAX_COMMAND_LANG}}}]}},
}
_ASK_SCHEMA = {
    "context": {"type": "string", "maxLength": rules.MAX_MESSAGE,
                "description": "OPTIONAL background for the questions, shown apart in a muted block above them. Needs questions. " + FORMAT_HINT},
    "questions": {"type": "array", "minItems": 1, "maxItems": structured.MAX_QUESTIONS,
                  "items": {"anyOf": [{"type": "string", "maxLength": structured.MAX_QUESTION}, _TYPED_QUESTION]},
                  "description": "Short, precise questions. PREFER TYPED ONES (objects): the owner gets a form and answers each by its id. "
                                 "A plain string is a numbered question he answers by reply. Replaces text. " + TYPED_HINT},
}
_REPEAT_SCHEMA = {
    "repeat": {"type": ["object", "string"], "description": (
        "Re-arm after each fire: {freq: daily, time: 'HH:MM'} | {freq: weekly, byweekday: [0-6, Monday is 0], time} | {freq: hourly, interval: N} | "
        "{freq: monthly, monthday: 1-31, time}. 24-hour times in the app's configured time zone (default America/New_York; preferences_get time_zone). '' stops; todo pauses it.")},
}
_PAUSE_SCHEMA = {"paused": {"type": "boolean", "description": "true pauses a repeating schedule, false resumes it."}}
_FIRE_NOW_SCHEMA = {"fire_now": {"type": "boolean", "description": "true sends to the item's session now (waking it first); a repeat keeps its next time. Refused for an approved or todo item."}}
_BORN_SCHEMA = {"state": {"type": "string", "enum": ["open", "todo"],
                          "description": "The state it is born in: open (default) or todo (parked until the owner releases it; only when the owner explicitly asks to park it)."}}
_CLAUDE_STATE_ENUM = [rules.OPEN, "working", *(s for s in rules.CLAUDE_STATES if s != rules.OPEN)]
_LEAN_SCHEMA = {"lean": {"type": "boolean", "description": "Default true: {item_id, ok, state, revision}. false: the full item with its thread."}}
SCHEDULE_OFFER_HINT = ("Optional. Propose a follow-up the owner accepts with one click (a clock button on this message): {when: ISO 8601 with a UTC offset, in the future, "
                       "e.g. 2026-10-20T09:00:00-04:00; title: a few words}. When he accepts, his reply on the thread tells you to file it: call task_manager_add with fire_at=<when> and that title, then reply with the date. Offer only a follow-up you would otherwise ask him to schedule.")
FILES_HINT = ("A thread message the owner attached files to (pasted or dropped on his reply) carries files: [{name, mime, size, path}]; "
              "each path is ABSOLUTE and local, so Read it (an image or a document) to see what he sent.")
_THREAD_SCHEMA = {"detail": {"type": "boolean", "description": "true also sends each changed item's whole thread. Default false: the new messages already come in messages."}}
_LIST_READ_SCHEMA = {
    "fields": {"type": ["array", "string"], "items": {"type": "string", "enum": sorted(lean_read.EXTRA_FIELDS) + [lean_read.FULL]},
               "description": "Opt in beyond the summary row: text, note, thread, review (the review_* block), or full (today's whole item)."},
    "include_approved": {"type": "boolean", "description": "true brings the owner's approved items back. Default false."},
    "item": {"type": "integer", "description": "One item id: that item in full with its last 10 thread messages (thread_more counts older ones)."},
    "detail": {"type": "boolean", "description": "With item: the whole thread. Default false."},
    "limit": {"type": "integer", "minimum": 1, "maximum": lean_read.MAX_LIMIT, "description": f"Rows per page, default {lean_read.DEFAULT_LIMIT}."},
    "cursor": {"type": ["integer", "string"], "description": "The previous answer's next_cursor (a paging offset, not the change cursor)."},
    "include_thread": {"type": "boolean", "description": "Same as fields thread. Default false."},
}
_FORK_STATE_ENUM = [s for s in _CLAUDE_STATE_ENUM if rules.canonical_state(s, count=False) != rules.WAITING]
_FORK_STATE_SCHEMA = {
    "fork_state": {"type": "string", "enum": _FORK_STATE_ENUM,
                   "description": "OPTIONAL. The fork's own state, task_manager_update's values (approval is the owner's alone). Unset: open."},
    "parent_state": {"type": "string", "enum": _FORK_STATE_ENUM,
                     "description": "OPTIONAL. A new state for the ORIGINAL item, in the same transaction. Unset: the parent keeps its state."},
}
_GROUP_SCHEMA = {"type": ["integer", "string", "null"],
                 "description": "A group id from task_manager_tasks_list, or a name (a new name makes the group). File by area."}
_GROUP_KEEP = ("id", "list", "name", "position", "deleted")


async def _run(call: Any) -> Any:
    try:
        return await asyncio.to_thread(call)
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc


async def _list_key(ctx: CplugContext, caller: AgentCaller, args: dict, *, required: bool = True) -> Optional[str]:
    value = args.get("list")
    if value is None and not required:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if value == "mine":
        swarm = service.swarm_of(ctx)
        thread = await swarm.thread_for_session(caller.current_session_id) if swarm is not None and not caller.external else None
        if thread:
            return thread
        project = await own_list.own_project(ctx, caller)
        if project is None:
            raise ToolError("your session belongs to no project; pass list all or a project id")
        return project
    try:
        return rules.check_list_key(value)
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc


async def _swarm_reader(ctx: CplugContext, caller: AgentCaller) -> bool:
    swarm = service.swarm_of(ctx)
    if swarm is None or caller.external:
        return False
    return bool(await swarm.thread_for_session(caller.current_session_id))


_QUOTE_SCHEMA = {"type": "integer", "description": "ONLY with kind answer: the id of the owner's message on this item that you are answering; the server snapshots its text and shows it quoted above your answer."}
_QUOTE_TEXT_SCHEMA = {"type": "string", "maxLength": 1000, "description": "ONLY with kind answer, instead of quote: the owner's question in his words, when he asked it outside the huddle."}


def _item_id(args: dict) -> int:
    value = args.get("item")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("item is required: an item id from task_manager_tasks_list or task_manager_changes")
    return value


def _thread_message(m: dict, base: Optional[Path] = None) -> dict:
    out = {"id": m["id"], "author": m["author"], "kind": m["kind"], "text": m["text"], "answered": m["answered"]}
    out.update({k: m[k] for k in ("form", "answers_to", "answers", "freeform", "quote", "quiet", "retracts", "category") if k in m})
    if "form" in m:
        out["text"] = lean_read.lead(m["text"])
    elif "answers" in m:
        out["text"] = "\n".join([lean_read.lead(m["text"]), *answers_wire.lines_of(m["answers"])])
    if m.get("files") and base is not None:
        out["files"] = files.for_agent(base, m["files"])
    if m.get("artifact"):
        out["artifact"] = {k: m["artifact"][k] for k in ("title", "description")}
    return out


def _compact(item: dict, thread: bool = True, base: Optional[Path] = None) -> dict:
    keep = ("id", "number", "list", "group", "section", "text", "note", "state", "status", "kind", "created_by", "revision", "deleted", "unread", "needs_you", "needs_action")
    out = {k: item[k] for k in keep if k in item}
    out.update({k: item[k] for k in (titles.FIELD, perceived_ask.FIELD, forks.FIELD, from_project.FIELD, *review.FIELDS, review_checks.FIELD, item_marker.FIELD, github_issue.FIELD, item_owner.FIELD, item_owner.TAG_COLUMN, item_owner.TAGGED_BY, waits.FIELD) if item.get(k)})
    trigger = item.get(triggers.FIELD)
    if trigger:
        out[triggers.FIELD] = {k: trigger[k] for k in ("kind", "fire_at_iso", "fired_at", "last_error", "repeat") if trigger.get(k) is not None}
        if trigger.get("paused"):
            out[triggers.FIELD]["paused"] = True
    if thread and "thread" in item:
        out["thread"] = [_thread_message(m, base) for m in item["thread"]]
    return out


def _group(group: dict) -> dict:
    return {k: group[k] for k in _GROUP_KEEP if k in group}


async def _caller_key(ctx: CplugContext, caller: AgentCaller) -> Optional[str]:
    return await actor_log.caller_key(ctx, caller)


async def _touched(ctx: CplugContext, caller: AgentCaller, list_key: Optional[str]) -> None:
    await _remember_lists(ctx, caller, [list_key], None)


async def _remember(ctx: CplugContext, caller: AgentCaller, list_key: Optional[str], cursor: int) -> None:
    await _remember_lists(ctx, caller, [list_key], cursor)


async def _remember_lists(ctx: CplugContext, caller: AgentCaller, list_keys: list, cursor: Optional[int]) -> None:
    key = await _caller_key(ctx, caller)
    if key is None:
        return
    store = service.store(ctx)
    for list_key in list_keys:
        name = list_key or rules.ALL_LIST
        if cursor is not None:
            await asyncio.to_thread(store.note_read, key, name, cursor, caller.current_session_id)
        await asyncio.to_thread(callers.note_caller, ctx.storage, key, name, None, caller.current_session_id)


async def _owned_lists(ctx: CplugContext, caller: AgentCaller, list_keys: set) -> set:
    if caller.external or not caller.current_session_id or not list_keys:
        return set()
    infos = await ctx.sessions.list()
    key = await _caller_key(ctx, caller)
    delivered = await asyncio.to_thread(service.store(ctx).send_targets, sorted(list_keys))
    holding = {h["list"]: h["target"] for h in held.snapshot() if h["state"] == held.HELD}
    me = {caller.current_session_id, key}
    bodies = {k: await service.agent_session(ctx, k) for k in list_keys if rules.agent_id_of(k)}
    return {k for k in list_keys
            if service.reader_owns(infos, caller.current_session_id, k, bodies.get(k))
            or delivered.get(k) in me or holding.get(k) == caller.current_session_id}


async def _record_read(ctx: CplugContext, caller: AgentCaller, items: list) -> None:
    owned, key = await _owned_lists(ctx, caller, {i["list"] for i in items if not i.get("deleted")}), await _caller_key(ctx, caller)
    mine = owner_read.held_by(items, caller, key)
    await asyncio.to_thread(_read, ctx, caller, [i for i in items if i["list"] in owned or i["id"] in mine])


def _read(ctx: CplugContext, caller: AgentCaller, items: list) -> None:
    if caller.external or not caller.current_session_id:
        return
    store = service.store(ctx)
    statuses = store.record_claude_read([(i["id"], i["seq"]) for i in items if not i.get("deleted")])
    for item in items:
        if item["id"] in statuses:
            item["status"] = statuses[item["id"]]
            item["section"] = lifecycle.section_of(item["status"])
    numbers = store.numbers(sorted({i["list"] for i in items}))
    for item in items:
        if not item.get("deleted"):
            item["number"] = numbers.get(item["id"])


def _plain(args: dict) -> dict:
    return {k: v for k, v in args.items() if k != "lean"}


def _answer(payload: dict, args: dict) -> dict:
    return tool_result(batch.lean_of(payload) if flags.flag(args, "lean", True) else payload)


def _lean_items(items: list, fields: Any, base: Optional[Path]) -> list:
    threads = fields == lean_read.FULL or "thread" in fields
    return [lean_read.project(_compact(i, threads, base=base), fields) for i in items]


async def _list_one_item(ctx: CplugContext, caller: AgentCaller, item_id: Any, session: Optional[str], detail: bool = False) -> dict:
    item = await _run(lambda: service.store(ctx).item(_item_id({"item": item_id})))
    await owner_read.annotate(ctx, [item])
    cursor = await asyncio.to_thread(service.store(ctx).current_cursor)
    await _remember(ctx, caller, item["list"], cursor)
    await _record_read(ctx, caller, [item])
    changes_view.remember(session, [item])
    shown = _compact(item, True, base=ctx.storage.path)
    forks_made = await _run(lambda: service.store(ctx).forks_of(item["id"]))
    if forks_made:
        shown["forks"] = [lean_read.fork_row(f) for f in forks_made]
    older = len(shown.get("thread", ())) - lean_read.ITEM_THREAD_TAIL
    if not detail and older > 0:
        shown["thread"] = shown["thread"][-lean_read.ITEM_THREAD_TAIL:]
        shown["thread_more"] = older
    return tool_result({"list": item["list"], "cursor": cursor, "item": shown})


async def huddle_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    session = None if caller.external else caller.current_session_id
    if args.get("item") is not None:
        return await _list_one_item(ctx, caller, args["item"], session, flags.flag(args, "detail", False))
    try:
        fields = lean_read.parse_fields(args.get("fields"), flags.flag(args, "include_thread", False))
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc
    approved = flags.flag(args, "include_approved", False)
    aggregate = flags.flag(args, "aggregate", False)
    include_swarm = await _swarm_reader(ctx, caller)
    if aggregate:
        body = await _run(lambda: service.store(ctx).aggregate(hide_swarm=lane.hides_swarm(None, include_swarm)))
        names = await asyncio.to_thread(service.project_names, ctx)
        lists = service.aggregate_groups(body, names)
        key = None
    else:
        key = await _list_key(ctx, caller, args)
        body = await _run(lambda: service.store(ctx).list_items(key, hide_swarm=lane.hides_swarm(key, include_swarm)))
        lists = [{"list": key, "name": None, "groups": body["groups"], "items": body["items"]}]
    rows = [(n, i) for n, g in enumerate(lists) for i in g["items"] if not lean_read.hides(i, approved)]
    hidden = sum(len(g["items"]) for g in lists) - len(rows)
    try:
        page, more = await _run(lambda: lean_read.page_of(rows, args.get("limit"), args.get("cursor")))
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc
    shown = [i for _n, i in page]
    await owner_read.annotate(ctx, shown)
    await _remember_lists(ctx, caller, [g["list"] for g in lists], body["cursor"])
    await _record_read(ctx, caller, shown + [i for g in lists for i in g["items"] if lean_read.hides(i, approved)])
    changes_view.remember(session, shown)
    base = ctx.storage.path
    meta = {"cursor": body["cursor"], "total": len(rows), **({"approved_hidden": hidden} if hidden else {}), **({"next_cursor": more} if more else {})}
    if not aggregate:
        roles = await mcp_roles.header(ctx, caller, key, lambda: _caller_key(ctx, caller))
        return tool_result({"list": key, **meta, **({"roles": roles} if roles else {}), "groups": [_group(g) for g in body["groups"]], "items": _lean_items(shown, fields, base)})
    first_page = not args.get("cursor")
    out = [{"list": g["list"], "name": g["name"], "groups": [_group(x) for x in g.get("groups", [])],
            "items": _lean_items([i for n, i in page if n == at], fields, base)} for at, g in enumerate(lists)]
    return tool_result({**meta, "groups": [g for g in out if g["items"] or first_page]})


async def huddle_schedules_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    key = None if args.get("list") == rules.ALL_LIST else await _list_key(ctx, caller, args, required=False)
    paused = args.get("paused")
    if paused is not None and not isinstance(paused, bool):
        raise ToolError("paused must be true or false")
    try:
        view = await scheduled.build(ctx, key, paused)
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc
    return tool_result({"cursor": view["cursor"], "total": len(view["schedules"]), "schedules": view["schedules"]})


def _with_threads(store: Any, items: list) -> list:
    out = []
    for entry in items:
        if entry.get("deleted"):
            out.append(entry)
            continue
        try:
            out.append({**entry, "thread": store.item(entry["id"])["thread"]})
        except TaskManagerNotFound:
            out.append(entry)
    return out


async def huddle_changes(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    since = args.get("since", 0)
    threads = flags.flag(args, "include_thread", flags.flag(args, "detail", False))
    key = await _list_key(ctx, caller, args, required=False)
    hide = lane.hides_swarm(key, await _swarm_reader(ctx, caller))
    body = await _run(lambda: service.store(ctx).changes(since, key, all_live_groups=False, hide_swarm=hide))
    await _remember(ctx, caller, key, body["cursor"])
    await _record_read(ctx, caller, body["items"])
    mine = None if flags.flag(args, "include_mine", False) else await _caller_key(ctx, caller)
    kept = [m for m in body["messages"] if not (mine and m["author"] != JOE and m["author_key"] == mine)]
    messages = [{**_thread_message(m, ctx.storage.path), "item": m["item_id"]} for m in kept]
    session = None if caller.external else caller.current_session_id
    if threads:
        body["items"] = await _run(lambda: _with_threads(service.store(ctx), body["items"]))
    items = changes_view.slim(session, [_compact(i, threads, base=ctx.storage.path) for i in body["items"]], body["reset"])
    omitted = len(body["messages"]) - len(kept)
    replied = await _run(lambda: service.store(ctx).awaiting_answer([i["id"] for i in body["items"]]))
    return tool_result({"cursor": body["cursor"], "reset": body["reset"], "items": items,
                        "groups": [_group(g) for g in body.get("groups", [])], "messages": messages,
                        **({"omitted_own": omitted} if omitted else {}),
                        **({"owner_replied": replied, "owner_replied_do": reply_return.OWNER_REPLIED_HINT} if replied else {})})


@own_list.guarded()
async def _move(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    item = _item_id(args)
    if "list" not in args and "group" not in args:
        raise ToolError("pass list (another list), group (a group to file it in), or both")
    key = await _list_key(ctx, caller, args, required=False)
    if key is None:
        key = (await _run(lambda: service.store(ctx).item(item)))["list"]
    await _run(lambda: service.known_list_key(ctx, key))
    if "group" in args:
        group = await _run(lambda: service.groups(ctx).find_or_create(key, args["group"], actor=CLAUDE))
        moved = await _run(lambda: service.store(ctx).move(item, key, actor=CLAUDE, group=group))
    else:
        moved = await _run(lambda: service.store(ctx).move(item, key, actor=CLAUDE))
    await _touched(ctx, caller, key)
    return steer.merge(_compact(moved, base=ctx.storage.path), steer.not_reaching(moved.get("status")))


async def huddle_move(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _move(ctx, caller, _plain(args)), args)


async def huddle_group_create(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await _group_create(ctx, caller, args))


@own_list.guarded(records=False)
async def _group_create(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    key = await _list_key(ctx, caller, args)
    await _run(lambda: service.known_list_key(ctx, key))
    made = await _run(lambda: service.groups(ctx).create(key, args.get("name"), actor=CLAUDE))
    await _touched(ctx, caller, key)
    return {**_group(made), "created": made["created"]}


async def huddle_group_update(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await _group_update(ctx, caller, args))


@own_list.guarded(records=False, group_is_id=True)
async def _group_update(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - {"group", "name", "position", "remove"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    group = args.get("group")
    if isinstance(group, bool) or not isinstance(group, int):
        raise ToolError("group is required: a group id from task_manager_tasks_list (task_manager_guide topic: 3)")
    writer = service.groups(ctx)
    if flags.flag(args, "remove", False):
        removed = await _run(lambda: writer.remove(group, actor=CLAUDE))
        await _touched(ctx, caller, removed["list"])
        return removed
    changed = await _run(lambda: writer.update(group, actor=CLAUDE, name=args.get("name"), position=args.get("position")))
    await _touched(ctx, caller, changed["list"])
    return _group(changed)


@own_list.guarded(creates=True)
async def _add(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    key = await _list_key(ctx, caller, args)
    text = args.get("text")
    if args.get("paused") is not None:
        raise ToolError("paused applies to task_manager_update on an item that already repeats")
    group = None
    if args.get("group") is not None:
        await _run(lambda: service.known_list_key(ctx, key))
        group = await _run(lambda: service.groups(ctx).find_or_create(key, args["group"], actor=CLAUDE))
    created_key = await _caller_key(ctx, caller) or ""
    added = await _run(lambda: service.store(ctx).add(
        key, text, actor=CLAUDE, kind=args.get("kind", rules.NO_KIND), group=group, review_fields=args,
        title=args.get(titles.FIELD), created_key=created_key, fire_at=args.get("fire_at"), repeat=args.get("repeat"),
        marker=_marker_arg(args),
        github_issue_url=args.get(github_issue.FIELD), perceived_ask=args.get(perceived_ask.FIELD),
        state=rules.canonical_state(args.get("state"))))
    added = await mcp_tags.tag_filer(ctx, added, created_key, external=caller.external)
    if added.get("kind") == rules.QUESTION:
        added = await _question_post(ctx, caller, added)
    await _touched(ctx, caller, key)
    reach = steer.fields(True, steer.QUESTION_REASON) if added.get("kind") == rules.QUESTION else steer.not_reaching(added.get("status"))
    return steer.merge(_compact(added, base=ctx.storage.path), reach)


async def _question_post(ctx: CplugContext, caller: AgentCaller, added: dict) -> dict:
    author_key = await _caller_key(ctx, caller) or ""
    posted = await _run(lambda: service.store(ctx).post(added["id"], added["text"], actor=CLAUDE, kind=QUESTION, author_key=author_key))
    if not caller.external:
        await asyncio.to_thread(service.surface_question, ctx, caller.current_session_id, added["id"], posted["message"]["id"])
    return posted["item"]


async def huddle_add(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _add(ctx, caller, args), args)


@own_list.guarded(dnd=True)
async def _update(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    args = rules.canonical_state_args(args)
    item = _item_id(args)
    allowed = {"item", "text", "state", "kind", "expected_revision", "fire_at", "repeat", "paused", "fire_now", titles.FIELD, perceived_ask.FIELD, item_marker.FIELD, *_LEGACY_FLAG_ARGS, github_issue.FIELD, *review.FIELDS, review_checks.FIELD, mcp_tags.FIELD, *waits.ARGS}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}; claude may change text, state, kind, title, perceived_ask, marker, github_issue, fire_at, repeat, paused, fire_now, tag and the review fields (and review_checks) only")
    revision = args.get("expected_revision")
    working = args.get("state") == lifecycle.WORKING
    state = None if working else args.get("state")
    parking = mcp_wait.park_args(args)
    if parking is None and any(name in args for name in waits.ARGS):
        raise ToolError(f"{', '.join(waits.ARGS)} apply only with state waiting")
    parker = await _caller_key(ctx, caller) if parking is not None else None
    changed = await _run(lambda: service.store(ctx).update(
        item, actor=CLAUDE, expected_revision=revision, text=args.get("text"), state=state, kind=args.get("kind"),
        review_fields=args, title=args.get(titles.FIELD), fire_at=args.get("fire_at"),
        repeat=args.get("repeat"), paused=args.get("paused"),
        marker=_marker_arg(args),
        github_issue_url=args.get(github_issue.FIELD), perceived_ask=args.get(perceived_ask.FIELD),
        wait=parking, wait_by=parker or "", review_checks=args.get(review_checks.FIELD)))
    if mcp_tags.FIELD in args:
        parked_with = {k: changed[k] for k in (waits.TOKEN_KEY,) if k in changed}
        changed = {**await mcp_tags.apply(ctx, item, args[mcp_tags.FIELD], caller_key=lambda: _caller_key(ctx, caller)), **parked_with}
    if working:
        claimant = await _caller_key(ctx, caller)
        swarm_body = not caller.external and await roles_service.is_swarm_body(ctx, caller.current_session_id)
        changed = await _run(lambda: service.store(ctx).mark_working(item, claimant, swarm_caller=swarm_body))
    if flags.flag(args, "fire_now", False):
        try:
            changed = await schedule.run_now(item)
        except rules.TaskManagerError as exc:
            raise ToolError(str(exc)) from exc
    await _touched(ctx, caller, changed["list"])
    answer = steer.merge(steer.merge(_compact(changed, base=ctx.storage.path), steer.for_update(args, changed.get("status"))), mcp_wait.wait_answer(changed))
    holding = await _run(lambda: review_lock.holding_subtasks(service.store(ctx), item)) if child_hold.stops(args.get("state"), changed) else []
    return steer.merge(answer, child_hold.stop_answer(args.get("state"), changed, holding))


async def huddle_update(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _update(ctx, caller, _plain(args)), args)


@own_list.guarded(dnd=True)
async def _fork(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    args = rules.canonical_state_args(args)
    item = _item_id(args)
    allowed = {"item", "title", "text", "list", "group", "fork_state", "parent_state", child_hold.FORK_ARG, *review.FIELDS}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    if rules.WAITING in (args.get("fork_state"), args.get("parent_state")):
        raise ToolError("a fork cannot set waiting: to make the parent wait on its forks pass parent_waits true; "
                        "to park on anything else, fork, then task_manager_update state waiting, waiting_on and wait_kind")
    parent_waits = args.get(child_hold.FORK_ARG, False)
    if not isinstance(parent_waits, bool):
        raise ToolError(f"{child_hold.FORK_ARG} must be true or false")
    store = service.store(ctx)
    key = await _list_key(ctx, caller, args, required=False)
    if key is not None:
        await _run(lambda: service.known_list_key(ctx, key))
    group = groups.UNSET
    if "group" in args:
        target = key or (await _run(lambda: store.item(item)))["list"]
        group = await _run(lambda: service.groups(ctx).find_or_create(target, args["group"], actor=CLAUDE))
    claimant = await _caller_key(ctx, caller) or ""
    made = await _run(lambda: store.fork(
        item, actor=CLAUDE, claimed_by=claimant, title=args.get(titles.FIELD), text=args.get("text"),
        list_key=key, group=group, fork_state=args.get("fork_state"), parent_state=args.get("parent_state"), review_fields=args,
        parent_waits=parent_waits))
    await _touched(ctx, caller, made["fork"]["list"])
    return {"fork": _compact(made["fork"], base=ctx.storage.path), "parent": _compact(made["parent"], base=ctx.storage.path)}


async def huddle_fork(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _fork(ctx, caller, _plain(args)), args)


async def _post(ctx: CplugContext, caller: AgentCaller, args: dict, kind: Optional[str], parts: str = "",
                quote: Optional[int] = None, quote_text: str = "", notify: bool = False, offer: Optional[dict] = None) -> dict:
    item = _item_id(args)
    text = args.get("text")
    author_key = await _caller_key(ctx, caller) or ""
    posted = await _run(lambda: service.store(ctx).post(item, text, actor=CLAUDE, kind=kind, author_key=author_key, parts=parts,
                                                        quote=quote, quote_text=quote_text, notify=notify, offer=offer))
    await _touched(ctx, caller, posted["item"]["list"])
    return posted


@own_list.guarded()
async def _ask(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    refusal = steer.check_ask(args)
    if refusal:
        raise ToolError(refusal)
    text, parts = await _run(lambda: structured.build(args.get("text"), args.get("context"), args.get("questions")))
    posted = await _post(ctx, caller, {"item": args.get("item"), "text": text}, QUESTION, parts)
    surfaced = False
    await asyncio.to_thread(question_toasts.dismiss, ctx, posted["item"]["id"])
    if not caller.external:
        surfaced = await asyncio.to_thread(service.surface_question, ctx, caller.current_session_id,
                                       posted["item"]["id"], posted["message"]["id"])
    return {"item": _compact(posted["item"], base=ctx.storage.path), "message_id": posted["message"]["id"], "notified": surfaced,
            "question_ids": structured.question_ids(parts), **steer.fields(True, steer.QUESTION_REASON)}


async def huddle_ask(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _ask(ctx, caller, _plain(args)), args)


def _marker_arg(args: dict) -> Optional[object]:
    return item_marker.from_args(args.get(item_marker.FIELD), args.get("flag_color"))


def _check_marker(args: dict) -> bool:
    try:
        return bool(item_marker.clean_fields(_marker_arg(args)))
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc


def _check_offer(args: dict) -> Optional[dict]:
    if args.get("offer_schedule") is None:
        return None
    try:
        return schedule_offer.clean(args["offer_schedule"])
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc


def _reply_kind(args: dict) -> tuple:
    kind, action, notify = args.get("kind"), args.get("action"), args.get("notify")
    if kind is not None and kind not in kinds.REPLY_KINDS:
        raise ToolError(f"kind must be one of {', '.join(kinds.REPLY_KINDS)} (a question goes through task_manager_ask)")
    if notify is not None and not isinstance(notify, bool):
        raise ToolError("notify must be true or false")
    try:
        checked = review.check_action(action) if action is not None else None
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc
    if checked in steer.RETIRED_LOOK_ACTIONS:
        raise ToolError(steer.RETIRED_LOOK_ACTIONS[checked])
    if checked is not None and kind not in (None, kinds.ATTENTION):
        raise ToolError("action belonged to the retired look; to notify use an info with notify true")
    if kind == kinds.ATTENTION or checked is not None:
        return kinds.INFO, True
    if notify and kind not in (None, kinds.INFO):
        raise ToolError("notify goes only on an info")
    return kind, bool(notify)


@own_list.guarded(dnd=True)
async def _reply(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    kind, notify = _reply_kind(args)
    quote, quote_text = args.get("quote"), args.get("quote_text") or ""
    if (quote is not None or quote_text) and kind != kinds.ANSWER:
        raise ToolError("quote and quote_text go only on an answer: use kind answer")
    if kind == kinds.ANSWER and (quote is None) == (not quote_text):
        raise ToolError("an answer quotes the question it answers: pass quote (the id of the owner's message on this item) or quote_text (his words, when he asked outside the huddle)")
    flagging = _check_marker(args)
    refusal = steer.check_reply(kind, args)
    if refusal:
        raise ToolError(refusal)
    if args.get("changes") is not None and not isinstance(args["changes"], bool):
        raise ToolError("changes must be true or false")
    offer = _check_offer(args)
    attached = await reply_paths.parts_for(ctx, caller, _item_id(args), args.get(reply_paths.FIELD))
    guarded = {}
    if not own_list.crossing():
        kind, quote, quote_text, notify, guarded = await _run(lambda: owner_guards.plan_reply(
            service.store(ctx), _item_id(args), kind, notify, quote=quote, quote_text=quote_text, has_files=bool(attached)))
    posted = await _post(ctx, caller, args, kind, attached, quote=quote, quote_text=quote_text, notify=notify, offer=offer)
    if flagging:
        posted["item"] = await _run(lambda: service.store(ctx).update(
            posted["item"]["id"], actor=CLAUDE, marker=_marker_arg(args)))
    return {"item": _compact(posted["item"], base=ctx.storage.path), "message_id": posted["message"]["id"], "kind": posted["message"]["kind"],
            **steer.for_reply(notify, posted["item"].get("status"), posted["message"]["kind"]), **guarded}


async def huddle_reply(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _reply(ctx, caller, _plain(args)), args)


@own_list.guarded()
async def _mark_answered(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - {"item"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    item = _item_id(args)
    changed = await _run(lambda: service.store(ctx).mark_answered(item, actor=CLAUDE))
    await _touched(ctx, caller, changed["list"])
    return steer.merge(_compact(changed, base=ctx.storage.path), steer.not_reaching(changed.get("status")))


async def huddle_mark_answered(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return _answer(await _mark_answered(ctx, caller, _plain(args)), args)


async def _delete(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    raise ToolError(f"only the owner deletes, and a delete is for good (thread, history and files). To ask him, call {rules.STATE_REQUEST_TOOL} "
                    "with action delete, the item and your reason; he approves each request in the approvals inbox")


async def huddle_batch(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - {"list_id", "ops", "stop_on_error"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    key = await _list_key(ctx, caller, {"list": args.get("list_id")})
    handlers = {name: (lambda a, fn=fn: fn(ctx, caller, a)) for name, fn in (
        ("update", _update), ("reply", _reply), ("ask", _ask), ("move", _move), ("mark_answered", _mark_answered),
        ("delete", _delete), ("fork", _fork), ("progress", _progress))}
    handlers["add"] = lambda a: _add(ctx, caller, {**a, "list": a.get("list", args.get("list_id"))})

    async def in_list(item_id: int) -> None:
        found = (await _run(lambda: service.store(ctx).item(item_id)))["list"]
        if found != key:
            raise ToolError(f"item {item_id} is in list {found}, not {key}")

    return tool_result(await batch.run(args, handlers=handlers, in_list=in_list))


@own_list.guarded(records=False, dnd=True)
async def _progress(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - {"item", "phase", "note", "worker"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    item = _item_id(args)
    found = await _run(lambda: service.store(ctx).item(item))
    await _run(lambda: progress.report(ctx, item, args.get("phase"), args.get("note"), args.get("worker")))
    await _touched(ctx, caller, found["list"])
    return {"id": item, "state": found.get("state"), "revision": found.get("revision")}


async def huddle_progress(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(batch.lean_of(await _progress(ctx, caller, _plain(args))))


@own_list.guarded()
async def _wait_resolve(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await mcp_wait.huddle_wait_update(ctx, caller, args)


async def huddle_wait_update(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await _wait_resolve(ctx, caller, _plain(args)))


async def huddle_role_set(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await mcp_roles.role_set(ctx, caller, args, caller_key=lambda: _caller_key(ctx, caller)))


async def huddle_focus(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await _focus(ctx, caller, args))


@own_list.guarded(records=False)
async def _focus(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - {"list", "items", "open", "clear", item_marker.FIELD, *_LEGACY_FLAG_ARGS})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    if flags.flag(args, "clear", False):
        return focus.clear(ctx)
    flagging = _check_marker(args)
    key = await _list_key(ctx, caller, args)
    items = args.get("items") or []
    if not isinstance(items, list):
        raise ToolError("items is a list of item ids from task_manager_tasks_list")
    open_id = args.get("open")
    focused = await _run(lambda: focus.set_focus(ctx, key, items, open_id, mark_unread=True))
    await _touched(ctx, caller, key)
    pointed = set(items) | ({open_id} if open_id else set())
    listed = await _run(lambda: focus.live_items(service.store(ctx), key))
    if flagging:
        store = service.store(ctx)
        for item in (i for i in listed.values() if i["id"] in pointed and i["state"] not in rules.APPROVED_STATES):
            await _run(lambda i=item: store.update(i["id"], actor=CLAUDE, marker=_marker_arg(args)))
    await _record_read(ctx, caller, [i for i in listed.values() if i["id"] in pointed])
    return focused


async def huddle_guide(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - {"since_rev", "topic", "detail"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    try:
        return tool_result(await asyncio.to_thread(guide_answer, args.get("since_rev"), args.get("topic"), flags.flag(args, "detail", False)))
    except (ValueError, OSError) as exc:
        raise ToolError(f"task_manager_guide: {exc}") from exc


@own_list.guarded(dnd=True)
async def _artifact(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    item = _item_id(args)

    async def touched(list_key: str) -> None:
        await _touched(ctx, caller, list_key)

    return await mcp_artifact.artifact(ctx, caller, args, run=_run, caller_key=lambda: _caller_key(ctx, caller), touched=touched, item_id=item)


async def huddle_artifact(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await _artifact(ctx, caller, _plain(args)))


async def huddle_inbox_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    key = await _list_key(ctx, caller, args, required=False)
    return tool_result(await mcp_inbox.inbox_list(ctx, args, run=_run, list_key=key))


async def huddle_inbox_file(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await mcp_inbox.inbox_file(ctx, caller, args, run=_run, add=_add, update=_update, ask=_ask))


async def huddle_item_state_request(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await state_request.apply(ctx, caller, args))


TOOLS: dict = {
    "task_manager_guide": ToolSpec(
        "The huddle rules. Only needed before a write other than task_manager_progress_set and task_manager_reply. No arguments: the core rules plus an index of the rest. topic returns one section, detail true the whole guide, since_rev (the guide_rev you last read) only what changed. Every huddle answer carries guide_rev.",
        {"since_rev": {"type": "integer", "minimum": 0, "description": "The guide_rev you last read: answers up_to_date, or what changed for agents since."},
         "topic": {"type": ["integer", "string"], "description": "One section by number or name (the index lists them)."},
         "detail": {"type": "boolean", "description": "true answers the whole guide. Default false."}},
        [], huddle_guide, "read",
    ),
    "task_manager_tasks_list": ToolSpec(
        "Read a huddle list (the to-do list shared with the owner) as lean summary rows: id, number, title, status, section, group, needs_action, unread; no threads, approved items hidden. Opt in with fields, include_approved, item (one item in full, last 10 messages; detail true for all), limit and cursor, aggregate. Never work a todo item unless the owner asks. Files: path is ABSOLUTE, Read it.",
        {"list": _LIST_SCHEMA, "aggregate": {"type": "boolean", "description": "Every list, grouped; list is then ignored."}, **_LIST_READ_SCHEMA},
        [], huddle_list, "read",
    ),
    "task_manager_schedules_list": ToolSpec(
        "Scheduled huddle items across every list, soonest next fire first: {list, list_name, item, title, next_fire (ISO with offset; null once a one-shot has fired), repeat, paused, state, pings {project_id, project, session}}. Filter with list (all or omitted: every list) or paused. Read only; change a schedule with task_manager_update.",
        {"list": _LIST_SCHEMA, "paused": {"type": "boolean", "description": "true only paused repeats, false only unpaused. Omit for both."}},
        [], huddle_schedules_list, "read",
    ),
    "task_manager_changes": ToolSpec(
        "Only what changed after a cursor (from task_manager_tasks_list or the last task_manager_changes). Items you already hold come back as {id, status, section, revision}; your own posts are left out of messages (include_mine true keeps them), the owner's always come whole. No threads unless detail true. A message's files[].path is ABSOLUTE: Read it. Omit list for every list.",
        {"since": {"type": "integer", "minimum": 0}, "list": _LIST_SCHEMA, **_THREAD_SCHEMA,
         "include_mine": {"type": "boolean", "description": "true keeps your own posts in messages. Default false."}}, ["since"], huddle_changes, "read",
    ),
    "task_manager_add": ToolSpec(
        "Add an item to a huddle list, marked as yours. Plain text, no 'done:' prefix (set kind). It lands open: file it by area with group, give it a short title, optionally schedule it with fire_at. Put formatted detail in a task_manager_reply. Answers lean unless lean is false.",
        {"list": _LIST_SCHEMA, "text": {"type": "string", "maxLength": rules.MAX_TEXT, "description": "Plain text (no markdown); formatted detail goes in a task_manager_reply."}, "kind": _KIND_SCHEMA,
         "group": _GROUP_SCHEMA, **_TITLE_SCHEMA, **_PERCEIVED_ASK_SCHEMA, **_MARKER_SCHEMA, **_GITHUB_ISSUE_SCHEMA, **_REVIEW_SCHEMAS, **_FIRE_AT_SCHEMA, **_REPEAT_SCHEMA, **_BORN_SCHEMA, **_LEAN_SCHEMA, **own_list.SCHEMA},
        ["list", "text"], huddle_add, "agent",
    ),
    "task_manager_update": ToolSpec(
        "Change an item: your own item's text or kind, any item's title, or its state. Set working when you start, waiting when blocked (needs waiting_on and wait_kind), review when finished (with a review_* block), open to take it back. Only the owner approves. Set todo only on his explicit ask to park it; todo items are not worked unless the owner asks. Only a question or a review reaches the owner.",
        {"item": _ITEM_SCHEMA, "text": {"type": "string", "description": "Plain text (no markdown); formatted detail goes in a task_manager_reply."},
         "state": {"type": "string", "enum": _CLAUDE_STATE_ENUM},
         "kind": _KIND_SCHEMA, **_TITLE_SCHEMA, **_PERCEIVED_ASK_SCHEMA, **_MARKER_SCHEMA, **_GITHUB_ISSUE_SCHEMA, **_REVIEW_SCHEMAS, **_REVIEW_CHECKS_SCHEMA, **_FIRE_AT_SCHEMA, **_REPEAT_SCHEMA, **_PAUSE_SCHEMA, **_FIRE_NOW_SCHEMA, **mcp_tags.SCHEMA, **mcp_wait.SCHEMA,
         "expected_revision": {"type": "integer"}, **_LEAN_SCHEMA, **own_list.SCHEMA, **dnd_gate.SCHEMA}, ["item"], huddle_update, "agent",
    ),
    "task_manager_state_request": ToolSpec(
        "Ask the owner to REOPEN an approved item (to open, or waiting via to_state), CLOSE an open one (his approve is the tick), "
        "UNDO_COMPLETION of a closure or DELETE one for good. task_manager_update cannot touch an approved item. Nothing changes until he approves in the "
        "approvals inbox; asking again updates it. Answers pending: read the outcome with approval_wait.",
        {"item": _ITEM_SCHEMA, "action": {"type": "string", "enum": list(state_request.ACTIONS)},
         "reason": {"type": "string", "maxLength": state_request.MAX_REASON, "description": "Why, in plain words; the owner reads it on the card."},
         "to_state": {"type": "string", "enum": list(state_request.REOPEN_TARGETS), "description": "reopen only; default open."},
         **own_list.SCHEMA}, ["item", "action", "reason"], huddle_item_state_request, "inbox",
        prepare=state_request.prepare, dedupe_by=state_request.DEDUPE_BY, on_deny=state_request.on_deny,
        canonical_args=state_request.canonical_shown,
    ),
    "task_manager_move": ToolSpec(
        "Move an item to the bottom of another list (find the project id with projects_list; all is the shared list) and/or into a group of it (an id or area name; null ungroups). Its thread, note, state and unread flag go with it. Answers lean unless lean is false.",
        {"item": _ITEM_SCHEMA, "list": _LIST_SCHEMA, "group": _GROUP_SCHEMA, **_LEAN_SCHEMA, **own_list.SCHEMA}, ["item"], huddle_move, "agent",
    ),
    "task_manager_fork": ToolSpec(
        "Fork an item: a new item beside it (copy of its title and text unless you give them) with its own state (fork_state), and optionally a new state for the original (parent_state), in one transaction. Approval stays the owner's. Answers lean {item_id, ok, fork, parent} unless lean is false.",
        {"item": _ITEM_SCHEMA, "text": {"type": "string", "maxLength": rules.MAX_TEXT, "description": "The fork's text; default the parent's. Plain text."},
         "list": _LIST_SCHEMA, "group": _GROUP_SCHEMA, **_FORK_STATE_SCHEMA, **_TITLE_SCHEMA, **_REVIEW_SCHEMAS, **_LEAN_SCHEMA, **own_list.SCHEMA, **dnd_gate.SCHEMA,
         child_hold.FORK_ARG: {"type": "boolean", "description": "OPTIONAL. The original waits on its forks: it goes to waiting until none is open or waiting. No parent_state with it."}},
        ["item"], huddle_fork, "agent",
    ),
    "task_manager_group_create": ToolSpec(
        "Add a named group (a foldable area section, such as auth or sidebar) to a huddle list, then file items into it with task_manager_add or task_manager_move. An existing name (any case) answers that group with created false, so repeating is safe.",
        {"list": _LIST_SCHEMA, "name": {"type": "string", "maxLength": groups.MAX_NAME}, **own_list.SCHEMA}, ["list", "name"],
        huddle_group_create, "agent",
    ),
    "task_manager_group_update": ToolSpec(
        "Rename a huddle group (name), move it among the list's groups (position, 0 is first), or remove it (remove true): its items become ungrouped, never deleted.",
        {"group": {"type": "integer", "description": "A group id from task_manager_tasks_list."},
         "name": {"type": "string", "maxLength": groups.MAX_NAME}, "position": {"type": "integer", "minimum": 0},
         "remove": {"type": "boolean"}, **own_list.SCHEMA}, ["group"], huddle_group_update, "agent",
    ),
    "task_manager_ask": ToolSpec(
        "Ask the owner a question on an item ONLY when you are blocked on his answer: the item becomes question and he is notified. Put background in context and typed questions (yes_no, single, multi, rank, short_text, long_text) in questions; his form answer returns keyed by your ids. Not blocked? Use task_manager_reply. Only a question or a review reaches the owner.",
        {"item": _ITEM_SCHEMA, "text": {"type": "string", "maxLength": rules.MAX_MESSAGE, "description": "A plain question (kept for compatibility). Prefer context plus questions."},
         **_ASK_SCHEMA, **_LEAN_SCHEMA, **own_list.SCHEMA}, ["item"], huddle_ask, "agent",
    ),
    "task_manager_answered_set": ToolSpec(
        "Mark an item's open question (your task_manager_ask) answered WITHOUT a reply, only when the owner really answered it outside the huddle. The item leaves status question. Safe to repeat. Answers lean unless lean is false.",
        {"item": _ITEM_SCHEMA, **_LEAN_SCHEMA, **own_list.SCHEMA}, ["item"], huddle_mark_answered, "agent",
    ),
    "huddle_focus": ToolSpec(
        "DEPRECATED: mark tasks with the marker argument of task_manager_update instead. Still highlights rows and opens one in the owner's views, and marks each row unread for him. clear true removes the highlight.",
        {"list": _LIST_SCHEMA, "items": {"type": "array", "items": _ITEM_SCHEMA, "maxItems": focus.MAX_FOCUS_ITEMS},
         "open": {"type": ["integer", "null"], "description": "The item id to open (it is highlighted too); null opens nothing."},
         "clear": {"type": "boolean", "description": "true drops the current highlight; the other arguments are then ignored."},
         **_MARKER_SCHEMA, **own_list.SCHEMA},
        [], huddle_focus, "agent",
    ),
    "task_manager_progress_set": ToolSpec(
        "Show a worker's live state on a working item's row so the owner need not read your terminal. Set phase (queued, running, testing, installing, blocked, done) and a short note (60 characters shows). One line per worker label; no update for 30 minutes reads stale. Lost on a restart. Also a task_manager_batch_run op.",
        {"item": _ITEM_SCHEMA, "phase": {"type": "string", "enum": list(progress.PHASES)},
         "note": {"type": "string", "maxLength": progress.MAX_NOTE, "description": "OPTIONAL. What it is doing, short (the row cuts at about 60 characters)."},
         "worker": {"type": "string", "maxLength": progress.MAX_WORKER, "description": f"OPTIONAL. This worker's label; default {progress.DEFAULT_WORKER}. One line per label."}, **own_list.SCHEMA, **dnd_gate.SCHEMA},
        ["item", "phase"], huddle_progress, "agent",
    ),
    "task_manager_wait_update": ToolSpec(
        "End a waiting task's wait, or its wait on its forks: result cleared (what it waited on is over) or failed (with a reason). The task goes back to open. The same as the wait's callback route, which a script calls with the one-time token from the task_manager_update answer.",
        {**mcp_wait.RESOLVE_PROPERTIES, **own_list.SCHEMA}, ["item", "result"], huddle_wait_update, "agent",
    ),
    "task_manager_role_set": ToolSpec(
        "Set a role on your OWN session. role dnd (do not disturb): no NEW tasks reach you by default; your claimed tasks, crosstalk and the owner's own pick still do. role lead: take your project's lead seat, only while it is vacant (the lead owns unclaimed tasks); a held seat is refused, ask the owner. on true or false.",
        {"role": {"type": "string", "enum": list(mcp_roles.ROLES)}, "on": {"type": "boolean", "description": "true sets the role, false clears it."}},
        ["role", "on"], huddle_role_set, "agent",
    ),
    "task_manager_artifact_add": ToolSpec(
        "Show the owner a PAGE (visual, preview, mock-up, comparison, chart): posts one self-contained HTML document as a card; open shows it in a locked-down frame. Not for text (use task_manager_reply). Pass html OR file_path, max 2 MB, inline CSS/JS, images as data: URIs. No network, storage or links out, and it cannot answer back: follow with task_manager_ask. Marks the item unread.",
        {"item": _ITEM_SCHEMA,
         "title": {"type": "string", "minLength": 1, "maxLength": artifacts.MAX_TITLE, "description": "The card's title."},
         "description": {"type": "string", "maxLength": artifacts.MAX_DESCRIPTION, "description": "One line saying what the page shows."},
         "html": {"type": "string", "description": "The whole page as one HTML document (up to 2 MB)."},
         "file_path": {"type": "string", "description": "Instead of html: an ABSOLUTE path to an .html file you wrote (up to 2 MB, not a symlink)."},
         **own_list.SCHEMA, **dnd_gate.SCHEMA},
        ["item", "title"], huddle_artifact, "agent",
    ),
    "task_manager_entries_list": ToolSpec(
        "The owner's add-box entries still waiting to be filed (queued or sent to a session): {id, list, text (the raw text as typed), status, created_at}. Read only; file one with task_manager_entry_import. list: all entries when omitted, or mine / a project id.",
        {"list": _LIST_SCHEMA}, [], huddle_inbox_list, "read",
    ),
    "task_manager_entry_import": ToolSpec(
        "File an add-box entry (the 'huddle inbox:' line names its id) as one or more items: split several requests, title each, group it, and obey a leading backlog or his plain ask to park it (state todo; else born open), now (working, you start it) or ask (question). Each item {title, text, group?, state?, ask?, perceived_ask?}; the raw text stays on every item. Read the guide's filing section first.",
        {"inbox_id": {"type": "integer", "minimum": 1, "description": "The entry id from the 'huddle inbox:' line or task_manager_entries_list."},
         "items": {"type": "array", "minItems": 1, "maxItems": inbox.MAX_FILED_ITEMS, "items": {
             "type": "object", "required": ["title", "text"],
             "properties": {"title": {"type": "string", "maxLength": titles.MAX_TITLE, "description": "A short title for the item."},
                            "text": {"type": "string", "maxLength": rules.MAX_TEXT, "description": "The item's text, plain, in the owner's intent (leading direction words removed)."},
                            "group": _GROUP_SCHEMA, "state": {"type": "string", "enum": list(inbox_filing.STATES), "description": "Default open."},
                            "ask": {"type": "object", "description": "With ask or state question: the typed questions, as task_manager_ask's context and questions.",
                                    "properties": _ASK_SCHEMA},
                            **_PERCEIVED_ASK_SCHEMA},
             "additionalProperties": False}},
         **own_list.SCHEMA},
        ["inbox_id", "items"], huddle_inbox_file, "agent",
    ),
    "task_manager_batch_run": ToolSpec(
        "Apply many huddle edits to ONE list in one call (prefer it for two or more); a lean answer per op. Each op is {op, item_id, ...} with the same fields as its own tool, checked as that tool checks them; op: add, update, reply, ask, move, mark_answered, delete, fork, progress. In order, not atomic; stop_on_error halts at a failure. list_id: all, a project id, or mine. Data: pipe table or ```kv.",
        {"list_id": _LIST_SCHEMA,
         "ops": {"type": "array", "minItems": 1, "maxItems": batch.MAX_OPS, "items": {
             "type": "object", "required": ["op"],
             "properties": {"op": {"type": "string", "enum": list(batch.OPS)}, "item_id": _ITEM_SCHEMA,
                            "text": {"type": "string", "description": "reply: " + FORMAT_HINT}, "state": {"type": "string"}, "kind": {"type": "string"},
                            "phase": {"type": "string", "enum": list(progress.PHASES), "description": "progress: the worker's phase."},
                            "note": {"type": "string", "description": "progress: a short note."},
                            "list": _LIST_SCHEMA, "group": _GROUP_SCHEMA, "expected_revision": {"type": "integer"}, **_TITLE_SCHEMA},
             "additionalProperties": True}},
         "stop_on_error": {"type": "boolean", "description": "Skip the remaining ops after the first failure. Default false."}},
        ["list_id", "ops"], huddle_batch, "agent",
    ),
    "task_manager_reply": ToolSpec(
        "Reply on an item's thread. info = fyi: it keeps the task in needs you (a read) until he reads it or the status changes; notify true also badges. answer = reply to HIS question (needs quote or quote_text). No looks: use task_manager_ask. His files[].path is ABSOLUTE. Data: pipe table or ```kv. Only a question or a review reaches the owner. offer_schedule {when,title}: one-click follow-up.",
        {"item": _ITEM_SCHEMA, "text": {"type": "string", "maxLength": rules.MAX_MESSAGE, "description": FORMAT_HINT},
         "kind": {"type": "string", "enum": list(kinds.REPLY_KINDS),
                  "description": "info (fyi, not unread unless notify), answer (replying to a question the owner asked; needs quote or quote_text) or attention (RETIRED: read as an info with notify true). Omitted: info."},
         **_NOTIFY_SCHEMA,
         "quote": _QUOTE_SCHEMA, "quote_text": _QUOTE_TEXT_SCHEMA,
         "action": {**_ACTION_SCHEMA, "description": "RETIRED (the look). answer, tick and push are refused (use task_manager_ask, or task_manager_update with review_action); read and none are read as notify true."},
         "changes": {"type": "boolean", "description": "Legacy, no effect (R92): the owner's reply on a review or done item already moved it to open. Answer a question with this reply, then return the item with task_manager_update state review (or done, for a task he had ticked); for changes, work them."},
         "offer_schedule": {"type": "object", "properties": {"when": {"type": "string"}, "title": {"type": "string", "maxLength": schedule_offer.MAX_TITLE}},
                            "required": ["when", "title"], "additionalProperties": False, "description": SCHEDULE_OFFER_HINT},
         **reply_paths.SCHEMA, **steer.NOT_A_QUESTION_SCHEMA, **_MARKER_SCHEMA, **_LEAN_SCHEMA, **own_list.SCHEMA, **dnd_gate.SCHEMA},
        ["item", "text"], huddle_reply, "agent", pane_only_args=(reply_paths.FIELD,),
    ),
}


TOOLS.update({**mcp_lead.TOOLS, **mcp_file_remove.TOOLS})

TOOLS = {name: dataclasses.replace(spec, handler=your_items.with_your_items(spec.handler, _caller_key)) for name, spec in TOOLS.items()}
