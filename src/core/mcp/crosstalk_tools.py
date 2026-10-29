
from __future__ import annotations

from typing import Any

from src.core.crosstalk import directory
from src.core.mcp import description_tools, lean_answers
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.read_tools import scrub


AGENTS, ROSTER = "agents", "roster"
LOOKUP_ARGS = frozenset({"query", "provider", "include_remote", "include_self", "limit"})
ROSTER_ARGS = frozenset(description_tools.ROSTER_PROPERTIES)


def _view(args: dict) -> str:
    view = args.get("view")
    if view is None:
        return ROSTER if ROSTER_ARGS & set(args) else AGENTS
    if view not in (AGENTS, ROSTER):
        raise ToolError(f"view must be {AGENTS} or {ROSTER}")
    return view


async def agents_lookup(manager: Any, caller: AgentCaller, args: dict) -> dict:
    view = _view(args)
    other = ROSTER_ARGS if view == AGENTS else LOOKUP_ARGS
    if (stray := sorted(other & set(args))):
        raise ToolError(f"{', '.join(stray)} belong to view {ROSTER if view == AGENTS else AGENTS}, not view {view}")
    if view == ROSTER:
        return await description_tools.ROSTER_HANDLER(manager, caller, {k: v for k, v in args.items() if k != "view"})
    if (unknown := sorted(set(args) - LOOKUP_ARGS - {"view"})):
        raise ToolError(f"agents_lookup does not take {', '.join(unknown)}")
    query, provider = args.get("query"), args.get("provider")
    for key, val in (("query", query), ("provider", provider)):
        if val is not None and not isinstance(val, str):
            raise ToolError(f"{key} must be text")
    for key in ("include_remote", "include_self"):
        if key in args and not isinstance(args[key], bool):
            raise ToolError(f"{key} must be true or false")
    limit = args.get("limit", 25)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ToolError("limit must be an integer from 1 to 100")
    result = await directory.lookup(
        manager, query=query, provider=provider, include_remote=args.get("include_remote", True),
        include_self=args.get("include_self", False), limit=limit,
        self_tmux=None if caller.external else caller.tmux_name)
    return _ok(scrub(result))


READ_TOOLS: dict = {
    "agents_lookup": (
        "Find agents by name (\"@Cv-Misc UI\"; case, spaces and dashes ignored), here and on paired computers: id (usable by every "
        "tool), name, provider, host, project, status; asleep means crosstalk_send wakes it. ambiguous true: pick by id. "
        "view roster instead lists this computer's sessions with descriptions and family (scope, has_description, project, company, detail).",
        {"view": {"type": "string", "enum": [AGENTS, ROSTER], "description": "agents (default): find by name. roster: list sessions with descriptions; implied by any roster argument"},
         "query": {"type": "string"}, "provider": {"type": "string", "description": "claude, codex, ..."},
         "include_remote": {"type": "boolean"}, "include_self": {"type": "boolean"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100}, **description_tools.ROSTER_PROPERTIES},
        [], agents_lookup),
}


async def crosstalk_send(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.crosstalk import bus
    result = await bus.send(manager, caller, to=args.get('to'), text=args.get('text'),
                              thread=args.get('thread'), in_reply_to=args.get('in_reply_to'),
                              expect_reply=args.get('expect_reply', False), task_item=args.get('task_item'))
    return result if 'content' in result else _ok(result)


async def crosstalk_reply(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.crosstalk import bus
    result = await bus.reply(manager, caller, message_id=args.get('message_id'), text=args.get('text'),
                             task_item=args.get('task_item'))
    return result if 'content' in result else _ok(result)


async def crosstalk_inbox(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.core.crosstalk import bus
    full = lean_answers.detail_flag(args)
    since = args.get('since', 0)
    if isinstance(since, bool) or not isinstance(since, (int, float)) or since < 0:
        raise ToolError('since must be a nonnegative timestamp')
    thread = args.get('thread')
    if thread is not None and not isinstance(thread, str):
        raise ToolError('thread must be a string')
    limit = args.get('limit', bus.INBOX_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= bus.INBOX_MAX:
        raise ToolError(f'limit must be a whole number from 1 to {bus.INBOX_MAX}')
    answer = await bus.inbox(manager, caller, since=since, thread=thread, limit=limit)
    return _ok(answer if full else lean_answers.crosstalk_inbox(answer))


def _cursor(args: dict, maximum: int, default: int) -> tuple[float | None, int]:
    before = args.get('before')
    if before is not None and (isinstance(before, bool) or not isinstance(before, (int, float)) or before < 0):
        raise ToolError('before must be a nonnegative timestamp')
    limit = args.get('limit', default)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ToolError(f'limit must be a whole number from 1 to {maximum}')
    return before, limit


async def crosstalk_thread(manager: Any, caller: AgentCaller, args: dict) -> dict:
    import asyncio
    from src.core.crosstalk import bus, history
    thread = args.get('thread')
    if not isinstance(thread, str) or not thread:
        raise ToolError('thread is required')
    before, limit = _cursor(args, history.MESSAGES_MAX, history.MESSAGES_LIMIT)
    identity = await bus.caller_identity(manager, caller)
    try:
        return _ok(await asyncio.to_thread(history.thread_messages, thread, participant=identity['key'],
                                           before=before, limit=limit))
    except history.HistoryError as exc:
        raise ToolError('no such thread for you') from exc


async def crosstalk_threads_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    import asyncio
    from src.core.crosstalk import bus, history
    session, project = args.get('session'), args.get('project')
    if session is not None and (not isinstance(session, str) or not session):
        raise ToolError('session must be a session id or uuid')
    if project is not None and (isinstance(project, bool) or not isinstance(project, int) or project < 1):
        raise ToolError('project must be a project id')
    before, limit = _cursor(args, history.THREADS_MAX, history.THREADS_LIMIT)
    identity = await bus.caller_identity(manager, caller)
    return _ok(await asyncio.to_thread(history.list_threads, session=session, project=project,
                                       participant=identity['key'], before=before, limit=limit))


async def crosstalk_wait(manager: Any, caller: AgentCaller, args: dict) -> dict:
    import asyncio
    from src.core.crosstalk import bus, store
    message_id, thread_id = args.get('message_id'), args.get('thread')
    if bool(message_id) == bool(thread_id):
        raise ToolError('give exactly one message_id or thread')
    timeout = args.get('timeout', 45)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 45:
        raise ToolError('timeout must be 0 to 45 seconds')
    identity = await bus.caller_identity(manager, caller)
    if message_id:
        item = await asyncio.to_thread(store.get, message_id)
        if item is None or identity['key'] not in (item['sender_key'], item['receiver_key']):
            raise ToolError('no such message for you')
        thread_id = item['thread']
    baseline = args.get('since', 0)
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or baseline < 0:
        raise ToolError('since must be a nonnegative timestamp')
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        generation = store.version()
        rows = await asyncio.to_thread(store.messages_for, identity['key'], since=baseline, thread=thread_id)
        if message_id:
            parent = await asyncio.to_thread(store.get, message_id)
            if parent and parent['status'] in ('expired', 'failed'):
                return _ok({'status': parent['status'], 'message': parent,
                            'replies': [r for r in rows if r['in_reply_to'] == message_id]})
            replies = [r for r in rows if r['in_reply_to'] == message_id]
            if replies:
                return _ok({'status': 'replied', 'replies': replies})
            if parent and parent['status'] == 'delivered' and not parent['expect_reply']:
                return _ok({'status': 'delivered', 'message': parent})
        elif rows:
            return _ok({'status': 'messages', 'messages': rows})
        remaining = deadline - loop.time()
        if remaining <= 0 or not await store.changed(remaining, generation):
            return _ok({'status': 'timeout', 'thread': thread_id})


READ_TOOLS.update({
    'crosstalk_inbox': ('Read your own crosstalk messages (full text, newest first) and idle-watch notices. detail true adds keys, epochs and delivery columns.',
        {'detail': {'type': 'boolean', 'description': 'every column instead of the lean default'}, 'since': {'type': 'number'}, 'thread': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'description': 'Newest first; default 20.'}}, [], crosstalk_inbox),
    'crosstalk_thread': ('Read a crosstalk thread only if you are a participant, oldest first; page back with before.',
        {'thread': {'type': 'string'}, 'before': {'type': 'number'},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}, ['thread'], crosstalk_thread),
    'crosstalk_threads_list': ('List your past crosstalk threads, newest first: both sides, project, count, last message. '
        'Filter by session or project; page with before (next_before).',
        {'session': {'type': 'string'}, 'project': {'type': 'integer', 'minimum': 1}, 'before': {'type': 'number'},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}}, [], crosstalk_threads_list),
    'crosstalk_wait': ('Wait up to 45 seconds for a reply or a thread message.',
        {'message_id': {'type': 'string'}, 'thread': {'type': 'string'},
         'since': {'type': 'number'}, 'timeout': {'type': 'number', 'minimum': 0, 'maximum': 45}},
        [], crosstalk_wait),
})

_TASK_ITEM = {'type': 'integer', 'minimum': 1, 'description': 'Task Manager item id this message concerns. Always pass it when the message is about a task; a reply inherits it.'}

WRITE_TOOLS: dict = {
    'crosstalk_send': ('Send a durable peer message by agent handle or id, with first-contact approval. An asleep agent (agents_lookup status) is woken on send once the owner approves; if the wake is refused or times out nothing is sent. The result carries a receipt: delivered, queued (on its way) or stuck (held by a dialog, failed or expired; reason says which), so never check pickup by hand.',
        {'to': {'type': 'string'}, 'text': {'type': 'string', 'maxLength': 20000},
         'thread': {'type': 'string'}, 'in_reply_to': {'type': 'string'},
         'expect_reply': {'type': 'boolean'}, 'task_item': _TASK_ITEM}, ['to', 'text'], crosstalk_send),
    'crosstalk_reply': ('Reply to one crosstalk message addressed to your current pane.',
        {'message_id': {'type': 'string'}, 'text': {'type': 'string', 'maxLength': 20000}, 'task_item': _TASK_ITEM},
        ['message_id', 'text'], crosstalk_reply),
}


async def agent_spawn(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from types import SimpleNamespace
    from pydantic import ValidationError
    from fastapi import HTTPException
    from src.api.agent_spawn_routes import spawn_for_caller
    from src.core.crosstalk.spawn import SpawnRequest

    if 'parent' in args:
        raise ToolError('parent is set by your authenticated pane')
    try:
        body = SpawnRequest.model_validate(args)
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc
    if manager.app is None:
        raise ToolError('spawn is unavailable on this transport')
    try:
        result = await spawn_for_caller(SimpleNamespace(app=manager.app), body, caller)
    except HTTPException as exc:
        detail = exc.detail
        raise ToolError(detail.get('message', str(detail)) if isinstance(detail, dict) else str(detail)) from exc
    return result if 'content' in result else _ok(result)


WRITE_TOOLS['agent_spawn'] = (
    'Start a visible Claude or Codex agent here or on a paired computer, assign its task through crosstalk, and receive its completion reply. '
    'The owner approves each spawn unless beast mode is armed. Limits: 5 live per caller, 20 total.',
    {'provider': {'type': 'string', 'enum': ['claude', 'codex']},
     'task': {'type': 'string', 'maxLength': 19000},
     'name': {'type': 'string'}, 'model': {'type': 'string'},
     'effort': {'type': 'string', 'enum': ['low', 'medium', 'high', 'xhigh', 'max']},
     'project': {'type': 'string'}, 'working_dir': {'type': 'string'},
     'peer': {'type': 'string'},
     'worktree': {'type': 'boolean'}, 'report_back': {'type': 'boolean'}},
    ['provider', 'task'], agent_spawn,
)
