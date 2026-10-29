
from __future__ import annotations

import hashlib
import os
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence

MEMORY_PREFIX = "memory/"
INDEX_FILE = "memory/MEMORY.md"


def first_to_target(conn: sqlite3.Connection, project_id: int, target_install_id: str, op_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pack_session_moves WHERE role = 'source' AND state = 'moved' AND target_install_id = ? AND id != ? "
        "AND session_uuid IN (SELECT session_uuid FROM sessions WHERE project_id = ?) LIMIT 1", (target_install_id, op_id, project_id)).fetchone()
    return row is None


def _left(left_behind: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(f"{item['what']} ({item['why']})" for item in left_behind)


def _moved(moved: Optional[Mapping[str, str]]) -> str:
    return "these folders moved too: " + "; ".join(f"{old} is now {new}" for old, new in sorted((moved or {}).items())) if moved else ""


def note_text(label: str, old_dir: str, new_dir: Optional[str], left_behind: Sequence[Mapping[str, Any]], moved: Optional[Mapping[str, str]] = None) -> str:
    lines = [f"you were moved to {label}. the conversation is the same one and it resumed there."]
    lines.append(f"your project folder there is {new_dir}. here it was {old_dir}." if new_dir else f"here your project folder was {old_dir}.")
    lines.append(f"paths in your earlier messages that start with {old_dir} now start with {new_dir}." if new_dir and new_dir != old_dir else "")
    lines.append(_moved(moved) + "." if moved else "")
    if left_behind:
        lines.append(f"these stayed behind on the old computer: {_left(left_behind)}.")
    return "\n".join(line for line in lines if line) + "\n"


def paste_text(label: str, old_dir: str, new_dir: Optional[str], left_behind: Sequence[Mapping[str, Any]], moved: Optional[Mapping[str, str]] = None) -> str:
    where = f"your project folder there is {new_dir} (it was {old_dir})" if new_dir else f"your project folder was {old_dir}"
    tail = f" these stayed behind on the old computer: {_left(left_behind)}." if left_behind else ""
    return f"you moved to {label}. {where}.{tail}" + (f" {_moved(moved)}." if moved else "")


def _entry(rel: str, path: str, data: bytes) -> Dict[str, Any]:
    with open(path, "wb") as out:
        out.write(data)
    return {"rel": rel, "path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def add_note(files: List[Dict[str, Any]], work: str, op_id: str, label: str, text: str) -> List[Dict[str, Any]]:
    os.makedirs(work, mode=0o700, exist_ok=True)
    name = f"moved-{op_id[:8]}.md"
    out = []
    for item in files:
        if item["rel"] == INDEX_FILE:
            with open(item["path"], "rb") as handle:
                data = handle.read()
            line = f"- [moved to {label}]({name}) where your project folder is now\n".encode()
            item = _entry(INDEX_FILE, os.path.join(work, "MEMORY.md"), data + (b"" if data.endswith(b"\n") or not data else b"\n") + line)
        out.append(item)
    out.append(_entry(MEMORY_PREFIX + name, os.path.join(work, name), text.encode()))
    return out
