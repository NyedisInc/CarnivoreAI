
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Optional
from urllib.parse import urlencode

import structlog

from src.core.federation import peer_fanout
from src.core.federation.peer_fanout import PeerAnswer, unavailable_marker
from src.core.hosts.ddl import LOCAL_HOST_KEY, LOCAL_HOST_LABEL
from src.core.deepsearch.query import SEARCH_QUERY_MAX_CHARS
from src.core.stream_redactor import redact_whole

logger = structlog.get_logger()

PEER_PATH = "/deepsearch/peer-search"
CONTEXT_PATH = "/deepsearch/peer-context"
MAX_CONTEXT_TEXT = 100_000
MAX_CONTEXT_MESSAGES = 120
KINDS = ("user", "assistant", "tool", "summary")
FILE_KINDS = ("conversation", "subagent")
MAX_GROUPS = 50
MAX_HITS = 10
MAX_TEXT = 2000
MAX_COUNT = 1_000_000
MAX_SCORE = 1e12
NOT_READY_KEY = "not_ready"
PEER_MIN_TERM_CHARS = 3
PEER_MAX_INFLIGHT = 2


def _encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or not _encodable(value):
        return None
    return redact_whole(value)[:MAX_TEXT]


def _count(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT else None


def _counts(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(k)[:32]: v for k, v in list(value.items())[:16] if _count(v) is not None and _encodable(str(k))}


def _bookmark(raw: Any) -> Optional[Dict[str, Any]]:
    at = _text(raw.get("at")) if isinstance(raw, dict) else None
    return {"id": None, "label": _text(raw.get("label")) or "", "at": at} if at else None


def _hit(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    snippet = _text(raw.get("snippet"))
    if snippet is None:
        return None
    score = raw.get("score")
    if score is not None and not (isinstance(score, (int, float)) and not isinstance(score, bool) and -MAX_SCORE <= score <= MAX_SCORE):
        return None
    return {"line": _count(raw.get("line")), "kind": raw["kind"], "snippet": snippet, "score": score,
            "file_kind": raw.get("file_kind") if raw.get("file_kind") in FILE_KINDS else "conversation",
            "at": _text(raw.get("at")), "bookmark": _bookmark(raw.get("bookmark"))}


def clean_group(raw: Any) -> Dict[str, Any]:
    cid = raw.get("conversation_id") if isinstance(raw, dict) else None
    if not isinstance(cid, str) or not cid or len(cid) > 128 or not _encodable(cid):
        return {}
    matches = _count(raw.get("matches"))
    hits = [h for h in (_hit(x) for x in (raw.get("hits") if isinstance(raw.get("hits"), list) else [])[:MAX_HITS]) if h]
    return {"conversation_id": cid, "matches": matches if matches is not None else len(hits),
            "by_kind": _counts(raw.get("by_kind")), "by_file_kind": _counts(raw.get("by_file_kind")),
            "session_uuid": None, "session": _text(raw.get("session")), "project_id": None, "project": _text(raw.get("project")),
            "first_prompt": _text(raw.get("first_prompt")), "working_dir": None, "last_active": _text(raw.get("last_active")),
            "family": _text(raw.get("family")), "hits": hits}


def clean_context(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("messages"), list):
        return {}
    messages = []
    for item in raw["messages"][:MAX_CONTEXT_MESSAGES]:
        if not isinstance(item, dict) or item.get("kind") not in KINDS or _count(item.get("line")) is None:
            continue
        text = item.get("text")
        if not isinstance(text, str) or not _encodable(text):
            continue
        messages.append({"line": item["line"], "kind": item["kind"], "role": item["kind"], "text": redact_whole(text)[:MAX_CONTEXT_TEXT],
                         "at": _text(item.get("at")), "uuid": None})
    marks = []
    for mark in (raw.get("bookmarks") if isinstance(raw.get("bookmarks"), list) else [])[:MAX_CONTEXT_MESSAGES]:
        bookmark = _bookmark(mark)
        if bookmark is not None:
            marks.append({**bookmark, "after_line": _count(mark.get("after_line"))})
    anchor = _count(raw.get("anchor"))
    return {"file_kind": raw.get("file_kind") if raw.get("file_kind") in FILE_KINDS else "conversation", "anchor": anchor,
            "messages": messages, "has_before": raw.get("has_before") is True, "has_after": raw.get("has_after") is True,
            "bookmarks": marks}


async def context_from(state_dir: Path, host_key: str, params: Dict[str, Any]) -> PeerAnswer:
    from src.core.db import connect, db_path_for  # noqa: PLC0415

    path = f"{CONTEXT_PATH}?{urlencode({k: v for k, v in params.items() if v is not None})}"
    answers = await peer_fanout.ask_peers(path, lambda: connect(db_path_for(state_dir), create=False), only=host_key)
    return answers[0] if answers else PeerAnswer(host_key, host_key, None, "unknown_computer")


def not_ready_answer(query: str) -> Dict[str, Any]:
    return {"query": query, "total_conversations": 0, "total_matches": 0, "groups": [], NOT_READY_KEY: True}


def peer_query(q: str) -> str:
    from src.core.deepsearch.query import tokens_of  # noqa: PLC0415

    return " ".join(t for t in tokens_of(q) if len(t) >= PEER_MIN_TERM_CHARS)


def export(local: Dict[str, Any]) -> Dict[str, Any]:
    groups = [g for g in (clean_group(x) for x in local.get("groups", [])[:MAX_GROUPS]) if g]
    return {"query": local.get("query", ""), "total_conversations": local.get("total_conversations", 0),
            "total_matches": local.get("total_matches", 0), "groups": groups}


def merge(local: Dict[str, Any], answers: List[PeerAnswer]) -> Dict[str, Any]:
    if not answers:
        return {**local, "peer_unavailable": []}
    mine = [{**g, "host_key": LOCAL_HOST_KEY, "host_label": LOCAL_HOST_LABEL} for g in local.get("groups", [])]
    seen = {g["conversation_id"]: g for g in mine}
    lanes, bad, extra_matches = [mine], [], 0
    for a in answers:
        if a.data is None:
            continue
        if isinstance(a.data, dict) and a.data.get(NOT_READY_KEY) is True:
            bad.append(PeerAnswer(a.host_key, a.label, None, NOT_READY_KEY))
            continue
        raw = a.data.get("groups") if isinstance(a.data, dict) else None
        if not isinstance(raw, list):
            bad.append(PeerAnswer(a.host_key, a.label, None, "bad_answer"))
            continue
        try:
            cleaned = [g for g in (clean_group(item) for item in raw[:MAX_GROUPS]) if g]
        except Exception as exc:  # noqa: BLE001
            logger.warning("deepsearch_peer_answer_dropped", peer=a.host_key, error_type=type(exc).__name__)
            bad.append(PeerAnswer(a.host_key, a.label, None, "bad_answer"))
            continue
        fresh = []
        for group in cleaned:
            twin = seen.get(group["conversation_id"])
            if twin is not None:
                twin.setdefault("also_on", []).append(a.label)
                continue
            group.update(host_key=a.host_key, host_label=a.label)
            seen[group["conversation_id"]] = group
            fresh.append(group)
            extra_matches += group["matches"]
        lanes.append(fresh)
    groups = [lane[i] for i in range(max(len(x) for x in lanes)) for lane in lanes if i < len(lane)]
    own_total = local.get("total_conversations", 0)
    return {**local, "groups": groups, "count": len(groups), "local_total_conversations": own_total,
            "total_conversations": own_total + sum(len(x) for x in lanes[1:]),
            "total_matches": local.get("total_matches", 0) + extra_matches,
            "peer_unavailable": unavailable_marker([a for a in answers if a.data is None] + bad)}


def peers_wanted(project: Optional[str], offset: int) -> bool:
    return offset == 0 and not (project and project.strip().isdigit())


def _path(q: str, kinds: Optional[List[str]], project: Optional[str], conversation_id: Optional[str], limit: int, per_group: int) -> str:
    params = {"q": q[:SEARCH_QUERY_MAX_CHARS], "limit": limit, "per_group": per_group, **({"kinds": ",".join(kinds)} if kinds else {}),
              **({"project": project} if project else {}), **({"conversation_id": conversation_id} if conversation_id else {})}
    return f"{PEER_PATH}?{urlencode(params)}"


async def _ask(state_dir: Path, path: str) -> List[PeerAnswer]:
    from src.core.db import connect, db_path_for  # noqa: PLC0415

    return await peer_fanout.ask_peers(path, lambda: connect(db_path_for(state_dir), create=False))


async def with_peers(state_dir: Path, local: Awaitable[Dict[str, Any]], *, q: str, kinds: Optional[List[str]],
                     project: Optional[str], conversation_id: Optional[str], limit: int, per_group: int) -> Dict[str, Any]:
    answer, answers = await asyncio.gather(local, _ask(state_dir, _path(q, kinds, project, conversation_id, limit, per_group)))
    return await asyncio.to_thread(merge, answer, answers)


async def peers_only(state_dir: Path, *, q: str, kinds: Optional[List[str]], project: Optional[str],
                     conversation_id: Optional[str], limit: int, per_group: int) -> Dict[str, Any]:
    answers = await _ask(state_dir, _path(q, kinds, project, conversation_id, limit, per_group))
    return await asyncio.to_thread(merge, {"groups": [], "total_conversations": 0, "total_matches": 0}, answers)

