
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from src.core import session_sleep, session_store
from src.core.hosts.ddl import LOCAL_HOST_KEY

SCOPE_ONLINE = "online"
SCOPE_AROUND = "around"
SCOPE_ALL = "all"
SCOPES = (SCOPE_ONLINE, SCOPE_AROUND, SCOPE_ALL)

HAS_ANY = "any"
HAS_SHORT = "short"
HAS_LONG = "long"
HAS_NONE = "none"
HAS_MISSING = "missing"
HAS_DESCRIPTION = (HAS_ANY, HAS_SHORT, HAS_LONG, HAS_NONE, HAS_MISSING)

MAX_ROSTER_ROWS = 200
STATUS_STOPPED = "stopped"
STATUS_ASLEEP = "asleep"
STATUS_ARCHIVED = "archived"
WAKE_HINT = "archived: waking it is a deliberate act; ask the owner before you wake or message it"


class RosterRefused(ValueError):
    pass


@dataclass
class RosterContext:

    rows: List[Dict[str, Any]] = field(default_factory=list)
    projects: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    companies: Dict[int, Dict[str, Any]] = field(default_factory=dict)


def read_context(conn: sqlite3.Connection) -> RosterContext:
    rows = [r for r in session_store.list_sessions(conn, include_archived=True, include_automated=False)
            if (r.get("host_key") or LOCAL_HOST_KEY) == LOCAL_HOST_KEY]
    projects = {int(r[0]): {"id": int(r[0]), "name": r[1], "short_description": r[2], "long_description": r[3],
                            "archived_at": r[4], "company_id": r[5]}
                for r in conn.execute("SELECT id, display_name, short_description, description, archived_at, "
                                      "company_id FROM projects")}
    companies = {int(r[0]): {"id": int(r[0]), "name": r[1], "parent_id": r[2]}
                 for r in conn.execute("SELECT id, name, parent_id FROM companies")}
    return RosterContext(rows=rows, projects=projects, companies=companies)


def _company_chain(companies: Dict[int, Dict[str, Any]], company_id: Optional[int]) -> List[Dict[str, Any]]:
    chain: List[Dict[str, Any]] = []
    seen: set = set()
    current = company_id
    while current is not None and current not in seen and current in companies:
        seen.add(current)
        chain.append({"id": current, "name": companies[current]["name"]})
        current = companies[current]["parent_id"]
    return chain


def _family(ctx: RosterContext, project_id: Optional[int], detail: bool) -> Dict[str, Any]:
    project = ctx.projects.get(int(project_id)) if project_id is not None else None
    if project is None:
        return {"project": None, "company": None, "parent_companies": []}
    shown = {"id": project["id"], "name": project["name"], "short_description": project["short_description"],
             "archived": bool(project["archived_at"])}
    if detail:
        shown["long_description"] = project["long_description"]
    chain = _company_chain(ctx.companies, project["company_id"])
    return {"project": shown, "company": chain[0] if chain else None, "parent_companies": chain[1:]}


def _entry(ctx: RosterContext, row: Optional[Dict[str, Any]], info: Any, detail: bool) -> Dict[str, Any]:
    row = row or {}
    live = info is not None
    project_id = (info.project_id if live and info.project_id is not None else row.get("project_id"))
    family = _family(ctx, project_id, detail)
    tmux = (info.tmux_session if live else None) or row.get("tmux_name")
    label = ((info.label if live else None) or (row.get("title") or "").strip() or (row.get("claude_title") or "").strip()
             or tmux or row.get("session_uuid"))
    asleep = not live and session_sleep.is_asleep(row)
    archived_by = "session" if row.get("archived_at") else "project" if (family["project"] or {}).get("archived") else None
    status = (info.activity_status if live else STATUS_ARCHIVED if archived_by else STATUS_ASLEEP if asleep
              else STATUS_STOPPED)
    entry = {
        "id": info.session.id if live else row.get("session_uuid"),
        "session_uuid": row.get("session_uuid"),
        "tmux_name": tmux,
        "display_name": label,
        "agent_type": (info.agent_type if live else None) or row.get("agent_type"),
        "status": status,
        "live": live,
        "asleep": asleep,
        "archived": archived_by is not None,
        "short_description": row.get("short_description"),
        "family": family,
    }
    if detail:
        entry["long_description"] = row.get("long_description")
        entry["working_dir"] = (info.session.working_dir if live else None) or row.get("working_dir")
    if archived_by:
        entry.update(archived_by=archived_by, wake_hint=WAKE_HINT)
    return entry


def _matches_description(entry: Dict[str, Any], row: Optional[Dict[str, Any]], has: str) -> bool:
    short = bool((row or {}).get("short_description"))
    long_ = bool((row or {}).get("long_description"))
    return {HAS_ANY: True, HAS_SHORT: short, HAS_LONG: long_, HAS_NONE: not short and not long_,
            HAS_MISSING: not (short and long_)}[has]


def _named(value: Optional[str], ident: Optional[int], name: Optional[str]) -> bool:
    if value is None:
        return True
    text = value.strip()
    return (text.isdigit() and ident == int(text)) or (name or "").casefold() == text.casefold()


def build_roster(
    ctx: RosterContext,
    live_infos: Iterable[Any],
    *,
    scope: str = SCOPE_ONLINE,
    has_description: str = HAS_ANY,
    project: Optional[str] = None,
    company: Optional[str] = None,
    detail: bool = False,
) -> Dict[str, Any]:
    if scope not in SCOPES:
        raise RosterRefused(f"scope must be one of {', '.join(SCOPES)}")
    if has_description not in HAS_DESCRIPTION:
        raise RosterRefused(f"has_description must be one of {', '.join(HAS_DESCRIPTION)}")
    by_row = {int(r["id"]): r for r in ctx.rows}
    pairs: List[tuple] = []
    seen_rows: set = set()
    for info in live_infos:
        row = by_row.get(info.session_row_id) if info.session_row_id is not None else None
        if row is not None:
            seen_rows.add(int(row["id"]))
        pairs.append((row, info))
    if scope != SCOPE_ONLINE:
        pairs += [(r, None) for r in ctx.rows if int(r["id"]) not in seen_rows]
    out: List[Dict[str, Any]] = []
    for row, info in pairs:
        entry = _entry(ctx, row, info, detail)
        if scope == SCOPE_AROUND and not entry["live"] and (entry["archived"] or not entry["asleep"]):
            continue
        if not _matches_description(entry, row, has_description):
            continue
        fam = entry["family"]
        proj = fam["project"] or {}
        if project is not None and not _named(project, proj.get("id"), proj.get("name")):
            continue
        chain = ([fam["company"]] if fam["company"] else []) + fam["parent_companies"]
        if company is not None and not any(_named(company, c["id"], c["name"]) for c in chain):
            continue
        out.append(entry)
    answer: Dict[str, Any] = {
        "scope": scope,
        "filters": {"has_description": has_description, "project": project, "company": company, "detail": detail},
        "total": len(out), "truncated": len(out) > MAX_ROSTER_ROWS, "sessions": out[:MAX_ROSTER_ROWS],
    }
    if any(e["archived"] for e in answer["sessions"]):
        answer["note"] = "rows marked archived are put away on purpose: " + WAKE_HINT
    return answer
