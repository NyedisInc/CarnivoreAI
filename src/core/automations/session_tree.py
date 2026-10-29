from __future__ import annotations

from contextlib import closing
from typing import Any, AbstractSet, Dict, Iterable, List, Optional, Sequence

UNASSIGNED_KEY = "unassigned"


def project_of(automation: Dict[str, Any]) -> Optional[int]:
    if automation.get("project_id") is not None:
        return automation["project_id"]
    own = (automation.get("target") or {}).get("project_id")
    return own if isinstance(own, int) and not isinstance(own, bool) else None


def names_session(automation: Dict[str, Any], session_uuid: str) -> bool:
    target = automation.get("target") or {}
    return target.get("kind") == "session_message" and str(target.get("session_uuid") or "") == session_uuid


def matches_session(automation: Dict[str, Any], session_uuid: str, project_id: Optional[int]) -> bool:
    return names_session(automation, session_uuid) or (project_id is not None and project_of(automation) == project_id)


def file_of(automation: Dict[str, Any], sessions_by_uuid: Dict[str, Dict[str, Any]],
            project_ids: Optional[AbstractSet[int]] = None) -> Dict[str, Optional[Any]]:
    def listed(pid: Any) -> Optional[int]:
        return pid if pid is not None and (project_ids is None or pid in project_ids) else None

    target = automation.get("target") or {}
    uuid = str(target.get("session_uuid") or "") if target.get("kind") == "session_message" else ""
    if uuid and uuid in sessions_by_uuid:
        return {"session_uuid": uuid, "project_id": listed(sessions_by_uuid[uuid].get("project_id"))}
    return {"session_uuid": None, "project_id": listed(project_of(automation))}


def _node(kind: str, key: str, label: str, project_id: Optional[int], session_uuid: Optional[str]) -> Dict[str, Any]:
    return {"key": key, "kind": kind, "label": label, "project_id": project_id, "session_uuid": session_uuid, "automations": [],
            "children": [], "next_fire_at": None, "last_run": None, "count": 0}


def _run_time(run: Dict[str, Any]) -> float:
    for field in ("ended_at", "started_at", "slot_at"):
        if run.get(field) is not None:
            return run[field]
    return 0


def _roll(node: Dict[str, Any]) -> None:
    next_fire: Optional[float] = None
    last: Optional[Dict[str, Any]] = None
    count = len(node["automations"])

    def consider(fire_at: Optional[float], run: Optional[Dict[str, Any]]) -> None:
        nonlocal next_fire, last
        if fire_at is not None and (next_fire is None or fire_at < next_fire):
            next_fire = fire_at
        if run and (last is None or _run_time(run) > _run_time(last)):
            last = run

    for a in node["automations"]:
        consider(a.get("next_fire_at") if a.get("enabled") else None, a.get("last_run"))
    for child in node["children"]:
        _roll(child)
        consider(child["next_fire_at"], child["last_run"])
        count += child["count"]
    node["next_fire_at"], node["last_run"], node["count"] = next_fire, last, count


def _by_label(node: Dict[str, Any]) -> str:
    return str(node["label"]).casefold()


def build_tree(projects: Iterable[Dict[str, Any]], sessions: Iterable[Dict[str, Any]], automations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes = {p["id"]: _node("project", f"project:{p['id']}", p["name"], p["id"], None) for p in projects if p.get("id") is not None}
    unassigned = _node("unassigned", UNASSIGNED_KEY, "", None, None)
    leaves: Dict[str, Dict[str, Any]] = {}
    for s in sessions:
        uuid = s.get("session_uuid")
        if not uuid or s.get("archived_at"):
            continue
        pid = s.get("project_id")
        home = nodes.get(pid) if pid is not None else None
        leaf = _node("session", f"session:{uuid}", s.get("tmux_name") or s.get("name") or "", pid if home else None, uuid)
        leaves[uuid] = leaf
        (home or unassigned)["children"].append(leaf)
    for a in automations:
        filed = file_of(a, leaves, set(nodes))
        home = leaves.get(filed["session_uuid"]) if filed["session_uuid"] else nodes.get(filed["project_id"])
        (home or unassigned)["automations"].append(a)
    top = sorted(nodes.values(), key=_by_label)
    if unassigned["automations"] or unassigned["children"]:
        top.append(unassigned)
    for parent in top:
        parent["children"].sort(key=_by_label)
        parent["automations"].sort(key=lambda a: str(a["name"]).casefold())
        for child in parent["children"]:
            child["automations"].sort(key=lambda a: str(a["name"]).casefold())
        _roll(parent)
    return top


def prune_empty(tree: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept = []
    for node in tree:
        if node["count"] > 0:
            kept.append({**node, "children": prune_empty(node["children"])})
    return kept


def read_inputs() -> Dict[str, List[Dict[str, Any]]]:
    from src.config import settings
    from src.core import session_store
    from src.core.db import connect, db_path_for
    from src.core.project_writes import list_projects_ordered

    path = db_path_for(settings.get_state_dir())
    if not path.exists():
        return {"projects": [], "sessions": []}
    with closing(connect(path, create=False)) as conn:
        projects = [{"id": p["id"], "name": p.get("display_name") or p.get("name") or ""} for p in list_projects_ordered(conn)]
        rows = session_store.list_sessions(conn, include_automated=False)
    sessions = [{"session_uuid": r.get("session_uuid"), "tmux_name": r.get("tmux_name"), "name": None, "project_id": r.get("project_id"),
                 "archived_at": r.get("archived_at")} for r in rows]
    return {"projects": projects, "sessions": sessions}
