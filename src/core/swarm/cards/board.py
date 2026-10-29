
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.swarm import author_path, body
from src.core.swarm.cards import port as card_port
from src.core.swarm.names import shown_name

_SCOPE = re.compile(r"^(sysop|project:[1-9][0-9]{0,9}|company:[1-9][0-9]{0,9})$")
SHARED_LIST = "all"
MINE_KINDS = frozenset({"owner", "owner_message", "session", "before_cards"})
FILTERS = ("all", "mine")
ARCHIVED = ("hide", "only", "all")
_COLUMNS = ("todo", "in_progress", "review", "done")
PARENT_HERE = "parent_of_children_here"


def valid_scope(scope: str) -> bool:
    return bool(_SCOPE.match(scope))


def scope_list_keys(conn: sqlite3.Connection, scope: str) -> List[Tuple[Optional[int], str]]:
    if not valid_scope(scope):
        raise ValueError(f"bad card scope {scope!r}")
    if scope.startswith("project:"):
        project_id = int(scope.split(":", 1)[1])
        return [(project_id, str(project_id))]
    if scope.startswith("company:"):
        company_id = int(scope.split(":", 1)[1])
        keys: List[Tuple[Optional[int], str]] = [
            (r["id"], str(r["id"])) for r in conn.execute(
                "SELECT id FROM projects WHERE company_id = ? AND archived_at IS NULL ORDER BY display_name COLLATE NOCASE, id", (company_id,))]
        keys += [(None, r["thread_key"]) for r in conn.execute(
            "SELECT thread_key FROM swarm_agents WHERE rank = 'company' AND company_id = ? AND torn_down_at IS NULL ORDER BY id", (company_id,))]
        return keys
    keys = [(r["id"], str(r["id"])) for r in conn.execute(
        "SELECT id FROM projects WHERE archived_at IS NULL ORDER BY display_name COLLATE NOCASE, id")]
    keys.append((None, SHARED_LIST))
    keys += [(None, r["thread_key"]) for r in conn.execute(
        "SELECT thread_key FROM swarm_agents WHERE rank IN ('alpha', 'company') AND torn_down_at IS NULL ORDER BY id")]
    seen: set = set()
    return [k for k in keys if not (k[1] in seen or seen.add(k[1]))]


def lane_names(conn: sqlite3.Connection, keys: Sequence[Tuple[Optional[int], str]]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for project_id, key in keys:
        if project_id is not None:
            row = conn.execute("SELECT display_name FROM projects WHERE id = ?", (project_id,)).fetchone()
            names[key] = row["display_name"] if row else f"project {project_id}"
        elif key == SHARED_LIST:
            row = conn.execute("SELECT display_name, rank FROM swarm_agents WHERE thread_key = ? AND torn_down_at IS NULL", (key,)).fetchone()
            names[key] = shown_name(dict(row)) if row else "shared"
        else:
            row = conn.execute("SELECT display_name, rank FROM swarm_agents WHERE thread_key = ? AND torn_down_at IS NULL", (key,)).fetchone()
            names[key] = shown_name(dict(row)) if row else key
    return names


def holder_names(conn: sqlite3.Connection, agent_ids: Sequence[int]) -> Dict[int, str]:
    ids = sorted(set(agent_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["id"]: shown_name(dict(r)) for r in conn.execute(f"SELECT id, display_name, rank FROM swarm_agents WHERE id IN ({marks})", ids)}


def name_holders(cards: Sequence[Dict[str, Any]], names: Mapping[int, str]) -> None:
    for card in cards:
        if card["holder"] is not None:
            card["holder"]["name"] = names.get(card["holder"]["agent_id"])
        if not card.get("summary"):
            card["summary"] = author_path.summary_fallback(card.get("text") or card.get("title") or "")


def archive_kept(card: Mapping[str, Any], archived: str) -> bool:
    gone = card.get("archived_at") is not None
    return archived == "all" or gone == (archived == "only")


def local_midnight(now: Optional[float] = None) -> float:
    moment = datetime.fromtimestamp(now) if now is not None else datetime.now()
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def is_mine(card: Mapping[str, Any]) -> bool:
    return card["parent"] is None and card["origin"]["kind"] in MINE_KINDS


def foreign_parent_ids(scope: str, cards: Sequence[Mapping[str, Any]]) -> List[int]:
    if scope.startswith("project:"):
        return []
    have = {c["id"] for c in cards}
    return sorted({c["parent"] for c in cards if c["parent"] is not None and c["parent"] not in have})


def sysop_owned(scope: str, parents: Sequence[Dict[str, Any]], sysop_lists: Sequence[str]) -> List[Dict[str, Any]]:
    if not scope.startswith("company:"):
        return list(parents)
    return [p for p in parents if p.get("project_id") is None and str(p["list_key"]) in sysop_lists]


def parent_copies(scope: str, cards: Sequence[Dict[str, Any]], parents: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    if scope.startswith("project:"):
        return {}
    by_id = {c["id"]: c for c in [*cards, *parents]}
    placed: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for child in cards:
        parent = by_id.get(child["parent"]) if child["parent"] is not None else None
        if parent is not None and parent["list_key"] != child["list_key"]:
            placed.setdefault(child["list_key"], {}).setdefault(parent["id"], {**parent, "lane_role": PARENT_HERE, "queue_index": None})
    return {key: list(copies.values()) for key, copies in placed.items()}


def compose(scope: str, filter: str, done_limit: int, keys: Sequence[Tuple[Optional[int], str]], names: Mapping[str, str],
            cards: Sequence[Dict[str, Any]], rules: Mapping[str, Mapping[str, Any]], win: Mapping[str, int], since: float,
            parents: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    kept = [{**c, "lane_role": None} for c in cards if filter == "all" or is_mine(c)]
    copies = parent_copies(scope, cards, parents)
    lanes: List[Dict[str, Any]] = []
    for project_id, key in keys:
        columns: Dict[str, List[Dict[str, Any]]] = {name: [] for name in _COLUMNS}
        for card in kept:
            if card["list_key"] == key:
                columns[card["column"]].append(card)
        for card in copies.get(key, []):
            if filter == "all" or is_mine(card):
                columns[card["column"]].append(card)
        counts = {name: len(columns[name]) for name in _COLUMNS}
        columns["done"] = sorted(columns["done"], key=lambda c: (c["updated_at"], c["id"]), reverse=True)[:done_limit]
        lanes.append({"project_id": project_id, "list_key": key, "name": names.get(key, key),
                      "rules": dict(rules.get(key, {})), "counts": counts, "columns": columns})
    return {"scope": scope, "filter": filter, "lanes": lanes,
            "win": {"through_review_today": win["through_review_today"], "in_review": win["in_review"], "since": since},
            "capacity": None}


async def board(scope: str, *, filter: str, done_limit: int, now: Optional[float] = None, archived: str = "hide") -> Dict[str, Any]:
    if filter not in FILTERS or archived not in ARCHIVED:
        raise ValueError(f"bad card filter {filter!r} / archived {archived!r}")
    port = card_port.get()
    keys = await body.run_db(lambda conn: scope_list_keys(conn, scope))
    names = await body.run_db(lambda conn: lane_names(conn, keys))
    list_keys = [key for _, key in keys]
    since = local_midnight(now)
    cards = [c for c in (await port.cards(list_keys=list_keys) if list_keys else []) if archive_kept(c, archived)]
    parents = [p for p in [await port.card(pid) for pid in foreign_parent_ids(scope, cards)] if p is not None]
    if parents and scope.startswith("company:"):
        alpha = await body.run_db(lambda conn: [r["thread_key"] for r in conn.execute(
            "SELECT thread_key FROM swarm_agents WHERE rank = 'alpha' AND torn_down_at IS NULL")])
        parents = sysop_owned(scope, parents, [SHARED_LIST, *alpha])
    rules = (await port.policy_read("rules", {"list_keys": list_keys}))["rules"]
    win = await port.policy_read("wins", {"list_keys": list_keys, "since": since})
    held = [c for c in [*cards, *parents] if c["holder"] is not None]
    holders = await body.run_db(lambda conn: holder_names(conn, [c["holder"]["agent_id"] for c in held]))
    name_holders([*cards, *parents], holders)
    return compose(scope, filter, done_limit, keys, names, cards, rules, win, since, parents)
