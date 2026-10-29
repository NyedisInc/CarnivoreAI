
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

from src.core.swarm import stream_sources
from src.core.swarm.names import shown_name

KINDS = ("company", "project", "agent", "sysop", "owner")
OWNER_PATH: List[Dict[str, Any]] = [{"kind": "owner", "name": "you", "agent_id": None}]
SUMMARY_CHARS = 160
TASK_CHARS = 200
QUESTION_REF = "question:"
_SENTENCE_END = re.compile(r"[.?!](?=\s|$)")


def crumb(kind: str, name: str, agent_id: Optional[int]) -> Dict[str, Any]:
    return {"kind": kind, "name": name, "agent_id": agent_id}


def _live_agent(conn: sqlite3.Connection, rank: str, column: str, value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    row = conn.execute(f"SELECT id FROM swarm_agents WHERE rank = ? AND {column} = ? AND torn_down_at IS NULL ORDER BY id LIMIT 1",
                       (rank, value)).fetchone()
    return int(row[0]) if row else None


def path_for_agent(conn: sqlite3.Connection, agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    own = agent["id"] if agent.get("torn_down_at") is None else None
    if agent["rank"] == "alpha":
        return [crumb("sysop", agent["display_name"], own)]
    project = None
    if agent.get("project_id") is not None:
        project = conn.execute("SELECT id, display_name, company_id FROM projects WHERE id = ?", (agent["project_id"],)).fetchone()
    company_id = agent.get("company_id") if agent.get("company_id") is not None else (project["company_id"] if project else None)
    company = conn.execute("SELECT id, name FROM companies WHERE id = ?", (company_id,)).fetchone() if company_id is not None else None
    path: List[Dict[str, Any]] = []
    if company is not None:
        lead = own if agent["rank"] == "company" else _live_agent(conn, "company", "company_id", company["id"])
        path.append(crumb("company", company["name"], lead))
    if agent["rank"] == "company":
        return path or [crumb("company", shown_name(agent), own)]
    if project is not None:
        lead = own if agent["rank"] == "project" else _live_agent(conn, "project", "project_id", project["id"])
        path.append(crumb("project", project["display_name"], lead))
    if agent["rank"] == "project":
        return path or [crumb("project", shown_name(agent), own)]
    return path + [crumb("agent", agent["display_name"], own)]


def relive(conn: sqlite3.Connection, path: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids = [c["agent_id"] for c in path if c.get("agent_id") is not None]
    live = {r[0] for r in conn.execute(f"SELECT id FROM swarm_agents WHERE torn_down_at IS NULL AND id IN ({','.join('?' * len(ids))})",
                                       ids)} if ids else set()
    return [{**c, "agent_id": c["agent_id"] if c.get("agent_id") in live else None} for c in path]


def relive_leads(stored: List[Dict[str, Any]], now: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    live = {c["kind"]: c["agent_id"] for c in now if c["kind"] in ("company", "project")}
    return [{**c, "agent_id": live.get(c["kind"], c["agent_id"])} if c["kind"] in ("company", "project") else c for c in stored]


_SUMMARY_RULES = (
    (re.compile(r"`|\b\w+\(|[{}<>]|==|=>|->|::|\b[a-z0-9]+_[a-z0-9_]+\b"), "no code (backticks, calls, brackets or snake_case names)"),
    (re.compile(r"(?:^|\s)[~.]{0,2}/\w|\b[\w.-]+/[\w.-]+/|\b(?:src|client|web|tests|docs|scripts)/\w|\w/\w[\w.-]*\.[a-z]{1,5}\b|\b[\w-]+\.(?:py|js|ts|svelte|md|json|css|html|sh|toml|ya?ml|sql|txt)\b", re.I),
     "no file names or paths"),
    (re.compile(r"\bline \d+|\b[A-Za-z_][\w.]*:\d+\b|\bL\d+\b", re.I), "no line numbers"),
)


def summary_refusal(text: str) -> Optional[str]:
    flat = " ".join(text.split())
    end = _SENTENCE_END.search(flat)
    if end and flat[end.end():].strip():
        return "the summary must be one sentence the owner can answer without reading code; put the rest in question"
    for pattern, rule in _SUMMARY_RULES:
        if pattern.search(flat):
            return f"the summary must be one plain sentence with {rule}; say what the choice changes for the owner and put the details in question"
    return None


def summary_fallback(text: str) -> str:
    flat = " ".join(text.split())
    end = _SENTENCE_END.search(flat)
    return cut_at_word(flat[:end.end()] if end else flat, SUMMARY_CHARS)


def cut_at_word(text: str, cap: int) -> str:
    flat = " ".join(text.split())
    if len(flat) <= cap:
        return flat
    head = flat[:cap]
    cut = head.rsplit(" ", 1)[0] if " " in head else flat[:cap - 1]
    return cut.rstrip(" ,;:.") + "…"


def _agent_row(conn: sqlite3.Connection, agent_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM swarm_agents WHERE id = ?", (agent_id,)).fetchone()
    return dict(row) if row is not None else None


def question_card(conn: sqlite3.Connection, question_id: int) -> Optional[Dict[str, Any]]:
    q = conn.execute("SELECT * FROM swarm_questions WHERE id = ?", (question_id,)).fetchone()
    if q is None:
        return None
    names = {r[0]: r[1] for r in conn.execute("SELECT id, display_name FROM swarm_agents")}
    askers = []
    first: Optional[Dict[str, Any]] = None
    for r in conn.execute("SELECT agent_id, author_path FROM swarm_question_askers WHERE question_id = ? ORDER BY asked_at, agent_id",
                          (question_id,)):
        row = _agent_row(conn, r["agent_id"])
        first = first or row
        now = path_for_agent(conn, row) if row else []
        path = relive_leads(relive(conn, json.loads(r["author_path"])), now) if r["author_path"] else now
        live = row is not None and row.get("torn_down_at") is None
        askers.append({"agent_id": r["agent_id"] if live else None, "name": names.get(r["agent_id"], "an agent"), "author_path": path})
    return {"summary": q["summary"] or summary_fallback(q["text"]),
            "task": q["task"] or cut_at_word((first or {}).get("job") or "", TASK_CHARS),
            "details": q["text"], "askers": askers,
            "asked_at": stream_sources._epoch(q["created_at"])}


def _agent_for_session_key(conn: sqlite3.Connection, key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    row = conn.execute("SELECT a.* FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id WHERE s.session_uuid = ? "
                       "ORDER BY a.id DESC LIMIT 1", (key,)).fetchone()
    return dict(row) if row is not None else None


_ACTOR_EVENTS = ("reported", "answered", "escalated", "accepted", "spawned")


def event_actor(conn: sqlite3.Connection, entry: Dict[str, Any]) -> Any:
    event, agent_id = entry.get("event"), entry.get("agent_id")
    if event == "answered":
        by = str(entry.get("answered_by") or "")
        if by == "owner":
            return "owner"
        return int(by.split(":", 1)[1]) if by.startswith("agent:") and by.split(":", 1)[1].isdigit() else None
    if event in ("reported", "escalated"):
        return agent_id
    if event == "accepted" and entry.get("report_id") is not None:
        row = conn.execute("SELECT parent_id FROM swarm_reports WHERE id = ?", (entry["report_id"],)).fetchone()
        return row[0] if row else None
    if event == "spawned" and agent_id is not None:
        row = conn.execute("SELECT rank, parent_id FROM swarm_agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None:
            return None
        return "owner" if row[0] in ("project", "company") else row[1]
    return None


def annotate(conn: sqlite3.Connection, agent: Dict[str, Any], entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    own = path_for_agent(conn, agent)
    rows: Dict[int, Optional[Dict[str, Any]]] = {}

    def path_of(agent_id: Any) -> List[Dict[str, Any]]:
        if not isinstance(agent_id, int):
            return [dict(c) for c in own]
        if agent_id not in rows:
            rows[agent_id] = _agent_row(conn, agent_id)
        return path_for_agent(conn, rows[agent_id]) if rows[agent_id] else [dict(c) for c in own]

    for entry in entries:
        kind = entry.get("kind")
        if kind == "owner":
            entry["author_path"] = [dict(c) for c in OWNER_PATH]
        elif kind == "event" and entry.get("event") in _ACTOR_EVENTS:
            actor = event_actor(conn, entry)
            entry["author_path"] = [dict(c) for c in OWNER_PATH] if actor == "owner" else path_of(actor)
        elif kind == "traffic" and entry.get("direction") == "in":
            sender = _agent_for_session_key(conn, entry.get("peer_key"))
            entry["author_path"] = path_for_agent(conn, sender) if sender else [crumb("agent", str(entry.get("peer") or "an agent"), None)]
        elif kind == "card" and str((entry.get("item") or {}).get("swarm_ref") or "").startswith(QUESTION_REF):
            ref = str(entry["item"]["swarm_ref"])[len(QUESTION_REF):]
            block = question_card(conn, int(ref)) if ref.isdigit() else None
            if block is not None:
                entry["question"] = block
            entry["author_path"] = block["askers"][0]["author_path"] if block and block["askers"] else [dict(c) for c in own]
        elif kind == "agent" and "author_agent_id" in entry:
            entry["author_path"] = path_of(entry.pop("author_agent_id"))
        else:
            entry["author_path"] = [dict(c) for c in own]
        key = entry.pop("peer_key", None)
        if kind == "traffic":
            entry["peer_session_uuid"] = key or None
    return entries
