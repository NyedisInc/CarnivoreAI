
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.project_history.activity import activity_days, is_automated
from src.core.project_history.classify import (
    HISTORY_STATES,
    STATE_RUNNING,
    activity_at,
    display_title,
    is_agent_row,
    iso,
    parse_stamp,
    row_state,
)

NO_PROJECT = "none"

SORT_RECENT = "recent"
SORT_NAME = "name"
SORT_OLDEST = "oldest"
SORTS: Tuple[str, ...] = (SORT_RECENT, SORT_NAME, SORT_OLDEST)

PROJECT_STATES: Tuple[str, ...] = ("all", "active", "archived")

UNKNOWN_AGENT = "unknown"

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
DEFAULT_SESSION_LIMIT = 10
MAX_SESSION_LIMIT = 500
MAX_QUERY_CHARS = 200


class HistoryQueryError(ValueError):
    """A request parameter could not be understood. The message names it."""


@dataclass(frozen=True)
class HistoryQuery:

    q: str = ""
    states: FrozenSet[str] = frozenset()
    agents: FrozenSet[str] = frozenset()
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    project_state: str = "all"
    include_empty: bool = True
    project: Optional[str] = None
    sort: str = SORT_RECENT
    offset: int = 0
    limit: int = DEFAULT_LIMIT
    session_limit: int = DEFAULT_SESSION_LIMIT

    @classmethod
    def parse(
        cls,
        *,
        q: Optional[str] = None,
        state: Optional[str] = None,
        agent: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project_state: Optional[str] = None,
        include_empty: bool = True,
        project: Optional[str] = None,
        sort: Optional[str] = None,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        session_limit: int = DEFAULT_SESSION_LIMIT,
    ) -> "HistoryQuery":
        text = (q or "").strip()
        if len(text) > MAX_QUERY_CHARS:
            raise HistoryQueryError(f"q is longer than {MAX_QUERY_CHARS} characters")
        states = _csv(state)
        bad = sorted(states - set(HISTORY_STATES))
        if bad:
            raise HistoryQueryError(f"state has unknown values: {', '.join(bad)}")
        since_at = _bound("since", since)
        until_at = _bound("until", until)
        if since_at and until_at and since_at > until_at:
            raise HistoryQueryError("since is after until")
        pstate = (project_state or "all").strip()
        if pstate not in PROJECT_STATES:
            raise HistoryQueryError(f"project_state must be one of {', '.join(PROJECT_STATES)}")
        order = (sort or SORT_RECENT).strip()
        if order not in SORTS:
            raise HistoryQueryError(f"sort must be one of {', '.join(SORTS)}")
        target = (project or "").strip() or None
        if target is not None and target != NO_PROJECT and not target.isdigit():
            raise HistoryQueryError("project must be a project id or 'none'")
        if offset < 0:
            raise HistoryQueryError("offset must not be negative")
        if not 1 <= limit <= MAX_LIMIT:
            raise HistoryQueryError(f"limit must be between 1 and {MAX_LIMIT}")
        if not 1 <= session_limit <= MAX_SESSION_LIMIT:
            raise HistoryQueryError(f"session_limit must be between 1 and {MAX_SESSION_LIMIT}")
        return cls(
            q=text.casefold(),
            states=frozenset(states),
            agents=frozenset(a.casefold() for a in _csv(agent)),
            since=since_at,
            until=until_at,
            project_state=pstate,
            include_empty=bool(include_empty),
            project=target,
            sort=order,
            offset=int(offset),
            limit=int(limit),
            session_limit=int(session_limit),
        )


def _csv(value: Optional[str]) -> set:
    return {part.strip() for part in (value or "").split(",") if part.strip()}


def _bound(name: str, value: Optional[str]) -> Optional[datetime]:
    if value is None or not value.strip():
        return None
    stamp = parse_stamp(value)
    if stamp is None:
        raise HistoryQueryError(f"{name} is not an ISO date or datetime")
    return stamp


@dataclass(frozen=True)
class RowFacts:

    family_of: Callable[[Mapping[str, Any]], Optional[str]]
    live_id_of: Callable[[Mapping[str, Any]], Optional[str]] = lambda _row: None
    transcripts: FrozenSet[str] = frozenset()
    theme_of: Callable[[Mapping[str, Any]], Optional[str]] = lambda _project: None


def _session_payload(row: Mapping[str, Any], facts: RowFacts, family: Optional[str]) -> Dict[str, Any]:
    state = row_state(row)
    conversation = row.get("claude_session_uuid") or None
    return {
        "session_uuid": str(row.get("session_uuid")),
        "row_id": row.get("id"),
        "title": display_title(row),
        "label": row.get("title"),
        "tmux_name": row.get("tmux_name"),
        "host_key": row.get("host_key") or "local",
        "state": state,
        "lifecycle": row.get("lifecycle"),
        "lifecycle_source": row.get("lifecycle_source"),
        "archived_at": row.get("archived_at"),
        "agent_type": row.get("agent_type"),
        "agent_family": family,
        "claude_session_uuid": conversation,
        "has_transcript": bool(conversation) and conversation in facts.transcripts,
        "created_at": row.get("created_at"),
        "last_seen_running_at": row.get("last_seen_running_at"),
        "last_work_at": row.get("last_work_at"),
        "last_activity_at": iso(activity_at(row)),
        "working_dir": row.get("working_dir"),
        "origin": row.get("origin"),
        "kind": row.get("kind"),
        "fork_kind": row.get("fork_kind"),
        "live_session_id": facts.live_id_of(row) if state == STATE_RUNNING else None,
    }


def _project_payload(project: Mapping[str, Any], facts: RowFacts) -> Dict[str, Any]:
    return {
        "id": project.get("id"),
        "name": project.get("display_name") or project.get("name") or "",
        "root": project.get("root"),
        "description": project.get("description"),
        "archived_at": project.get("archived_at"),
        "last_opened_at": project.get("last_opened_at"),
        "created_at": project.get("created_at"),
        "default_theme": facts.theme_of(project),
        "company_id": project.get("company_id"),
        "company_name": project.get("company_name"),
        "has_image": bool(project.get("has_image")),
        "image_rev": project.get("image_rev"),
        "storage": project.get("storage"),
        "pack_state": project.get("pack_state"),
        "moved_to_label": project.get("moved_to_label") or project.get("moved_to_install_id"),
    }


def _matches(needle: str, values: Iterable[Any]) -> bool:
    if not needle:
        return True
    return any(isinstance(v, str) and needle in v.casefold() for v in values)


def _project_passes(project: Optional[Mapping[str, Any]], query: HistoryQuery) -> bool:
    archived = bool(project and project.get("archived_at"))
    if query.project_state == "active":
        return not archived
    if query.project_state == "archived":
        return archived
    return True


def build_history(
    projects: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    query: HistoryQuery,
    facts: RowFacts,
) -> Dict[str, Any]:
    by_id = {p.get("id"): p for p in projects if p.get("id") is not None}
    groups: Dict[Any, Dict[str, Any]] = {}
    agents: set = set()
    state_counts = {state: 0 for state in HISTORY_STATES}

    def group_for(key: Any) -> Dict[str, Any]:
        if key not in groups:
            project = by_id.get(key) if key != NO_PROJECT else None
            groups[key] = {"project": project, "rows": [], "latest": None}
        return groups[key]

    project_hit = {
        key: _matches(query.q, (p.get("display_name"), p.get("name"), p.get("root")))
        for key, p in by_id.items()
    }

    for row in rows:
        key = row.get("project_id") if row.get("project_id") in by_id else NO_PROJECT
        if query.project is not None and str(key) != query.project:
            continue
        project = by_id.get(key)
        family = facts.family_of(row)
        agents.add(family or UNKNOWN_AGENT)
        if not _project_passes(project, query):
            continue
        if query.q and not (project_hit.get(key, False) or _matches(
            query.q,
            (row.get("title"), row.get("claude_title"), row.get("tmux_name"),
             row.get("agent_type"), family, row.get("claude_session_uuid"), row.get("working_dir")),
        )):
            continue
        if query.agents and (family or UNKNOWN_AGENT).casefold() not in query.agents:
            continue
        when = activity_at(row)
        if query.since and (when is None or when < query.since):
            continue
        if query.until and (when is None or when > query.until):
            continue
        state = row_state(row)
        state_counts[state] += 1
        if query.states and state not in query.states:
            continue
        group = group_for(key)
        group["rows"].append((when, row, family))
        if is_agent_row(row, family) and when and (group["latest"] is None or when > group["latest"]):
            group["latest"] = when

    if query.include_empty:
        for key, project in by_id.items():
            if query.project is not None and str(key) != query.project:
                continue
            if _project_passes(project, query) and project_hit.get(key, False):
                group_for(key)

    ordered = _order_groups(list(groups.items()), query.sort)
    total = len(ordered)
    page = ordered[query.offset: query.offset + query.limit]
    out_groups = [_group_payload(key, group, query, facts) for key, group in page]
    end = query.offset + len(page)
    return {
        "total": total,
        "offset": query.offset,
        "limit": query.limit,
        "next_offset": end if end < total else None,
        "groups": out_groups,
        "facets": {"agents": sorted(agents), "states": state_counts},
    }


def _group_latest(group: Mapping[str, Any]) -> Optional[datetime]:
    project = group.get("project") or {}
    stamps = [group.get("latest"), parse_stamp(project.get("last_opened_at"))]
    known = [s for s in stamps if s is not None]
    return max(known) if known else None


def _order_groups(items: List[Tuple[Any, Dict[str, Any]]], sort: str) -> List[Tuple[Any, Dict[str, Any]]]:
    named = [item for item in items if item[0] != NO_PROJECT]
    rest = [item for item in items if item[0] == NO_PROJECT]
    if sort == SORT_NAME:
        named.sort(key=lambda it: ((it[1]["project"] or {}).get("display_name") or "").casefold())
    elif sort == SORT_OLDEST:
        named.sort(key=lambda it: (parse_stamp((it[1]["project"] or {}).get("created_at")) is None,
                                   parse_stamp((it[1]["project"] or {}).get("created_at")) or datetime.min,
                                   it[0]))
    else:
        named.sort(key=lambda it: (_group_latest(it[1]) is None,
                                   -(_group_latest(it[1]).timestamp() if _group_latest(it[1]) else 0)))
    return named + rest


def _group_payload(key: Any, group: Mapping[str, Any], query: HistoryQuery, facts: RowFacts) -> Dict[str, Any]:
    entries = list(group["rows"])
    oldest_first = query.sort == SORT_OLDEST
    entries.sort(key=lambda e: (e[0] is None, (e[0].timestamp() if e[0] else 0) * (1 if oldest_first else -1)))
    counts = {state: 0 for state in HISTORY_STATES}
    automated_counts = {state: 0 for state in HISTORY_STATES}
    agent_rows = [row for _when, row, family in entries if is_agent_row(row, family)]
    for row in agent_rows:
        counts[row_state(row)] += 1
        if is_automated(row):
            automated_counts[row_state(row)] += 1
    project = group.get("project")
    return {
        "key": str(key),
        "project": _project_payload(project, facts) if project else None,
        "session_total": len(entries),
        "counts": counts,
        "automated_counts": automated_counts,
        "activity_days": activity_days(agent_rows),
        "last_activity_at": iso(_group_latest(group)),
        "sessions": [_session_payload(row, facts, family) for _when, row, family in entries[: query.session_limit]],
    }
