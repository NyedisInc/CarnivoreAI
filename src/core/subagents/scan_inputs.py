
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from src.core.stat_gate.dir_names import entry_names
from src.core.subagents.parent_index import CompletionIndex

AGENT_FILE_PREFIX = "agent-"

FileTimes = Optional[Tuple[int, int, int]]
AgentFilesSignature = Optional[Tuple[Tuple[str, FileTimes], ...]]


def agent_files_signature(directory: Path) -> AgentFilesSignature:
    try:
        names = entry_names(directory)
    except FileNotFoundError:
        return ()
    except OSError:
        return None
    signature = []
    for name in names:
        if not name.startswith(AGENT_FILE_PREFIX):
            continue
        try:
            stat = os.stat(os.path.join(directory, name))
            times: FileTimes = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
        except OSError:
            times = None
        signature.append((name, times))
    return tuple(signature)


def index_snapshot(index: Optional[CompletionIndex]) -> Optional[Tuple[Tuple, Tuple]]:
    if index is None:
        return None
    return (tuple(sorted(index.by_agent_id.items())), tuple(sorted(index.by_tool_use.items())))


__all__ = ["agent_files_signature", "index_snapshot"]
