
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from src.core.stat_gate.dir_names import entry_names
from src.core.subagents import launch_memo
from src.core.subagents.parent_index import CompletionIndex

AGENT_FILE_PREFIX = "agent-"

FileTimes = Optional[Tuple[int, int, int]]
AgentFilesSignature = Optional[Tuple[Tuple[str, FileTimes], ...]]


def agent_files_signature(directory: Path) -> AgentFilesSignature:
    return agent_files_signature_read(directory)[0]


def agent_files_signature_read(directory: Path) -> Tuple[AgentFilesSignature, bool]:
    read_now: list = []

    def compute() -> Tuple[AgentFilesSignature, bool]:
        read_now.append(True)
        signature = read_agent_files_signature(directory)
        return signature, signature is not None and all(times is not None for _, times in signature)

    signature = launch_memo.remembered(str(directory), compute)
    return signature, bool(read_now)


def read_agent_files_signature(directory: Path) -> AgentFilesSignature:
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


__all__ = ["agent_files_signature", "agent_files_signature_read", "index_snapshot", "read_agent_files_signature"]
