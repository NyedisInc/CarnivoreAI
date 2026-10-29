
from __future__ import annotations

import base64
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core.companion_shell.rows import exclude_clause
from src.core.db import transaction
from src.core.pack.migrate import task_manager_side
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

MAX_FILES_BYTES = 2 * 1024 * 1024
SESSION_COLUMNS = ("session_uuid", "project_attribution", "origin", "agent_type", "agent_family", "agent_family_source", "model",
                   "claude_session_uuid", "claude_session_uuid_source", "title", "claude_title", "pinned_theme", "created_at")
_AGENT_SKIP = frozenset({"id", "parent_id", "session_row_id", "project_id", "company_id", "state", "turn_authority", "turn_opened_at",
                         "torn_down_at", "repo_dir", "updated_at", "host_key"})


class ManifestError(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def reroot(path: Optional[str], old_root: str, new_root: str) -> str:
    if path:
        rel = os.path.relpath(path, old_root)
        if rel == ".":
            return new_root
        if not rel.startswith(".."):
            return os.path.join(new_root, rel)
    return new_root


def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root)


def _agent_files(agents: List[Dict[str, Any]], root: str) -> Dict[str, str]:
    from src.core.swarm.memory import SCOPE_LOCAL, SCOPE_PROJECT, memory_dir

    out: Dict[str, str] = {}
    total = 0
    for agent in agents:
        slug = agent["slug"]
        paths = [Path(root) / ".claude" / "agents" / f"{slug}.md", Path(root) / ".codex" / "agents" / f"{slug}.toml"]
        for scope in (SCOPE_PROJECT, SCOPE_LOCAL):
            base = memory_dir(Path(root), slug, scope)
            if base.is_dir():
                paths += [p for p in sorted(base.rglob("*")) if p.is_file() and not p.is_symlink()]
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            size = path.stat().st_size
            if total + size > MAX_FILES_BYTES:
                logger.warning("pack_migrate_agent_files_capped", agent=slug)
                return out
            total += size
            out[_rel(str(path), root)] = base64.b64encode(path.read_bytes()).decode("ascii")
    return out


def thread_key_here(agent: Mapping[str, Any], project_id: int) -> str:
    return str(project_id) if agent.get("rank") == "project" else agent["thread_key"]


def collect(conn: sqlite3.Connection, project: Mapping[str, Any], state_dir: str) -> Dict[str, Any]:
    pid, root = project["id"], project["root"]
    company = None
    if project.get("company_id") is not None:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (project["company_id"],)).fetchone()
        if row is not None:
            hq = conn.execute("SELECT uid FROM projects WHERE id = ?", (row["hq_project_id"],)).fetchone() if row["hq_project_id"] else None
            company = {"uid": row["uid"], "name": row["name"], "accounts": row["accounts"], "hue": row["hue"], "hq_project_uid": hq[0] if hq else None}
    sessions = []
    for row in conn.execute(f"SELECT * FROM sessions WHERE project_id = ?{exclude_clause(conn)} ORDER BY id", (pid,)).fetchall():
        entry = {c: row[c] for c in SESSION_COLUMNS}
        entry["working_dir_rel"] = _rel(row["working_dir"], root) if row["working_dir"] and not _rel(row["working_dir"], root).startswith("..") else "."
        sessions.append(entry)
    agent_rows = [dict(r) for r in conn.execute(
        "SELECT * FROM swarm_agents WHERE project_id = ? AND torn_down_at IS NULL ORDER BY id", (pid,)).fetchall()]
    by_id = {a["id"]: a for a in agent_rows}
    agents = []
    for a in agent_rows:
        entry = {k: v for k, v in a.items() if k not in _AGENT_SKIP}
        entry["parent_thread_key"] = by_id[a["parent_id"]]["thread_key"] if a["parent_id"] in by_id else None
        entry["repo_dir_rel"] = _rel(a["repo_dir"], root) if not _rel(a["repo_dir"], root).startswith("..") else "."
        entry["source_id"] = a["id"]
        agents.append(entry)
    return {
        "version": 1,
        "project": {k: project.get(k) for k in ("uid", "display_name", "description", "short_description", "default_agent_type", "color",
                                                "air_gap", "github_account")},
        "company": company, "sessions": sessions, "agents": agents, "agent_files": _agent_files(agent_rows, root),
        "huddle": task_manager_side.export_list(state_dir, str(pid)),
    }


def summary(manifest: Mapping[str, Any]) -> Dict[str, int]:
    items = manifest["huddle"]["items"]
    return {"sessions": len(manifest["sessions"]), "agents": len(manifest["agents"]), "cards": len(items),
            "messages": len(manifest["huddle"]["messages"]), "groups": len(manifest["huddle"]["groups"]),
            "agent_files": len(manifest["agent_files"])}


def _under(root: str, rel: str) -> str:
    if rel == ".":
        return root
    if os.path.isabs(rel) or ".." in Path(rel).parts:
        raise ManifestError("bad_path", "the project's rows name a folder outside the project")
    return os.path.join(root, rel)


def _insert(conn: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> int:
    cur = conn.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", tuple(values.values()))
    return int(cur.lastrowid)


def apply(conn: sqlite3.Connection, manifest: Mapping[str, Any], *, project_id: int, target_root: str,
          state_dir: str, undo: Dict[str, Any]) -> Dict[str, Any]:
    stamp = utc_now()
    company_id = conn.execute("SELECT company_id FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    undo.setdefault("session_ids", [])
    undo.setdefault("session_before", {})
    undo.setdefault("agent_ids", [])
    undo.setdefault("agent_before", {})
    undo.setdefault("files", [])
    try:
        with transaction(conn):
            for s in manifest["sessions"]:
                working_dir = _under(target_root, s["working_dir_rel"])
                found = conn.execute("SELECT * FROM sessions WHERE session_uuid = ?", (s["session_uuid"],)).fetchone()
                values = {c: s[c] for c in SESSION_COLUMNS if c != "session_uuid"}
                values.update(working_dir=working_dir, project_id=project_id, lifecycle="stopped", updated_at=stamp)
                if found is None:
                    undo["session_ids"].append(_insert(conn, "sessions", {"session_uuid": s["session_uuid"], **values}))
                else:
                    undo["session_before"][str(found["id"])] = {k: found[k] for k in values}
                    conn.execute(f"UPDATE sessions SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), found["id"]))
            id_of: Dict[str, int] = {}
            ordered = sorted(manifest["agents"], key=lambda a: a["parent_thread_key"] is not None)
            agent_map: Dict[int, int] = {}
            for a in ordered:
                key = thread_key_here(a, project_id)
                found = conn.execute("SELECT * FROM swarm_agents WHERE thread_key = ? AND torn_down_at IS NULL", (key,)).fetchone()
                have = {r[1] for r in conn.execute("PRAGMA table_info(swarm_agents)")}
                values = {k: v for k, v in a.items() if k in have and k not in _AGENT_SKIP and k != "source_id"}
                values.update(repo_dir=_under(target_root, a["repo_dir_rel"]),
                              project_id=project_id, company_id=company_id, thread_key=key,
                              parent_id=id_of.get(a["parent_thread_key"]), session_row_id=None, state="asleep", turn_authority=None,
                              turn_opened_at=None, updated_at=stamp)
                if found is None:
                    new_id = _insert(conn, "swarm_agents", values)
                    undo["agent_ids"].append(new_id)
                else:
                    new_id = found["id"]
                    undo["agent_before"][str(new_id)] = {k: found[k] for k in values if k in found.keys()}
                    conn.execute(f"UPDATE swarm_agents SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), new_id))
                id_of[a["thread_key"]] = new_id
                agent_map[a["source_id"]] = new_id
            company = manifest.get("company")
            if company and company.get("hq_project_uid") and company_id is not None:
                hq = conn.execute("SELECT id FROM projects WHERE uid = ?", (company["hq_project_uid"],)).fetchone()
                if hq is not None:
                    conn.execute("UPDATE companies SET hq_project_id = ? WHERE id = ? AND hq_project_id IS NULL", (hq[0], company_id))
    except sqlite3.IntegrityError as exc:
        logger.warning("pack_migrate_row_refused", error=str(exc)[:120])
        raise ManifestError("agent_conflict", "this computer already holds a different agent or session that conflicts with the project's") from exc
    for rel, blob in manifest["agent_files"].items():
        dest = Path(target_root) / rel
        if ".." in Path(rel).parts or rel.startswith("/") or dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(blob))
        undo["files"].append(rel)
    undo["huddle"] = task_manager_side.import_list(state_dir, str(project_id), manifest["huddle"], agent_map)
    return {**summary(manifest), "task_files_not_copied": list(undo["huddle"].get("task_files_dropped", []))}


def undo_rows(conn: sqlite3.Connection, undo: Mapping[str, Any], *, target_root: Optional[str], project_id: Optional[int], state_dir: str) -> None:
    with transaction(conn):
        for sid in undo.get("session_ids", []):
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        for sid, before in undo.get("session_before", {}).items():
            conn.execute(f"UPDATE sessions SET {', '.join(f'{k} = ?' for k in before)} WHERE id = ?", (*before.values(), int(sid)))
        for aid in reversed(undo.get("agent_ids", [])):
            conn.execute("DELETE FROM swarm_agents WHERE id = ?", (aid,))
        for aid, before in undo.get("agent_before", {}).items():
            conn.execute(f"UPDATE swarm_agents SET {', '.join(f'{k} = ?' for k in before)} WHERE id = ?", (*before.values(), int(aid)))
    if target_root:
        for rel in undo.get("files", []):
            (Path(target_root) / rel).unlink(missing_ok=True)
    if undo.get("huddle") is not None and project_id is not None:
        task_manager_side.undo(state_dir, str(project_id), undo["huddle"])
