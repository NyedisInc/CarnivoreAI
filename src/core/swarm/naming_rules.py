
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

from src.core.swarm import memory
from src.core.swarm.names import shown_name

MAX_NAME_CHARS = 25
TASK_EXAMPLES = ("fixing node colors", "create swarm mockups", "do full security review")
FEATURE_EXAMPLES = ("UXUI", "Security Analyst", "Style Guide", "Icon Design", "Settings Menus", "File Changes")
_PREFIX = re.compile(r"^(feat|fix|tweak)\b", re.IGNORECASE)
_FOLD = re.compile(r"[^0-9a-z]+")

RULES_TEXT = (
    f"Agent names: at most {MAX_NAME_CHARS} characters, and never starting with feat, fix or tweak. A task agent is named by "
    f"its general task in a few plain words (for example {', '.join(TASK_EXAMPLES)}). A feature agent is named by the specialty "
    f"it owns, a domain and never one piece of work (for example {', '.join(FEATURE_EXAMPLES)}). Route new work to a live feature "
    "agent whose specialty fits first; spawn a new agent only when nothing fits.")


class NameRefused(ValueError):
    pass


def check_name(raw: Any, what: str = "name") -> str:
    if raw is not None and not isinstance(raw, str):
        raise NameRefused(f"{what} must be text")
    name = " ".join((raw or "").split())
    if not name:
        raise NameRefused(f"{what} is required. {RULES_TEXT}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise NameRefused(f"{what} cannot hold control characters")
    if len(name) > MAX_NAME_CHARS:
        raise NameRefused(f"{what} {name!r} is {len(name)} characters; the limit is {MAX_NAME_CHARS}. {RULES_TEXT}")
    prefix = _PREFIX.match(name)
    if prefix:
        raise NameRefused(f"{what} {name!r} starts with {prefix.group(1)!r}, a card-title prefix, not a name. {RULES_TEXT}")
    try:
        memory.refuse_secrets(name, f"agent {what}")
    except memory.SwarmFileError as exc:
        raise NameRefused(str(exc)) from None
    return name


def fold(text: Any) -> str:
    return _FOLD.sub("", str(text or "").casefold())


def _project_agents(conn: sqlite3.Connection, project_id: Optional[int], repo_dir: str) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM swarm_agents WHERE torn_down_at IS NULL AND (project_id = ? OR repo_dir = ?)",
                        (project_id if project_id is not None else -1, repo_dir)).fetchall()
    return [dict(r) for r in rows]


def specialist_for(conn: sqlite3.Connection, parent: Dict[str, Any], specialty: str) -> Optional[Dict[str, Any]]:
    key = fold(specialty)
    if not key:
        return None
    for agent in _project_agents(conn, parent.get("project_id"), parent["repo_dir"]):
        if agent["rank"] == "feature" and key in (fold(agent.get("specialty")), fold(agent["display_name"])):
            return agent
    return None


def name_holder(conn: sqlite3.Connection, agent: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    key = fold(name)
    for other in _project_agents(conn, agent.get("project_id"), agent["repo_dir"]):
        if other["id"] != agent["id"] and key in (fold(other["display_name"]), fold(shown_name(other))):
            return other
    return None


def former_names(agent: Dict[str, Any]) -> List[str]:
    try:
        names = json.loads(agent.get("former_names") or "[]")
    except ValueError:
        return []
    return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
