
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_LINE_BYTES = 4 * 1024 * 1024


def copilot_home() -> Path:
    return Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")


def events_path(conversation_id: Optional[str], home: Optional[Path] = None) -> Optional[Path]:
    if not conversation_id or not _UUID.match(str(conversation_id)):
        return None
    path = Path(home or copilot_home()) / "session-state" / str(conversation_id) / "events.jsonl"
    return path if path.is_file() and not path.is_symlink() else None


def iter_events(path: Path, types: tuple) -> Iterator[Dict[str, Any]]:
    needles = [f'"{t}"'.encode() for t in types]
    try:
        with open(path, "rb") as handle:
            for raw in handle:
                if len(raw) > MAX_LINE_BYTES or not any(n in raw[:200] for n in needles):
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("type") in types and isinstance(rec.get("data"), dict):
                    yield dict(rec["data"], _type=rec["type"])
    except OSError:
        return


def read_prompts(conversation_id: Optional[str], home: Optional[Path] = None) -> List[str]:
    path = events_path(conversation_id, home)
    if path is None:
        return []
    return [d["content"].strip() for d in iter_events(path, ("user.message",))
            if isinstance(d.get("content"), str) and d["content"].strip()]
