
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.deepsearch.reader import ConversationIndex

MAX_QUERY_CHARS: int = 500
SCOPE_LOCAL, SCOPE_PEERS, SCOPE_ALL = "local", "peers", "all"
LIMIT_DEFAULT: int = 20
LIMIT_MAX: int = 50
PER_GROUP_DEFAULT: int = 3
PER_GROUP_MAX: int = 10
SUGGEST_LIMIT_DEFAULT: int = 8
SUGGEST_LIMIT_MAX: int = 20
SUGGEST_QUERY_MAX: int = 200
KINDS: tuple = ("user", "assistant", "tool", "summary")
CONTEXT_DEFAULT: int = 20
CONTEXT_MAX: int = 50
FILE_KINDS: tuple = ("conversation", "subagent")


def parse_kinds(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None or not raw.strip():
        return None
    return [k.strip() for k in raw.split(",") if k.strip()]


async def search(index: ConversationIndex, q: str, *, kinds: Optional[List[str]] = None, project: Optional[str] = None,
                 conversation_id: Optional[str] = None, limit: int = LIMIT_DEFAULT, offset: int = 0,
                 per_group: int = PER_GROUP_DEFAULT, scope: str = SCOPE_ALL) -> Dict[str, Any]:
    if scope == SCOPE_PEERS:
        return await index.search_peers(q, kinds=kinds, project=project, conversation_id=conversation_id,
                                        limit=limit, offset=offset, per_group=per_group)
    answer = await index.search(q, kinds=kinds, project=project, conversation_id=conversation_id,
                                limit=limit, offset=offset, per_group=per_group, peers=scope == SCOPE_ALL)
    answer["ingest"] = await index.status()
    return answer


async def context(index: ConversationIndex, conversation_id: str, *, file_kind: str = "conversation", line: Optional[int] = None,
                  at: Optional[str] = None, before_line: Optional[int] = None, after_line: Optional[int] = None,
                  before: int = CONTEXT_DEFAULT, after: int = CONTEXT_DEFAULT, host_key: Optional[str] = None) -> Dict[str, Any]:
    return await index.context(conversation_id, file_kind=file_kind, line=line, at=at, before_line=before_line,
                               after_line=after_line, before=before, after=after, host_key=host_key)


async def suggest(index: ConversationIndex, prefix: str, *, limit: int = SUGGEST_LIMIT_DEFAULT) -> Dict[str, Any]:
    return await index.suggest(prefix, limit=limit)
