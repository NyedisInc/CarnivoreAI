
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

SF_DATALESS: int = getattr(stat, "SF_DATALESS", 0x40000000)

STATUS_BLANK = "blank"
STATUS_UNPARSEABLE = "unparseable"
STATUS_NON_OBJECT = "non_object"
STATUS_TORN = "torn"


def claude_files(root: Path) -> List[Tuple[Path, str]]:
    found: List[Tuple[Path, str]] = []
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        parts = Path(dirpath).parts
        scope = "subagent" if "subagents" in parts else "main"
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            kind = "workflow_journal" if scope == "subagent" and "workflows" in parts else scope
            found.append((Path(dirpath) / name, kind))
    return sorted(found)


def codex_files(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("rollout-*.jsonl") if p.is_file())


def is_dataless(path: Path) -> bool:
    try:
        return bool(getattr(os.lstat(path), "st_flags", 0) & SF_DATALESS)
    except OSError:
        return False


def iter_lines(path: Path) -> Iterator[Tuple[str, Optional[dict]]]:
    """Yield ``(status, obj)`` for every line of one JSONL file. Output: iterator.

    Inputs: path (Path). ``status`` is ``ok`` with the decoded object, or one of
    the ``STATUS_*`` names with None. Raises OSError when the file cannot be opened.
    """
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                yield STATUS_TORN, None
                continue
            body = raw.rstrip(b"\r\n")
            if not body.strip():
                yield STATUS_BLANK, None
                continue
            try:
                obj = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                yield STATUS_UNPARSEABLE, None
                continue
            if not isinstance(obj, dict):
                yield STATUS_NON_OBJECT, None
                continue
            yield "ok", obj


def read_text_lines(path: Path) -> Iterator[Tuple[str, Optional[str]]]:
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                yield STATUS_TORN, None
                continue
            try:
                yield "line", raw.decode("utf-8")
            except UnicodeDecodeError:
                yield "undecodable", None


FileTask = Tuple[str, str, str]
"""One unit of work: (family, scope, absolute path)."""


def build_tasks(claude_roots: List[Path], codex_roots: List[Path]) -> List[FileTask]:
    tasks: List[FileTask] = []
    for root in claude_roots:
        if root.is_dir():
            tasks.extend(("claude", scope, str(p)) for p, scope in claude_files(root))
    for root in codex_roots:
        if root.is_dir():
            tasks.extend(("codex", "rollout", str(p)) for p in codex_files(root))
    return tasks


def run_pool(tasks: List[FileTask], worker: Callable, merge: Callable, jobs: int) -> None:
    chunks = [tasks[i:i + 64] for i in range(0, len(tasks), 64)]
    if jobs <= 1:
        for chunk in chunks:
            merge(worker(chunk))
        return
    from multiprocessing import Pool

    with Pool(processes=jobs) as pool:
        for result in pool.imap_unordered(worker, chunks):
            merge(result)
