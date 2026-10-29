
from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from src.core.claude_resume_argv import read_ps_text


PROBE_TIMEOUT_SECONDS: float = 10.0
LSOF_TIMEOUT_SECONDS: float = 3.0

_LSTART_TOKENS: int = 5

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_RESUME_RE = re.compile(r"--resume[= ]+([0-9a-fA-F-]{36})")

SOURCE_PID_RECORD: str = "claude_pid_record"
SOURCE_ARGV: str = "argv_resume"
SOURCE_NONE: str = "unidentified"

CONFLICT_LIVE_WRITER: str = "conversation_open_in_live_process"
CONFLICT_SAME_DIR_UNIDENTIFIED: str = "unidentified_claude_in_same_directory"


class MeasureError(Exception):
    """A probe could not run at all. Distinct from "ran and found nothing"."""


@dataclass(frozen=True)
class Proc:

    pid: int
    ppid: int
    lstart: str
    command: str


@dataclass(frozen=True)
class Writer:

    pid: int
    conversation: Optional[str]
    source: str
    cwd: Optional[str] = None
    tmux: Optional[str] = None
    command: str = ""

    @property
    def where(self) -> str:
        if self.tmux:
            return f"tmux {self.tmux.split(':', 1)[0]}"
        return "outside tmux"

    def as_dict(self) -> dict:
        return {
            "pid": self.pid, "conversation": self.conversation,
            "source": self.source, "cwd": self.cwd, "tmux": self.tmux,
        }


@dataclass
class ProcessTable:

    rows: Dict[int, Proc] = field(default_factory=dict)
    children: Dict[int, List[int]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows: Iterable[Proc]) -> "ProcessTable":
        table = cls()
        for row in rows:
            table.rows[row.pid] = row
            table.children.setdefault(row.ppid, []).append(row.pid)
        return table

    def descendants(self, root: int) -> List[Proc]:
        out: List[Proc] = []
        queue = [root]
        seen = set()
        while queue:
            pid = queue.pop(0)
            if pid in seen or pid not in self.rows:
                continue
            seen.add(pid)
            out.append(self.rows[pid])
            queue.extend(sorted(self.children.get(pid, [])))
        return out


def parse_ps_line(line: str) -> Optional[Proc]:
    parts = line.split()
    if len(parts) < 2 + _LSTART_TOKENS + 1:
        return None
    try:
        pid, ppid = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    lstart = " ".join(parts[2:2 + _LSTART_TOKENS])
    head = re.match(r"\s*\d+\s+\d+\s+(\S+\s+){%d}" % _LSTART_TOKENS, line)
    command = line[head.end():] if head else " ".join(parts[2 + _LSTART_TOKENS:])
    return Proc(pid=pid, ppid=ppid, lstart=lstart, command=command.rstrip("\n"))


def read_process_table(max_age: float = 0.0) -> ProcessTable:
    """Take the process table in one ``ps`` call (or the shared one no older than ``max_age``).

    Inputs: max_age (float) - seconds; 0 (the default, every guard) always runs ``ps``,
      a periodic observer passes ``SHARED_TABLE_MAX_AGE_SECONDS`` to share the watcher's run.
    Output: ProcessTable.
    Raises: MeasureError when ps cannot run - an empty table would read as
      "no writers anywhere", which is the one wrong answer a guard cannot give.
    """
    text = read_ps_text(max_age, PROBE_TIMEOUT_SECONDS)
    if text is None:
        raise MeasureError("ps could not run or exited non-zero")
    rows = [r for r in (parse_ps_line(l) for l in text.splitlines()) if r]
    if not rows:
        raise MeasureError("ps returned no rows")
    return ProcessTable.from_rows(rows)


def normalise_lstart(value: str) -> str:
    return " ".join(str(value).split())


_CTIME_FORMAT: str = "%a %b %d %H:%M:%S %Y"


def same_process_start(ps_lstart: str, proc_start: str) -> bool:
    a, b = normalise_lstart(ps_lstart), normalise_lstart(proc_start)
    if not a or not b:
        return False
    if a == b:
        return True
    try:
        local_epoch = time.mktime(time.strptime(a, _CTIME_FORMAT))
        utc_epoch = calendar.timegm(time.strptime(b, _CTIME_FORMAT))
    except (ValueError, OverflowError):
        return False
    return abs(local_epoch - utc_epoch) < 1.0


def read_pid_record(pid: int, record_dir: Optional[Path] = None) -> Optional[dict]:
    if record_dir is not None:
        dirs: Sequence[Path] = (record_dir,)
    else:
        from src.core.claude_config.profile_roots import claude_registry_roots

        dirs = claude_registry_roots()
    for directory in dirs:
        try:
            return json.loads((directory / f"{pid}.json").read_text())
        except (OSError, ValueError):
            continue
    return None


def resume_uuid_in(command: str) -> Optional[str]:
    match = _RESUME_RE.search(command or "")
    if not match:
        return None
    value = match.group(1).lower()
    return value if _UUID_RE.match(value) else None


def process_cwd(pid: int) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["/usr/sbin/lsof", "-b", "-w", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, timeout=LSOF_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return os.path.realpath(line[1:])
    return None


def identify_writer(
    proc: Proc,
    record: Optional[dict],
    *,
    cwd_probe: Callable[[int], Optional[str]] = process_cwd,
) -> Writer:
    if record and same_process_start(proc.lstart, str(record.get("procStart") or "")):
        sid = str(record.get("sessionId") or "").lower()
        if _UUID_RE.match(sid):
            cwd = record.get("cwd")
            return Writer(
                pid=proc.pid, conversation=sid, source=SOURCE_PID_RECORD,
                cwd=os.path.realpath(cwd) if cwd else None,
                tmux=record.get("tmux"), command=proc.command,
            )
    cwd = None
    if record and record.get("cwd"):
        cwd = os.path.realpath(str(record["cwd"]))
    argv_uuid = resume_uuid_in(proc.command)
    if argv_uuid and "--fork-session" not in proc.command:
        return Writer(
            pid=proc.pid, conversation=argv_uuid, source=SOURCE_ARGV,
            cwd=cwd or cwd_probe(proc.pid), command=proc.command,
        )
    return Writer(
        pid=proc.pid, conversation=None, source=SOURCE_NONE,
        cwd=cwd or cwd_probe(proc.pid), command=proc.command,
    )


def live_writers(
    table: ProcessTable,
    is_claude: Callable[[str], bool],
    *,
    record_dir: Optional[Path] = None,
    cwd_probe: Callable[[int], Optional[str]] = process_cwd,
) -> List[Writer]:
    out = []
    for pid in sorted(table.rows):
        proc = table.rows[pid]
        if is_claude(proc.command):
            out.append(identify_writer(proc, read_pid_record(pid, record_dir), cwd_probe=cwd_probe))
    return out


def first_claude_under(
    table: ProcessTable, pane_pid: int, is_claude: Callable[[str], bool]
) -> Optional[Proc]:
    for proc in table.descendants(pane_pid):
        if is_claude(proc.command):
            return proc
    return None


def transcript_paths(conversation: Optional[str], root: Optional[Path] = None) -> List[str]:
    if not conversation or not _UUID_RE.match(conversation):
        return []
    if root is not None:
        roots: Sequence[Path] = (root,)
    else:
        from src.core.claude_config.transcript_roots import claude_transcript_roots

        roots = claude_transcript_roots()
    found: Dict[str, str] = {}
    for base in roots:
        for path in base.glob(f"*/{conversation}.jsonl"):
            found.setdefault(os.path.realpath(path), str(path))
    return sorted(found.values())


def file_facts(paths: Sequence[str]) -> List[dict]:
    facts = []
    for path in paths:
        try:
            st = os.stat(path)
            facts.append({"path": path, "bytes": st.st_size, "mtime": int(st.st_mtime)})
        except OSError as exc:
            facts.append({"path": path, "error": str(exc)})
    return facts


def writer_conflict(
    conversation: Optional[str],
    resume_cwd: Optional[str],
    writers: Iterable[Writer],
) -> Optional[Tuple[str, str]]:
    writers = list(writers)
    if conversation:
        for w in writers:
            if w.conversation == conversation:
                return (
                    CONFLICT_LIVE_WRITER,
                    f"already running elsewhere: claude pid {w.pid} "
                    f"({w.where}) has this conversation open",
                )
    if resume_cwd:
        for w in writers:
            if w.conversation is None and w.cwd == resume_cwd:
                return (
                    CONFLICT_SAME_DIR_UNIDENTIFIED,
                    f"claude pid {w.pid} ({w.where}) is running in this "
                    "folder and its conversation could not be identified",
                )
    return None
