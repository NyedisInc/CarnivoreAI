
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.db import transaction
from src.core.swarm import fact_index, facts, memory, store

logger = structlog.get_logger()

INDEX_FILE = "MEMORY.md"
BACKUP_CAP = 50
MAX_INDEX_CHARS = 64_000
_FACT_PATH_RE = re.compile(r"^facts/(f_[0-9a-f]{12})\.md$")
_BACKUP_ID_RE = re.compile(r"^\d{8}T\d{12}Z$")


class MemoryEditRefused(ValueError):
    pass


class MemoryEditNotFound(LookupError):
    pass


def _agent(conn: sqlite3.Connection, agent_id: int) -> Dict[str, Any]:
    agent = store.get_agent(conn, agent_id)
    if agent is None:
        raise MemoryEditNotFound("no such agent")
    return agent


def _mem(agent: Dict[str, Any]) -> Path:
    return memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])


def _fact_row(conn: sqlite3.Connection, agent_id: int, path: str) -> Optional[Dict[str, Any]]:
    if path == INDEX_FILE:
        return None
    m = _FACT_PATH_RE.match(path)
    if not m:
        raise MemoryEditRefused("only MEMORY.md and fact files can be edited")
    row = conn.execute("SELECT * FROM swarm_facts WHERE id = ? AND agent_id = ? AND state <> 'killed'",
                       (m.group(1), agent_id)).fetchone()
    if row is None:
        raise MemoryEditNotFound("no such fact")
    return dict(row)


def _backup_dir(state_dir: Path, agent_id: int, path: str) -> Path:
    key = "MEMORY" if path == INDEX_FILE else Path(path).stem
    return Path(state_dir) / "swarm" / "memory-backups" / str(int(agent_id)) / key


def list_backups(state_dir: Path, agent_id: int, path: str) -> List[Dict[str, str]]:
    folder = _backup_dir(state_dir, agent_id, path)
    if not folder.is_dir():
        return []
    ids = sorted((p.stem for p in folder.glob("*.md") if _BACKUP_ID_RE.match(p.stem)), reverse=True)
    return [{"id": i, "at": datetime.strptime(i, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc).isoformat()} for i in ids]


def list_files(conn: sqlite3.Connection, agent_id: int) -> List[Dict[str, Any]]:
    _agent(conn, agent_id)
    rows = facts.list_for_agent(conn, agent_id)
    return [{"path": INDEX_FILE, "title": INDEX_FILE, "state": None}] + [
        {"path": f"facts/{r['id']}.md", "title": r["title"], "state": r["state"]} for r in rows]


def read_file(conn: sqlite3.Connection, state_dir: Path, agent_id: int, path: str) -> Dict[str, Any]:
    agent = _agent(conn, agent_id)
    _fact_row(conn, agent_id, path)
    target = _mem(agent) / path
    if not target.exists() and path != INDEX_FILE:
        raise MemoryEditNotFound("the fact's file is gone")
    text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    return {"path": path, "text": text, "backups": list_backups(state_dir, agent_id, path)}


def _write_backup(state_dir: Path, agent_id: int, path: str, text: str) -> str:
    folder = _backup_dir(state_dir, agent_id, path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    while (folder / f"{stamp}.md").exists():
        stamp = f"{stamp[:-7]}{int(stamp[-7:-1]) + 1:06d}Z"
    memory.atomic_write(folder / f"{stamp}.md", text)
    for old in [b["id"] for b in list_backups(state_dir, agent_id, path)][BACKUP_CAP:]:
        (folder / f"{old}.md").unlink(missing_ok=True)
    return stamp


def _write_fact(conn: sqlite3.Connection, agent: Dict[str, Any], row: Dict[str, Any], text: str) -> None:
    title, body, meta = fact_index._split_front(text, row["id"])
    if not body.strip():
        raise MemoryEditRefused("a fact needs some text; kill it instead of emptying it")
    if len(body) > facts.MAX_FACT_CHARS:
        raise MemoryEditRefused(f"a fact must be at most {facts.MAX_FACT_CHARS} characters")
    scope = meta.get("scope") if meta.get("scope") in memory.FACT_SCOPES else row["scope"]
    memory.write_fact(_mem(agent), memory.Fact(row["id"], title, scope, row["origin"], row["taught_at"], body,
                                               row["owner_message_ref"]))
    with transaction(conn):
        conn.execute("UPDATE swarm_facts SET title = ?, scope = ?, sha256 = ? WHERE id = ?",
                     (title, scope, hashlib.sha256(body.encode("utf-8")).hexdigest(), row["id"]))


def save_file(conn: sqlite3.Connection, state_dir: Path, agent_id: int, path: str, text: str) -> Dict[str, Any]:
    agent = _agent(conn, agent_id)
    row = _fact_row(conn, agent_id, path)
    mem = _mem(agent)
    target = mem / path
    if row is None:
        if len(text) > MAX_INDEX_CHARS:
            raise MemoryEditRefused(f"MEMORY.md must be at most {MAX_INDEX_CHARS} characters")
        memory.refuse_secrets(text, INDEX_FILE)
    else:
        memory.refuse_secrets(text, path)
    if target.exists():
        _write_backup(state_dir, agent_id, path, target.read_text(encoding="utf-8", errors="replace"))
    if row is None:
        memory.atomic_write(target, text)
    else:
        _write_fact(conn, agent, row, text)
    fact_index.refresh_agent(conn, agent)
    logger.info("swarm_memory_edited", agent_id=agent_id, path=path)
    return read_file(conn, state_dir, agent_id, path)


def restore_backup(conn: sqlite3.Connection, state_dir: Path, agent_id: int, path: str,
                   backup_id: Optional[str] = None) -> Dict[str, Any]:
    _fact_row(conn, agent_id, path)
    backups = list_backups(state_dir, agent_id, path)
    if backup_id is None:
        if not backups:
            raise MemoryEditNotFound("there is nothing to undo")
        backup_id = backups[0]["id"]
    if not _BACKUP_ID_RE.match(backup_id) or backup_id not in {b["id"] for b in backups}:
        raise MemoryEditNotFound("no such backup")
    text = (_backup_dir(state_dir, agent_id, path) / f"{backup_id}.md").read_text(encoding="utf-8", errors="replace")
    return save_file(conn, state_dir, agent_id, path, text)
