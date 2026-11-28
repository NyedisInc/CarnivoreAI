
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

AGY_HOME = Path.home() / ".gemini" / "antigravity-cli"
FAMILY = "agy"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_LOGS = (".system_generated", "logs")
MAX_LINE_BYTES = 4 * 1024 * 1024


def valid_id(conversation_id: Optional[str]) -> bool:
    return bool(conversation_id) and bool(_UUID.match(str(conversation_id)))


def brain_dir(conversation_id: str, home: Optional[Path] = None) -> Optional[Path]:
    if not valid_id(conversation_id):
        return None
    path = Path(home or AGY_HOME) / "brain" / str(conversation_id)
    return path if path.is_dir() and not path.is_symlink() else None


def transcript_path(conversation_id: str, home: Optional[Path] = None, *, full: bool = False) -> Optional[Path]:
    base = brain_dir(conversation_id, home)
    if base is None:
        return None
    path = base.joinpath(*_LOGS, "transcript_full.jsonl" if full else "transcript.jsonl")
    return path if path.is_file() and not path.is_symlink() else None


def store_path(conversation_id: str, home: Optional[Path] = None) -> Optional[Path]:
    if not valid_id(conversation_id):
        return None
    path = Path(home or AGY_HOME) / "conversations" / f"{conversation_id}.db"
    return path if path.is_file() and not path.is_symlink() else None


def iter_conversations(home: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    root = Path(home or AGY_HOME) / "brain"
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return
    for name in names:
        path = transcript_path(name, home)
        if path is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        yield {"id": name, "path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _text(record: Dict[str, Any]) -> str:
    content = record.get("content")
    if isinstance(content, str) and content:
        return content
    calls = record.get("tool_calls")
    if isinstance(calls, list):
        return " ".join(f"{c.get('name')} {json.dumps(c.get('args'), separators=(',', ':'))}"
                        for c in calls if isinstance(c, dict) and isinstance(c.get("name"), str))
    return ""


def read_messages(path: Path, *, limit: int = 0) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    try:
        with open(path, "rb") as handle:
            for raw in handle:
                if len(raw) > MAX_LINE_BYTES:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                kind = rec.get("type")
                role = "user" if kind == "USER_INPUT" else "assistant" if kind == "PLANNER_RESPONSE" else None
                content = rec.get("content")
                if role is None or not isinstance(content, str) or not content.strip():
                    continue
                out.append({"role": role, "text": content, "at": str(rec.get("created_at") or "")})
    except OSError:
        return []
    return out[-limit:] if limit > 0 else out


def carry_files(conversation_id: str, home: Optional[Path] = None) -> List[Dict[str, Any]]:
    base, files = Path(home or AGY_HOME), []
    brain = brain_dir(conversation_id, base)
    if brain is not None:
        for dirpath, dirnames, names in os.walk(brain, followlinks=False):
            dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
            for name in names:
                path = Path(dirpath) / name
                if path.is_symlink() or not path.is_file():
                    continue
                files.append({"rel": path.relative_to(base).as_posix(), "path": str(path), "size": path.stat().st_size})
    store = store_path(conversation_id, base)
    if store is not None:
        files.append({"rel": f"conversations/{conversation_id}.db", "path": str(store), "size": store.stat().st_size})
    return sorted(files, key=lambda f: f["rel"])
