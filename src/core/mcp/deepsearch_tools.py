
from __future__ import annotations

from typing import Any

from src.core.deepsearch import reader, service
from src.core.deepsearch.reader import ContextNotFound, ConversationsUnavailable, InvalidSearch
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.read_tools import scrub


def _int(args: dict, key: str, default: int, top: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError(f"{key} must be a positive integer")
    return min(value, top)


async def conversation_search(manager: Any, caller: AgentCaller, args: dict) -> dict:
    q = args.get("q")
    if not isinstance(q, str) or not q.strip() or len(q) > service.MAX_QUERY_CHARS:
        raise ToolError(f"q is required: 1 to {service.MAX_QUERY_CHARS} characters")
    kinds = args.get("kinds")
    if kinds is not None and (not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds)):
        raise ToolError(f"kinds must be a list of {', '.join(service.KINDS)}")
    project = args.get("project")
    if project is not None and not isinstance(project, (str, int)):
        raise ToolError("project must be a project name or id")
    try:
        answer = await service.search(reader.default_index(), q.strip(), kinds=kinds or None,
                                      project=str(project) if project is not None else None,
                                      limit=_int(args, "limit", service.LIMIT_DEFAULT, service.LIMIT_MAX),
                                      per_group=_int(args, "per_group", service.PER_GROUP_DEFAULT, service.PER_GROUP_MAX))
    except InvalidSearch as exc:
        raise ToolError(str(exc)) from exc
    except ConversationsUnavailable as exc:
        raise ToolError(f"the search index is unavailable: {exc}") from exc
    return _ok(scrub(answer))


async def deepsearch_context_get(manager: Any, caller: AgentCaller, args: dict) -> dict:
    conversation_id = args.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise ToolError("conversation_id is required")
    anchors = {k: args[k] for k in ("line", "at", "before_line", "after_line") if args.get(k) is not None}
    if len(anchors) != 1:
        raise ToolError("name exactly one of line, at, before_line, after_line")
    file_kind = args.get("file_kind", "conversation")
    if file_kind not in service.FILE_KINDS:
        raise ToolError(f"file_kind must be one of {', '.join(service.FILE_KINDS)}")
    host_key = args.get("host_key")
    try:
        answer = await service.context(reader.default_index(), conversation_id, file_kind=file_kind,
                                       host_key=host_key if isinstance(host_key, str) else None,
                                       before=_int(args, "before", service.CONTEXT_DEFAULT, service.CONTEXT_MAX),
                                       after=_int(args, "after", service.CONTEXT_DEFAULT, service.CONTEXT_MAX), **anchors)
    except ContextNotFound as exc:
        raise ToolError(str(exc)) from exc
    except ConversationsUnavailable as exc:
        raise ToolError(f"the search index is unavailable: {exc}") from exc
    return _ok(scrub(answer))


READ_TOOLS: dict = {
    "conversation_search": (
        "Search every saved conversation, both harnesses; subagent transcripts too unless the owner "
        "limited the index (ingest.scope). Answers conversations ranked best first, with redacted hits "
        "and snippets, plus the ingest state. Paired computers' conversations are merged in, tagged "
        "host_key and host_label (also_on when on both); peer_unavailable names one that did not answer.",
        {"q": {"type": "string", "minLength": 1, "maxLength": service.MAX_QUERY_CHARS},
         "kinds": {"type": "array", "items": {"type": "string", "enum": list(service.KINDS)}},
         "project": {"type": ["string", "integer"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": service.LIMIT_MAX},
         "per_group": {"type": "integer", "minimum": 1, "maximum": service.PER_GROUP_MAX}},
        ["q"], conversation_search,
    ),
    "deepsearch_context_get": (
        "Read the conversation around one deep search hit: a window of messages (role, text, time), oldest first, "
        "through the same filter and redaction as conversation_search, plus the bookmarks inside it. Anchor with the "
        "hit's line, or at (an ISO moment), and page with before_line / after_line (the first / last line already "
        "read). host_key reads a conversation held by a paired computer.",
        {"conversation_id": {"type": "string", "minLength": 1, "maxLength": 128},
         "line": {"type": "integer", "minimum": 0}, "at": {"type": "string", "maxLength": 64},
         "before_line": {"type": "integer", "minimum": 0}, "after_line": {"type": "integer", "minimum": 0},
         "file_kind": {"type": "string", "enum": list(service.FILE_KINDS)},
         "before": {"type": "integer", "minimum": 1, "maximum": service.CONTEXT_MAX},
         "after": {"type": "integer", "minimum": 1, "maximum": service.CONTEXT_MAX},
         "host_key": {"type": "string", "maxLength": 128}},
        ["conversation_id"], deepsearch_context_get,
    ),
}
